import logging

import numpy as np

import config
from dedup import text_to_vector, is_duplicate
from agent_manager import analyze_article, AnalysisError
from database import init_db, get_all_vectors, save_vector, save_article, delete_old_vectors, save_trending_models, upsert_related_material
from FetcherHF import stream_hf_articles
from FetcherHFDatasets import stream_hf_datasets_by_mode
from mcp_fetcher_kaggle import stream_kaggle_articles
from mcp_fetcher_papers import stream_papers_articles
from github_fetcher import (
    stream_github_articles_v2,
    stream_github_trending_page_articles,
    run_github_trending_pipeline,
    TRENDING_PERIODS,
)

from mcp_fetcher_hf_trending import fetch_trending_models
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

    # Ошибки анализа отдельно пишем в errors.log — удобно смотреть на защите,
    # какие статьи не удалось обработать и почему.
    error_handler = logging.FileHandler(config.ERROR_LOG_FILE, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s"))
    logging.getLogger().addHandler(error_handler)


logger = logging.getLogger("main")


#Источники статей

def _fake_articles():
    """Демо-статьи — оставлены для быстрой проверки пайплайна без сети/MCP."""
    fake_articles = [
        {
            "title": "Новый подход к RAG-системам",
            "text": "В статье описан метод улучшения retrieval-augmented generation за счет гибридного поиска...",
            "source_url": "https://arxiv.org/abs/fake1",
        },
        {
            "title": "Fine-tuning LLM на малых датасетах",
            "text": "Авторы предлагают технику LoRA-адаптации для дообучения языковых моделей...",
            "source_url": "https://arxiv.org/abs/fake2",
        },
    ]
    for article in fake_articles:
        yield article


def _tag_source_type(articles, source_type: str):
    for article in articles:
        # Не затираем тип, если фетчер уже проставил свой (см. mcp_fetcher_kaggle.py,
        # где вперемешку датасеты и модели — общий ярлык для всего источника не подходит).
        article.setdefault("source_type", source_type)
        yield article


def stream_all_new_articles():
    try:
        yield from _tag_source_type(stream_hf_articles("LLM"), "модель")
    except Exception as e:
        logger.error(f"Источник Hugging Face (модели) недоступен: {e}")

    # Раньше тут был единственный статичный запрос "machine learning" — при
    # повторных прогонах (раз в 3 дня, плюс ручные запуски) HF отдаёт почти
    # одну и ту же топ-выдачу по этому запросу, и все кандидаты уходят в дедуп
    # как уже виденные (см. лог: "Обработано: 0, дублей: 22"). Гоняем несколько
    for mode in config.HF_DATASET_MODES:
        try:
            yield from _tag_source_type(stream_hf_datasets_by_mode(mode), "датасет")
        except Exception as e:
            logger.error(f"Источник Hugging Face (датасеты, режим='{mode}') недоступен: {e}")

    try:
        yield from _tag_source_type(stream_papers_articles(), "статья")
    except Exception as e:
        logger.error(f"Источник Papers (HF + PwC) недоступен: {e}")

    #одно множество на все режимы гита, чтобы репо выбранное ллм в одном режиме не уходило в ллм повторно в другому
    seen_github_ids: set[str] = set()

    try:
        yield from _tag_source_type(stream_github_articles_v2(seen_ids=seen_github_ids), "репозиторий")
    except Exception as e:
        logger.error(f"Источник GitHub(SearchAPI) недоступен: {e}")

    for period in TRENDING_PERIODS:
        try:
            yield from _tag_source_type(
                stream_github_trending_page_articles(period, seen_ids=seen_github_ids), "репозиторий",)
        except Exception as e:
            logger.error(f"Источник GitHub Trending ({period}) недоступен: {e}")


    for kaggle_q in ("machine learning", "LLM"):
        try:
            yield from _tag_source_type(stream_kaggle_articles(kaggle_q), "датасет")
        except Exception as e:
            logger.error(f"Источник Kaggle (запрос='{kaggle_q}') недоступен: {e}")

# Тренды HF — отдельный пайплайн: без дедупа и LLM-анализа, просто снимок
# витрины (name/downloads/likes/tags), который save_trending_models() каждый
# раз полностью перезаписывает. Раньше этот шаг дёргался только из app.py
# через /trending/refresh — теперь синхронизируем и при прогоне main.py.
def _refresh_trending_models():
    try:
        models = fetch_trending_models(limit=30)
        if not models:
            logger.info("Трендовые модели HF не получены (пусто или MCP-сервер недоступен).")
            return
        save_trending_models(models)
        logger.info(f"Витрина трендовых моделей HF обновлена: {len(models)} шт.")
    except Exception as e:
        logger.error(f"Источник HF Trending недоступен: {e}")


# Полный цикл лидерборда: скрапинг арены (Playwright, ~1-2 мин) + сохранение
# снимка + инкрементальный анализ — всё это уже собрано в arena_scraper.save_to_db().
# Раньше сюда попадал только сам скрапинг через отдельный /scrape в app.py;
# теперь весь пайплайн (статьи + тренды + лидерборд) обновляется одним прогоном
# main.py, без ручных дозапусков.
def _refresh_leaderboard():
    try:
        data = arena_scraper.collect_all_categories(arena_scraper.CATEGORY_URLS)
        arena_scraper.save_to_db(data)  # save_leaderboard_data() + run_leaderboard_analysis() внутри
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


# Главный цикл 

def stream_dataset_articles():
    """Генератор только датасетов: Hugging Face (4 режима) + Kaggle (machine learning и LLM)."""
    for mode in config.HF_DATASET_MODES:
        try:
            yield from _tag_source_type(stream_hf_datasets_by_mode(mode), "датасет")
        except Exception as e:
            logger.error(f"Источник Hugging Face (датасеты, режим='{mode}') недоступен: {e}")

    for kaggle_q in ("machine learning", "LLM"):
        try:
            for article in stream_kaggle_articles(kaggle_q):
                if article.get("source_type") == "датасет":
                    yield article
        except Exception as e:
            logger.error(f"Источник Kaggle (запрос='{kaggle_q}') недоступен: {e}")


def process_articles_stream(articles_stream):
    """Общий цикл дедупликации, анализа LLM и сохранения в БД для любого потока материалов."""
    # Чистим только устаревший кэш векторов-дублей (не сами статьи —
    # они должны копиться со всех прогонов, это база знаний, а не разовый снимок)
    delete_old_vectors(days=14)

    # 1. ОДИН РАЗ выгружаем все векторы из БД в оперативную память.
    memory_vectors: list[np.ndarray] = [np.array(v, dtype=np.float32) for v in get_all_vectors()]
    logger.info(f"Загружено векторов из БД: {len(memory_vectors)}")

    processed, skipped, failed = 0, 0, 0

    # 2. Потоково получаем материалы
    for article in articles_stream:
        title = article["title"]
        text = article["text"]
        source_url = article["source_url"]

        # 3. Текст -> вектор (реальные эмбеддинги через fastembed, Sprint 3)
        new_vector = text_to_vector(text)

        # 4. Проверка на дубликат (со всей БД + со статьями, добавленными в этом же цикле)
        if is_duplicate(new_vector, memory_vectors):
            logger.info(f"[SKIP] Дубликат: {title}")
            skipped += 1
            continue

        # 5. Уникальный материал — отправляем в агента (PydanticAI)
        try:
            analysis = analyze_article(title, text)
        except AnalysisError as e:
            logger.error(f"[FAIL] {title}: {e}")
            failed += 1
            continue  # материал не сохраняется, но цикл не падает

        # 6. Сохраняем вектор ОТДЕЛЬНО от статьи — по контракту database.py
        save_vector(new_vector.tolist())

        payload = {
            "title": title,
            "summary": analysis.summary,
            "source_url": source_url,
            "tags": analysis.tags,  # список строк — database.py сам делает json.dumps
            "directions": article.get("directions", []),
            "task_types": article.get("task_types", []),
            "stars": int(article.get("stars") or article.get("upvotes") or 0),
            "upvotes": int(article.get("upvotes") or article.get("stars") or 0),
            "source_type": article.get("source_type", "датасет"),
            # Заполнено у HF-датасетов, тематических срезов и периодов
            "language": article.get("language", ""),
            "topic_tag": article.get("topic_tag", ""),
            "related_links": article.get("related_links", []),
            "source_article_url": article.get("source_article_url", ""),
            "period": article.get("period", ""),
            "has_code": article.get("has_code", 0),
        }

        save_article(payload)
        processed += 1

        for material in article.get("related_materials", []):
            try:
                upsert_related_material(material, source_article_url=source_url)
            except Exception as upsert_err:
                logger.warning(f"Не удалось сохранить связанный материал {material}: {upsert_err}")

        # 8. КРИТИЧЕСКИЙ ШАГ: пополняем memory_vectors,
        #    чтобы следующие материалы в этом же цикле сравнивались
        #    и с базой, и с только что спарсенными
        memory_vectors.append(new_vector)

    logger.info(f"Готово. Обработано: {processed}, дублей: {skipped}, ошибок: {failed}")
    return processed, skipped, failed


def main():
    setup_logging()

    # Создаёт таблицы, если их ещё нет (безопасно вызывать при каждом запуске)
    init_db()

    # Тренды GitHub — сбор 30 проектов (weekly + monthly), обогащение README и Qwen
    _refresh_github_trending()

    # Тренды HF не участвуют в дедупе/цикле статей — обновляем отдельным шагом
    _refresh_trending_models()

    # Лидерборд арены — тоже независимый пайплайн, тяжёлый (Playwright),
    # поэтому запускаем целиком отдельным шагом, а не смешиваем со статьями
    _refresh_leaderboard()

    # Обработка основного потока всех материалов
    process_articles_stream(stream_all_new_articles())


def run_papers_only():
    """Изолированный запуск сбора и обработки только раздела статей (HF + PwC + Healthcare)."""
    setup_logging()
    from mcp_fetcher_papers import ingest_papers
    return ingest_papers()


def run_datasets_only():
    """Изолированный запуск сбора и обработки только датасетов (Hugging Face + Kaggle)."""
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