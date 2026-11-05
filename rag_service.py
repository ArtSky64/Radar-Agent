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
_REBUILD_INTERVAL_SEC = 300  # автоматическое обновление индекса раз в 5 минут


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


def _load_all_cards_from_db() -> list[dict[str, Any]]:
    """Извлекает все сущности (датасеты, модели, репозитории, статьи) из SQLite."""
    cards: list[dict[str, Any]] = []

    with database.get_connection() as conn:
        cursor = conn.cursor()

        # 1. Таблица articles (датасеты, статьи, репозитории)
        try:
            rows = cursor.execute("""
                SELECT rowid, title, summary, source_url, tags, source_type,
                       directions, task_types, stars, added_at
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
                    "url": url,
                    "tags": tags,
                    "metrics": {
                        "stars": r["stars"] or 0,
                    },
                    "added_at": r["added_at"] or "",
                })
        except Exception as e:
            logger.warning(f"Не удалось загрузить articles: {e}")

        # 2. Таблица hf_trending (модели Hugging Face)
        try:
            rows = cursor.execute("""
                SELECT rowid, model_name, summary, card_description, source_url,
                       tags, pipeline_tag, downloads, likes, rank_global, rank_ru
                FROM hf_trending
            """).fetchall()
            for r in rows:
                tags = _clean_tags(r["tags"])
                title = (r["model_name"] or "Без названия").strip()
                summary = (r["summary"] or r["card_description"] or "").strip()
                url = (r["source_url"] or f"https://huggingface.co/{title}").strip()
                p_tag = (r["pipeline_tag"] or "").strip()
                if p_tag and p_tag not in tags:
                    tags.append(p_tag)

                cards.append({
                    "id": f"hf_{r['rowid']}",
                    "title": title,
                    "category": "модель",
                    "summary": summary,
                    "url": url,
                    "tags": tags,
                    "metrics": {
                        "downloads": r["downloads"] or 0,
                        "likes": r["likes"] or 0,
                        "pipeline_tag": p_tag,
                    },
                    "added_at": "",
                })
        except Exception as e:
            logger.warning(f"Не удалось загрузить hf_trending: {e}")

        # 3. Таблица github_trending (репозитории)
        try:
            rows = cursor.execute("""
                SELECT rowid, repo_name, source_url, summary, tags, stars
                FROM github_trending
            """).fetchall()
            for r in rows:
                tags = _clean_tags(r["tags"])
                title = (r["repo_name"] or "Без названия").strip()
                summary = (r["summary"] or "").strip()
                url = (r["source_url"] or "").strip()

                cards.append({
                    "id": f"gh_{r['rowid']}",
                    "title": title,
                    "category": "репозиторий",
                    "summary": summary,
                    "url": url,
                    "tags": tags,
                    "metrics": {
                        "stars": r["stars"] or 0,
                    },
                    "added_at": "",
                })
        except Exception as e:
            logger.warning(f"Не удалось загрузить github_trending: {e}")

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
    Строит / обновляет векторный индекс карточек в памяти.
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

        vectors = []
        valid_cards = []

        for c in cards:
            text = _make_search_text(c)
            try:
                vec = dedup.text_to_vector(text)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                vectors.append(vec)
                valid_cards.append(c)
            except Exception as e:
                logger.error(f"Ошибка векторизации карточки '{c.get('title')}': {e}")

        if vectors:
            _INDEX_VECTORS = np.vstack(vectors).astype(np.float32)
            _INDEX_CARDS = valid_cards
        else:
            _INDEX_VECTORS = np.empty((0, config.VECTOR_DIM), dtype=np.float32)
            _INDEX_CARDS = []

        _LAST_BUILD_TS = now
        logger.info(f"Векторный индекс построен: {len(_INDEX_CARDS)} карточек")
        return len(_INDEX_CARDS)


def search_cards(
    query: str,
    category: str = "all",
    max_sources: int | None = None,
    top_k: int = 5,
    min_score: float = 0.20,
) -> list[dict[str, Any]]:
    """
    Выполняет косинусный поиск карточек по текстовому запросу.

    :param query: Поисковый запрос (например: 'медицинские датасеты снимков МРТ')
    :param category: Фильтр по категории ('all', 'датасет', 'модель', 'репозиторий', 'статья')
    :param max_sources: Количество найденных источников на выходе (по умолчанию 5)
    :param top_k: Алиас для обратной совместимости
    :param min_score: Минимальный порог косинусного сходства
    :return: Список словарей [{'card': card_data, 'score': float}, ...]
    """
    limit = max_sources if max_sources is not None else top_k
    build_index()

    if not _INDEX_CARDS or _INDEX_VECTORS is None or len(_INDEX_VECTORS) == 0:
        return []

    # Получаем вектор запроса и нормализуем
    query_vec = dedup.text_to_vector(query.strip())
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0:
        return []
    query_vec = (query_vec / q_norm).astype(np.float32)

    # Скалярное произведение нормализованных векторов = косинусное сходство
    scores = np.dot(_INDEX_VECTORS, query_vec)

    # Фильтрация по категории и порогу сходства
    category_filter = category.strip().lower() if category else "all"
    results = []

    for idx, score in enumerate(scores):
        card = _INDEX_CARDS[idx]
        card_cat = card.get("category", "").lower()

        if category_filter != "all":
            # Разрешаем частичное совпадение (например "модели" -> "модель", "датасеты" -> "датасет")
            if not (category_filter in card_cat or card_cat in category_filter):
                continue

        if score >= min_score:
            results.append({
                "score": round(float(score), 4),
                "card": card,
            })

    # Сортировка по убыванию релевантности
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def get_catalog_stats() -> dict[str, int]:
    """Возвращает статистику по карточкам в индексе."""
    build_index()
    stats: dict[str, int] = {
        "всего": len(_INDEX_CARDS),
        "датасет": 0,
        "модель": 0,
        "репозиторий": 0,
        "статья": 0,
    }
    for c in _INDEX_CARDS:
        cat = c.get("category", "")
        if cat in stats:
            stats[cat] += 1
        else:
            stats[cat] = 1
    return stats
