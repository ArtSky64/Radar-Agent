import logging
import config
from dedup import text_to_vector, is_duplicate, flush_embeddings_cache
from agent_manager import analyze_article, analyze_dataset, DatasetCard, AnalysisError
from database import (
    init_db,
    get_all_vectors,
    save_vector,
    save_article,
    delete_old_vectors,
    save_trending_models,
    upsert_related_material,
    is_vector_duplicate_db,
    get_existing_article_urls,
)
from hf_datasets_fetcher import stream_hf_datasets_by_mode
from kaggle_fetcher import stream_kaggle_articles
from papers_fetcher import stream_papers_articles
from github_fetcher import run_github_trending_pipeline
from hf_trending_fetcher import fetch_trending_models
import arena_scraper


class _BenignProactorNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Cancelling an overlapped future failed" not in record.getMessage()


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("asyncio").addFilter(_BenignProactorNoiseFilter())

    error_handler = logging.FileHandler(config.ERROR_LOG_FILE, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s"))
    logging.getLogger().addHandler(error_handler)


logger = logging.getLogger("main")


def _tag_source_type(articles, source_type: str):
    for article in articles:
        article.setdefault("source_type", source_type)
        yield article


def stream_all_new_articles():
    for mode in config.HF_DATASET_MODES:
        try:
            yield from _tag_source_type(stream_hf_datasets_by_mode(mode), "датасет")
        except Exception as e:
            logger.error(f"Источник Hugging Face (датасеты, режим='{mode}') недоступен: {e}")

    try:
        yield from _tag_source_type(stream_papers_articles(), "статья")
    except Exception as e:
        logger.error(f"Источник Papers недоступен: {e}")

    try:
        yield from _tag_source_type(stream_kaggle_articles(), "датасет")
    except Exception as e:
        logger.error(f"Источник Kaggle недоступен: {e}")


def _refresh_trending_models():
    try:
        models = fetch_trending_models(limit=30)
        if not models:
            logger.info("Трендовые модели HF не получены.")
            return
        save_trending_models(models)
        logger.info(f"Витрина трендовых моделей HF обновлена: {len(models)} шт.")
    except Exception as e:
        logger.error(f"Источник HF Trending недоступен: {e}")


def _refresh_leaderboard():
    try:
        data = arena_scraper.collect_all_categories(arena_scraper.CATEGORY_URLS)
        arena_scraper.save_to_db(data)
        rows = sum(len(v) for v in data["categories"].values())
        logger.info(f"Лидерборд обновлён: {rows} строк по {len(data['categories'])} категориям.")
    except Exception as e:
        logger.error(f"Скрапинг/анализ лидерборда не выполнен: {e!r}")


def _refresh_github_trending():
    try:
        limit = getattr(config, "GITHUB_TRENDING_LIMIT", 30)
        logger.info(f"Запуск пайплайна GitHub Trending (Топ-{limit} weekly + monthly)...")
        results = run_github_trending_pipeline(limit=limit)
        logger.info(f"Витрина трендовых репозиториев GitHub обновлена: {len(results)} шт.")
    except Exception as e:
        logger.error(f"Пайплайн GitHub Trending завершился с ошибкой: {e!r}")


def stream_dataset_articles():
    for mode in config.HF_DATASET_MODES:
        try:
            yield from _tag_source_type(stream_hf_datasets_by_mode(mode), "датасет")
        except Exception as e:
            logger.error(f"Источник Hugging Face (датасеты, режим='{mode}') недоступен: {e}")

    try:
        for article in stream_kaggle_articles():
            if article.get("source_type") == "датасет":
                yield article
    except Exception as e:
        logger.error(f"Источник Kaggle недоступен: {e}")


def process_articles_stream(articles_stream):
    delete_old_vectors(days=14)

    memory_vectors: list[list[float]] = list(get_all_vectors())
    existing_urls: set[str] = get_existing_article_urls()
    logger.info(f"Загружено векторов из БД: {len(memory_vectors)}, известных URL: {len(existing_urls)}")

    processed, skipped, failed = 0, 0, 0

    for article in articles_stream:
        title = article.get("title", "")
        text = article.get("text", "")
        source_url = str(article.get("source_url") or "").strip()
        clean_url = source_url.rstrip("/")
        source_type = article.get("source_type", "статья")

        if clean_url and (clean_url in existing_urls or f"{clean_url}/" in existing_urls):
            logger.info(f"[EXISTS] Материал уже в базе ({source_type}): {title}")
            try:
                save_article({
                    "title": title,
                    "source_url": source_url,
                    "stars": int(article.get("stars") or article.get("upvotes") or 0),
                    "upvotes": int(article.get("upvotes") or article.get("stars") or 0),
                    "source_type": source_type,
                    "language": article.get("language", ""),
                    "topic_tag": article.get("topic_tag", ""),
                    "related_links": article.get("related_links", []),
                    "source_article_url": article.get("source_article_url", ""),
                    "period": article.get("period", ""),
                    "has_code": article.get("has_code", 0),
                    "has_spaces": article.get("has_spaces", 0),
                    "rank_global": int(article.get("rank_global", 0) or 0),
                    "rank_ru": int(article.get("rank_ru", 0) or 0),
                })
                for material in article.get("related_materials", []):
                    try:
                        upsert_related_material(material, source_article_url=source_url)
                    except Exception:
                        pass
            except Exception as upd_err:
                logger.debug(f"Не удалось обновить метрики {source_url}: {upd_err}")
            skipped += 1
            continue

        new_vector = text_to_vector(text)

        if source_type != "датасет" and (is_vector_duplicate_db(new_vector) or is_duplicate(new_vector, memory_vectors)):
            logger.info(f"[SKIP] Дубликат: {title}")
            skipped += 1
            continue

        try:
            if source_type == "датасет":
                existing_summary = article.get("summary")
                if existing_summary and "Назначение" in existing_summary and "Состав и масштаб" in existing_summary:
                    analysis = DatasetCard(
                        summary=existing_summary,
                        tags=article.get("tags") or ["датасет", "AI/ML"],
                    )
                else:
                    analysis = analyze_dataset(title, text)
            else:
                analysis = analyze_article(title, text)
        except AnalysisError as e:
            logger.error(f"[FAIL] {title}: {e}")
            failed += 1
            continue

        save_vector(new_vector)
        memory_vectors.append(new_vector)

        all_tags = list(dict.fromkeys(list(getattr(analysis, "tags", []) or []) + [t for t in article.get("tags", []) if t]))

        payload = {
            "title": title,
            "summary": analysis.summary,
            "source_url": source_url,
            "tags": all_tags,
            "directions": article.get("directions", []),
            "task_types": article.get("task_types", []),
            "stars": int(article.get("stars") or article.get("upvotes") or 0),
            "upvotes": int(article.get("upvotes") or article.get("stars") or 0),
            "source_type": article.get("source_type", "датасет"),
            "language": article.get("language", ""),
            "topic_tag": article.get("topic_tag", ""),
            "related_links": article.get("related_links", []),
            "source_article_url": article.get("source_article_url", ""),
            "period": article.get("period", ""),
            "has_code": article.get("has_code", 0),
            "has_spaces": article.get("has_spaces", 0),
            "rank_global": int(article.get("rank_global", 0) or 0),
            "rank_ru": int(article.get("rank_ru", 0) or 0),
        }

        save_article(payload)
        processed += 1
        existing_urls.add(clean_url)
        existing_urls.add(f"{clean_url}/")

        for material in article.get("related_materials", []):
            try:
                upsert_related_material(material, source_article_url=source_url)
            except Exception as upsert_err:
                logger.warning(f"Не удалось сохранить связанный материал {material}: {upsert_err}")

        memory_vectors.append(new_vector)

    flush_embeddings_cache()
    logger.info(f"Готово. Обработано: {processed}, дублей: {skipped}, ошибок: {failed}")
    return processed, skipped, failed


def main():
    setup_logging()
    init_db()
    _refresh_github_trending()
    _refresh_trending_models()
    _refresh_leaderboard()
    process_articles_stream(stream_all_new_articles())


def run_papers_only():
    setup_logging()
    from papers_fetcher import ingest_papers
    return ingest_papers()


def run_datasets_only():
    setup_logging()
    init_db()
    logger.info("=== Запуск сбора ТОЛЬКО датасетов (Hugging Face + Kaggle) ===")
    return process_articles_stream(stream_dataset_articles())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI/ML Radar Agent Pipeline")
    parser.add_argument("--only-papers", "--papers", action="store_true", help="Запустить сбор и сохранение только статей (HF + PwC)")
    parser.add_argument("--only-datasets", "--datasets", action="store_true", help="Запустить сбор и сохранение только датасетов (HF + Kaggle)")
    parser.add_argument("--only-github", action="store_true", help="Запустить только GitHub Trending")
    parser.add_argument("--only-models", action="store_true", help="Запустить только HF Trending модели")
    parser.add_argument("--only-arena", action="store_true", help="Запустить только лидерборд арены")
    args = parser.parse_args()

    if args.only_papers:
        run_papers_only()
    elif args.only_datasets:
        run_datasets_only()
    elif args.only_github:
        setup_logging()
        init_db()
        _refresh_github_trending()
    elif args.only_models:
        setup_logging()
        init_db()
        _refresh_trending_models()
    elif args.only_arena:
        setup_logging()
        init_db()
        _refresh_leaderboard()
    else:
        main()
