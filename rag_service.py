"""
Модуль векторного поиска и индексации карточек базы знаний (RAG Service).
Индексирует:
- Датасеты и статьи из таблицы articles
- Трендовые модели из таблицы hf_trending
- Трендовые репозитории из таблицы github_trending

Векторизация выполняется через локальную модель dedup.text_to_vector (fastembed / MiniLM-L12).
Поиск по косинусному сходству нормализованных векторов.
"""

import json
import logging
import re
import sqlite3
import threading
import time
from typing import Any

import numpy as np

import config
import database
import dedup

logger = logging.getLogger("rag_service")

# Кэш индекса в памяти
_LOCK = threading.Lock()
_INDEX_CARDS: list[dict[str, Any]] = []
_INDEX_VECTORS: np.ndarray | None = None
_LAST_BUILD_TS = 0.0
_REBUILD_INTERVAL_SEC = 600  # обновление индекса раз в 10 минут


def _clean_tags(raw_tags: Any) -> list[str]:
    """Нормализует теги в список строк."""
    if not raw_tags:
        return []
    if isinstance(raw_tags, list):
        return [str(t).strip() for t in raw_tags if str(t).strip()]
    if isinstance(raw_tags, str):
        try:
            parsed = json.loads(raw_tags)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed if str(t).strip()]
        except Exception:
            pass
        return [t.strip() for t in raw_tags.split(",") if t.strip()]
    return []


def parse_hf_metadata(raw_card_desc: str) -> tuple[dict[str, Any], str]:
    """
    Извлекает структурированные метаданные из card_description (если это JSON из cardData Hugging Face).
    Возвращает (словарь_метаданных, очищенный_текст).
    Никогда не выбрасывает исключений и не допускает отображения сырого JSON пользователю.
    """
    if not raw_card_desc:
        return {}, ""
    text = raw_card_desc.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed, ""
        except Exception:
            pass

    # Поиск JSON блока внутри строки
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict):
                clean_text = text.replace(m.group(0), "").strip()
                return parsed, clean_text
        except Exception:
            pass

    return {}, text


def build_human_readable_full_description(
    title: str,
    summary: str,
    meta: dict[str, Any],
    clean_text: str = "",
    details: dict[str, Any] | None = None,
) -> str:
    """
    Формирует развёрнутое человекочитаемое описание карточки вместо сырого JSON-дампа.
    """
    blocks = []
    clean_summary = summary.strip() if summary else ""
    if clean_summary:
        blocks.append(clean_summary)

    meta_lines = []
    base_model = meta.get("base_model") or (details.get("base_model") if details else None)
    if base_model:
        meta_lines.append(f"- **Базовая модель:** `{base_model}`")

    lib = meta.get("library_name") or (details.get("library_name") if details else None)
    if lib:
        meta_lines.append(f"- **Библиотека / Фреймворк:** `{lib}`")

    datasets = meta.get("datasets") or (details.get("datasets") if details else None)
    if datasets:
        if isinstance(datasets, list):
            ds_str = ", ".join([f"`{d}`" for d in datasets])
        else:
            ds_str = str(datasets)
        meta_lines.append(f"- **Обучающие датасеты:** {ds_str}")

    langs = meta.get("language") or (details.get("language") if details else None)
    if langs:
        if isinstance(langs, list):
            if len(langs) > 6:
                sample_langs = ", ".join([str(l) for l in langs[:6]])
                langs_str = f"{len(langs)} языков ({sample_langs} и др.)"
            else:
                langs_str = ", ".join([str(l) for l in langs])
        else:
            langs_str = str(langs)
        meta_lines.append(f"- **Языковая поддержка:** {langs_str}")

    lic = meta.get("license_name") or meta.get("license") or (details.get("license") if details else None)
    lic_link = meta.get("license_link") or (details.get("license_link") if details else None)
    if lic and lic != "other":
        if lic_link:
            meta_lines.append(f"- **Лицензия:** [{lic}]({lic_link})")
        else:
            meta_lines.append(f"- **Лицензия:** `{lic}`")
    elif lic_link:
        meta_lines.append(f"- **Лицензия:** [Спецификация лицензии]({lic_link})")

    p_tag = meta.get("pipeline_tag") or (details.get("pipeline_tag") if details else None)
    if p_tag:
        meta_lines.append(f"- **Пайплайн задачи:** `{p_tag}`")

    if meta_lines:
        blocks.append("#### Спецификация и окружение:\n" + "\n".join(meta_lines))

    clean_extra = clean_text.strip() if clean_text else ""
    if clean_extra and clean_extra != clean_summary and len(clean_extra) > 30:
        if clean_extra.startswith("---") and "---" in clean_extra[3:]:
            parts = clean_extra[3:].split("---", 1)
            if len(parts) > 1:
                clean_extra = parts[1].strip()
        if clean_extra and not clean_extra.startswith("{"):
            blocks.append(clean_extra)

    return "\n\n".join(blocks).strip()


def _load_all_cards_from_db() -> list[dict[str, Any]]:
    """Извлекает все сущности (датасеты, модели, репозитории, статьи, арена) из SQLite."""
    cards: list[dict[str, Any]] = []

    with database.get_connection() as conn:
        cursor = conn.cursor()

        # 1. Таблица articles (датасеты, статьи, репозитории)
        try:
            rows = cursor.execute("""
                SELECT rowid, title, summary, source_url, tags, source_type,
                       directions, task_types, stars, added_at, related_links,
                       language, topic_tag, period
                FROM articles
            """).fetchall()
            for r in rows:
                c_type = (r["source_type"] or "статья").strip().lower()
                tags = _clean_tags(r["tags"])
                title = (r["title"] or "Без названия").strip()
                summary = (r["summary"] or "").strip()
                url = (r["source_url"] or "").strip()

                cards.append({
                    "id": f"art_{r['rowid']}",
                    "title": title,
                    "category": c_type,
                    "summary": summary,
                    "full_description": summary,
                    "url": url,
                    "tags": tags,
                    "metrics": {
                        "stars": r["stars"] or 0,
                    },
                    "details": {
                        "directions": r["directions"] or "[]",
                        "task_types": r["task_types"] or "[]",
                        "related_links": r["related_links"] or "[]",
                        "language": r["language"] or "",
                        "period": r["period"] or "",
                    },
                    "added_at": r["added_at"] or "",
                })
        except Exception as e:
            logger.warning(f"Не удалось загрузить articles: {e}")

        # 2. Таблица hf_trending (модели Hugging Face)
        try:
            rows = cursor.execute("""
                SELECT rowid, model_name, summary, card_description, source_url,
                       tags, pipeline_tag, downloads, likes, rank_global, rank_ru,
                       parameters, license, language, variant
                FROM hf_trending
            """).fetchall()
            for r in rows:
                tags = _clean_tags(r["tags"])
                title = (r["model_name"] or "Без названия").strip()
                card_desc = (r["card_description"] or "").strip()
                summary = (r["summary"] or "").strip()
                url = (r["source_url"] or f"https://huggingface.co/{title}").strip()
                p_tag = (r["pipeline_tag"] or "").strip()
                if p_tag and p_tag not in tags:
                    tags.append(p_tag)

                meta, clean_text = parse_hf_metadata(card_desc)

                details = {
                    "parameters": r["parameters"] or "",
                    "pipeline_tag": p_tag or meta.get("pipeline_tag", ""),
                    "license": meta.get("license_name") or r["license"] or meta.get("license", ""),
                    "license_link": meta.get("license_link", ""),
                    "language": r["language"] or meta.get("language", ""),
                    "variant": r["variant"] or "",
                    "library_name": meta.get("library_name", ""),
                    "base_model": meta.get("base_model", ""),
                    "datasets": meta.get("datasets", []),
                }

                if meta:
                    full_desc = build_human_readable_full_description(
                        title=title,
                        summary=summary or clean_text,
                        meta=meta,
                        clean_text=clean_text,
                        details=details,
                    )
                else:
                    full_desc = card_desc if card_desc and not card_desc.startswith("{") else summary

                if not summary and full_desc:
                    summary = full_desc[:350]

                cards.append({
                    "id": f"hf_{r['rowid']}",
                    "title": title,
                    "category": "модель",
                    "summary": summary,
                    "full_description": full_desc,
                    "url": url,
                    "tags": tags,
                    "metrics": {
                        "downloads": r["downloads"] or 0,
                        "likes": r["likes"] or 0,
                        "rank_global": r["rank_global"],
                        "rank_ru": r["rank_ru"],
                    },
                    "details": details,
                    "added_at": "",
                })
        except Exception as e:
            logger.warning(f"Не удалось загрузить hf_trending: {e}")

        # 3. Таблица github_trending (репозитории)
        try:
            rows = cursor.execute("""
                SELECT rowid, repo_name, source_url, summary,
                       tags, directions, task_types, stars, period, stars_this_period
                FROM github_trending
            """).fetchall()
            for r in rows:
                tags = _clean_tags(r["tags"])
                title = (r["repo_name"] or "Без названия").strip()
                summary = (r["summary"] or "").strip()
                url = (r["source_url"] or f"https://github.com/{title}").strip()

                cards.append({
                    "id": f"gh_{r['rowid']}",
                    "title": title,
                    "category": "репозиторий",
                    "summary": summary,
                    "full_description": summary,
                    "url": url,
                    "tags": tags,
                    "metrics": {
                        "stars": r["stars"] or 0,
                        "stars_this_period": r["stars_this_period"] or 0,
                        "period": r["period"] or "",
                    },
                    "details": {
                        "directions": r["directions"] or "[]",
                        "task_types": r["task_types"] or "[]",
                        "period": r["period"] or "",
                    },
                    "added_at": "",
                })
        except Exception as e:
            logger.warning(f"Не удалось загрузить github_trending: {e}")

        # 4. Таблица leaderboard (LMSYS Arena)
        try:
            rows = cursor.execute("""
                SELECT rowid, model_name, category, rating, organization, license, vote_count, summary
                FROM leaderboard
            """).fetchall()
            for r in rows:
                title = (r["model_name"] or "Без названия").strip()
                summary = (r["summary"] or "").strip()
                cat_tag = (r["category"] or "").strip()
                tags = [cat_tag] if cat_tag else []

                cards.append({
                    "id": f"lb_{r['rowid']}",
                    "title": title,
                    "category": "модель",
                    "summary": summary,
                    "full_description": summary,
                    "url": f"https://huggingface.co/{title}",
                    "tags": tags,
                    "metrics": {
                        "rating": r["rating"] or 0,
                        "vote_count": r["vote_count"] or 0,
                    },
                    "details": {
                        "organization": r["organization"] or "",
                        "license": r["license"] or "",
                        "arena_category": cat_tag,
                    },
                    "added_at": "",
                })
        except Exception as e:
            logger.warning(f"Не удалось загрузить leaderboard: {e}")

    return cards


def _make_search_text(card: dict[str, Any]) -> str:
    """Формирует текстовое представление карточки для построения эмбеддинга."""
    category = card.get("category", "")
    title = card.get("title", "")
    tags = ", ".join(card.get("tags", []))
    summary = card.get("summary", "")

    parts = [f"[{category.upper()}] {title}"]
    if tags:
        parts.append(f"Теги: {tags}")
    if summary:
        parts.append(f"Описание: {summary[:600]}")

    return "\n".join(parts)


def build_index(force: bool = False) -> int:
    """
    Строит / обновляет векторный индекс карточек в памяти пакетом (векторизация батчами).
    Возвращает количество проиндексированных карточек.
    """
    global _INDEX_CARDS, _INDEX_VECTORS, _LAST_BUILD_TS

    with _LOCK:
        now = time.monotonic()
        if not force and _INDEX_VECTORS is not None and (now - _LAST_BUILD_TS < _REBUILD_INTERVAL_SEC):
            return len(_INDEX_CARDS)

        cards = _load_all_cards_from_db()
        if not cards:
            _INDEX_CARDS = []
            _INDEX_VECTORS = np.empty((0, config.VECTOR_DIM), dtype=np.float32)
            _LAST_BUILD_TS = now
            return 0

        texts = [_make_search_text(c) for c in cards]
        raw_vectors = dedup.batch_texts_to_vectors(texts)

        valid_cards = []
        vectors = []
        for c, vec in zip(cards, raw_vectors):
            norm = np.linalg.norm(vec)
            if norm > 0:
                vectors.append((vec / norm).astype(np.float32))
                valid_cards.append(c)

        if vectors:
            _INDEX_VECTORS = np.vstack(vectors).astype(np.float32)
            _INDEX_CARDS = valid_cards
        else:
            _INDEX_VECTORS = np.empty((0, config.VECTOR_DIM), dtype=np.float32)
            _INDEX_CARDS = []

        _LAST_BUILD_TS = now
        logger.info(f"Векторный индекс построен: {len(_INDEX_CARDS)} карточек")
        return len(_INDEX_CARDS)


def get_card_by_title_or_id(
    target: str,
    category: str = "all",
) -> dict[str, Any] | None:
    """
    Точный или высокоточный поиск конкретной карточки по названию, URL или ID.
    Если найдена в памяти или БД, возвращает карточку с полным описанием (README/card_description)
    и детальными метаданными.
    """
    if not target or not target.strip():
        return None

    cleaned_target = target.strip().strip('"\'«»').lower()
    if not cleaned_target:
        return None

    if _INDEX_VECTORS is None or len(_INDEX_CARDS) == 0:
        build_index()

    # 1. Поиск в загруженных карточках в памяти
    best_card = None
    category_filter = category.strip().lower() if category else "all"

    for c in _INDEX_CARDS:
        c_title = (c.get("title") or "").strip().lower()
        c_id = (c.get("id") or "").strip().lower()
        c_url = (c.get("url") or "").strip().lower()
        c_cat = (c.get("category") or "").strip().lower()

        if category_filter != "all" and c_cat != category_filter:
            continue

        # Прямое совпадение по ID
        if c_id == cleaned_target:
            return c

        # Точное совпадение по названию или URL
        if c_title == cleaned_target or (c_url and c_url == cleaned_target):
            return c

        # Чистое совпадение без префикса категорий
        clean_title = re.sub(r"^\[.*?\]\s*", "", c_title).strip()
        if clean_title == cleaned_target:
            return c

        # Подстрока названия (например meta-llama/Llama-3-8b в длинном запросе)
        if len(clean_title) >= 4 and (clean_title in cleaned_target or cleaned_target in clean_title):
            if best_card is None or len(clean_title) > len(best_card.get("title", "")):
                best_card = c

    if best_card is not None:
        return best_card

    # 2. Прямой поиск в базе SQLite (если карточка не в памяти)
    try:
        with database.get_connection() as conn:
            cursor = conn.cursor()

            # Поиск в hf_trending
            row = cursor.execute("""
                SELECT rowid, model_name, summary, card_description, source_url,
                       tags, pipeline_tag, downloads, likes, rank_global, rank_ru,
                       parameters, license, language, variant
                FROM hf_trending
                WHERE LOWER(model_name) = ? OR LOWER(model_name) LIKE ?
                LIMIT 1
            """, (cleaned_target, f"%{cleaned_target}%")).fetchone()

            if row:
                title = row["model_name"]
                card_desc = (row["card_description"] or "").strip()
                summary = (row["summary"] or "").strip()
                p_tag = (row["pipeline_tag"] or "").strip()
                meta, clean_text = parse_hf_metadata(card_desc)

                details = {
                    "parameters": row["parameters"] or "",
                    "pipeline_tag": p_tag or meta.get("pipeline_tag", ""),
                    "license": meta.get("license_name") or row["license"] or meta.get("license", ""),
                    "license_link": meta.get("license_link", ""),
                    "language": row["language"] or meta.get("language", ""),
                    "variant": row["variant"] or "",
                    "library_name": meta.get("library_name", ""),
                    "base_model": meta.get("base_model", ""),
                    "datasets": meta.get("datasets", []),
                }

                if meta:
                    full_desc = build_human_readable_full_description(
                        title=title,
                        summary=summary or clean_text,
                        meta=meta,
                        clean_text=clean_text,
                        details=details,
                    )
                else:
                    full_desc = card_desc if card_desc and not card_desc.startswith("{") else summary

                return {
                    "id": f"hf_{row['rowid']}",
                    "title": title,
                    "category": "модель",
                    "summary": summary or full_desc[:350],
                    "full_description": full_desc,
                    "url": row["source_url"] or f"https://huggingface.co/{title}",
                    "tags": _clean_tags(row["tags"]),
                    "metrics": {
                        "downloads": row["downloads"] or 0,
                        "likes": row["likes"] or 0,
                        "rank_global": row["rank_global"],
                        "rank_ru": row["rank_ru"],
                    },
                    "details": details,
                }

            # Поиск в articles
            row = cursor.execute("""
                SELECT rowid, title, summary, source_url, tags, source_type,
                       directions, task_types, stars, added_at, related_links,
                       language, topic_tag, period
                FROM articles
                WHERE LOWER(title) = ? OR LOWER(title) LIKE ?
                LIMIT 1
            """, (cleaned_target, f"%{cleaned_target}%")).fetchone()

            if row:
                summary = (row["summary"] or "").strip()
                return {
                    "id": f"art_{row['rowid']}",
                    "title": row["title"],
                    "category": (row["source_type"] or "статья").strip().lower(),
                    "summary": summary,
                    "full_description": summary,
                    "url": row["source_url"] or "",
                    "tags": _clean_tags(row["tags"]),
                    "metrics": {"stars": row["stars"] or 0},
                    "details": {
                        "directions": row["directions"] or "[]",
                        "task_types": row["task_types"] or "[]",
                        "related_links": row["related_links"] or "[]",
                        "language": row["language"] or "",
                    },
                }

            # Поиск в github_trending
            row = cursor.execute("""
                SELECT rowid, repo_name, source_url, summary,
                       tags, directions, task_types, stars, period, stars_this_period
                FROM github_trending
                WHERE LOWER(repo_name) = ? OR LOWER(repo_name) LIKE ?
                LIMIT 1
            """, (cleaned_target, f"%{cleaned_target}%")).fetchone()

            if row:
                summary = (row["summary"] or "").strip()
                return {
                    "id": f"gh_{row['rowid']}",
                    "title": row["repo_name"],
                    "category": "репозиторий",
                    "summary": summary,
                    "full_description": summary,
                    "url": row["source_url"] or f"https://github.com/{row['repo_name']}",
                    "tags": _clean_tags(row["tags"]),
                    "metrics": {
                        "stars": row["stars"] or 0,
                        "stars_this_period": row["stars_this_period"] or 0,
                        "period": row["period"] or "",
                    },
                    "details": {
                        "directions": row["directions"] or "[]",
                        "task_types": row["task_types"] or "[]",
                    },
                }

            # Поиск в leaderboard
            row = cursor.execute("""
                SELECT rowid, model_name, category, rating, organization, license, vote_count, summary
                FROM leaderboard
                WHERE LOWER(model_name) = ? OR LOWER(model_name) LIKE ?
                LIMIT 1
            """, (cleaned_target, f"%{cleaned_target}%")).fetchone()

            if row:
                summary = (row["summary"] or "").strip()
                return {
                    "id": f"lb_{row['rowid']}",
                    "title": row["model_name"],
                    "category": "модель",
                    "summary": summary,
                    "full_description": summary,
                    "url": f"https://huggingface.co/{row['model_name']}",
                    "tags": [row["category"]] if row["category"] else [],
                    "metrics": {
                        "rating": row["rating"] or 0,
                        "vote_count": row["vote_count"] or 0,
                    },
                    "details": {
                        "organization": row["organization"] or "",
                        "license": row["license"] or "",
                        "arena_category": row["category"] or "",
                    },
                }
    except Exception as e:
        logger.warning(f"Ошибка точного поиска карточки в БД: {e}")

    return None


def search_cards(
    query: str,
    category: str = "all",
    max_sources: int | None = None,
    top_k: int = 5,
    min_score: float = 0.26,
) -> list[dict[str, Any]]:
    """
    Выполняет косинусный поиск карточек по текстовому запросу.
    Сверхбыстрый поиск по готовой матрице векторов в памяти (доли миллисекунды).

    :param query: Поисковый запрос (например: 'медицинские датасеты снимков МРТ')
    :param category: Фильтр по категории ('all', 'датасет', 'модель', 'репозиторий', 'статья')
    :param max_sources: Количество найденных источников на выходе (по умолчанию 5)
    :param top_k: Алиас для обратной совместимости
    :param min_score: Минимальный порог косинусного сходства (по умолчанию 0.26 для отсечения шума)
    :return: Список словарей [{'card': card_data, 'score': float}, ...]
    """
    limit = max_sources if max_sources is not None else top_k

    # Если индекс еще не построен — строим
    if _INDEX_VECTORS is None or len(_INDEX_VECTORS) == 0:
        build_index()
    else:
        # Фоновое фоновое обновление при устаревании (не блокируя текущий поиск)
        now = time.monotonic()
        if now - _LAST_BUILD_TS > _REBUILD_INTERVAL_SEC:
            threading.Thread(target=build_index, daemon=True).start()

    if not _INDEX_CARDS or _INDEX_VECTORS is None or len(_INDEX_VECTORS) == 0:
        return []

    # Получаем вектор запроса и нормализуем
    query_vec = dedup.text_to_vector(query.strip())
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0:
        return []
    query_vec = (query_vec / q_norm).astype(np.float32)

    # Скалярное произведение нормализованных векторов = косинусное сходство (мгновенно на BLAS/numpy)
    scores = np.dot(_INDEX_VECTORS, query_vec)

    # Фильтрация по категории и порогу сходства
    category_filter = category.strip().lower() if category else "all"
    results = []

    for idx, score in enumerate(scores):
        if score < min_score:
            continue
        card = _INDEX_CARDS[idx]
        c_cat = card.get("category", "").lower()

        if category_filter != "all" and c_cat != category_filter:
            continue

        results.append({
            "card": card,
            "score": float(score),
        })

    # Сортировка по убыванию релевантности
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def get_catalog_stats() -> dict[str, int]:
    """Возвращает агрегированную статистику проиндексированных карточек."""
    build_index()
    stats = {
        "всего": len(_INDEX_CARDS),
        "модели": 0,
        "датасеты": 0,
        "репозитории": 0,
        "статьи": 0,
    }
    for c in _INDEX_CARDS:
        cat = c.get("category", "").lower()
        if cat == "модель":
            stats["модели"] += 1
        elif cat == "датасет":
            stats["датасеты"] += 1
        elif cat == "репозиторий":
            stats["репозитории"] += 1
        else:
            stats["статьи"] += 1
    return stats
