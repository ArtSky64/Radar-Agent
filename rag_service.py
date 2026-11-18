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

import config
import database
import dedup

logger = logging.getLogger("rag_service")

# Кэш индекса в памяти
_LOCK = threading.Lock()
_INDEX_CARDS: list[dict[str, Any]] = []
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

                # Обогащаем теги направлениями (directions), типами задач (task_types) и топиком
                for d in _clean_tags(r["directions"]):
                    d_clean = d.strip().lower()
                    if d_clean:
                        tags.append(d_clean)
                        if d_clean in config.GITHUB_DIRECTIONS:
                            tags.append(config.GITHUB_DIRECTIONS[d_clean])

                for tt in _clean_tags(r["task_types"]):
                    tt_clean = tt.strip().lower()
                    if tt_clean:
                        tags.append(tt_clean)
                        if tt_clean in config.GITHUB_TASK_TYPES:
                            tags.append(config.GITHUB_TASK_TYPES[tt_clean])

                topic = (r["topic_tag"] or "").strip()
                if topic and topic not in tags:
                    tags.append(topic)

                tags = list(dict.fromkeys(tags))

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
                       parameters, license, language, variant, directions, task_types
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

                for d in _clean_tags(r["directions"]):
                    d_clean = d.strip().lower()
                    if d_clean:
                        tags.append(d_clean)
                        if d_clean in config.GITHUB_DIRECTIONS:
                            tags.append(config.GITHUB_DIRECTIONS[d_clean])

                for tt in _clean_tags(r["task_types"]):
                    tt_clean = tt.strip().lower()
                    if tt_clean:
                        tags.append(tt_clean)
                        if tt_clean in config.GITHUB_TASK_TYPES:
                            tags.append(config.GITHUB_TASK_TYPES[tt_clean])

                tags = list(dict.fromkeys(tags))

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

                for d in _clean_tags(r["directions"]):
                    d_clean = d.strip().lower()
                    if d_clean:
                        tags.append(d_clean)
                        if d_clean in config.GITHUB_DIRECTIONS:
                            tags.append(config.GITHUB_DIRECTIONS[d_clean])

                for tt in _clean_tags(r["task_types"]):
                    tt_clean = tt.strip().lower()
                    if tt_clean:
                        tags.append(tt_clean)
                        if tt_clean in config.GITHUB_TASK_TYPES:
                            tags.append(config.GITHUB_TASK_TYPES[tt_clean])

                tags = list(dict.fromkeys(tags))

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

        # 4. Таблица leaderboard (LMSYS Arena) — строго ПОСЛЕДНИЙ снимок и БЕЗ дублирования моделей
        try:
            rows = cursor.execute("""
                SELECT rowid, model_name, category, rating, organization, license, vote_count, summary
                FROM leaderboard
                WHERE fetched_at = (SELECT MAX(fetched_at) FROM leaderboard)
            """).fetchall()

            seen_lb_models: dict[str, dict[str, Any]] = {}

            for r in rows:
                m_name = (r["model_name"] or "Без названия").strip()
                if not m_name:
                    continue
                cat_tag = (r["category"] or "").strip().lower()
                summary = (r["summary"] or "").strip()

                if m_name in seen_lb_models:
                    # Если модель уже представлена в снимке (например и в text, и в vision)
                    existing = seen_lb_models[m_name]
                    if cat_tag and cat_tag not in existing["tags"]:
                        existing["tags"].append(cat_tag)
                    continue

                card_tags = ["lmsys arena", "бенчмарк"]
                if cat_tag:
                    card_tags.append(cat_tag)
                if cat_tag in ("vision", "text-to-image", "image-edit"):
                    card_tags.extend(["компьютерное зрение", "vision", "изображения", "мультимодальный"])

                card = {
                    "id": f"lb_{r['rowid']}",
                    "title": m_name,
                    "category": "модель",
                    "summary": summary,
                    "full_description": summary,
                    "url": f"https://huggingface.co/{m_name}",
                    "tags": card_tags,
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
                }
                seen_lb_models[m_name] = card
                cards.append(card)
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
        parts.append(f"Направления и теги: {tags}")
    if summary:
        parts.append(f"Описание: {summary[:600]}")

    return "\n".join(parts)


def build_index(force: bool = False) -> int:
    """
    Строит / обновляет векторный индекс карточек в SQLite через sqlite-vec (vec_cards и rag_cards).
    Возвращает количество проиндексированных карточек.
    """
    global _INDEX_CARDS, _LAST_BUILD_TS

    with _LOCK:
        now = time.monotonic()
        if not force and _INDEX_CARDS and (now - _LAST_BUILD_TS < _REBUILD_INTERVAL_SEC):
            return len(_INDEX_CARDS)

        # Если в памяти пусто, но индекс уже есть в SQLite:
        if not force and not _INDEX_CARDS and (now - _LAST_BUILD_TS < _REBUILD_INTERVAL_SEC):
            try:
                with database.get_connection() as conn:
                    cnt = conn.execute("SELECT count(*) FROM vec_cards").fetchone()[0]
                    if cnt > 0:
                        rows = conn.execute("SELECT data FROM rag_cards").fetchall()
                        _INDEX_CARDS = [json.loads(r["data"]) for r in rows]
                        _LAST_BUILD_TS = now
                        return len(_INDEX_CARDS)
            except Exception:
                pass

        cards = _load_all_cards_from_db()
        if not cards:
            _INDEX_CARDS = []
            try:
                with database.get_connection() as conn:
                    conn.execute("DELETE FROM vec_cards")
                    conn.execute("DELETE FROM rag_cards")
            except Exception:
                pass
            _LAST_BUILD_TS = now
            return 0

        texts = [_make_search_text(c) for c in cards]
        raw_vectors = dedup.batch_texts_to_vectors(texts)

        valid_cards = []
        vec_entries = []
        rag_entries = []

        for c, vec in zip(cards, raw_vectors):
            if not vec or len(vec) != config.VECTOR_DIM:
                continue
            card_key = c.get("id")
            if not card_key:
                continue
            cat = (c.get("category") or "").strip().lower()
            blob = dedup.serialize_float32(vec)
            card_json = json.dumps(c, ensure_ascii=False)
            title = c.get("title", "")
            url = c.get("url", "")

            valid_cards.append(c)
            vec_entries.append((card_key, cat, blob))
            rag_entries.append((card_key, cat, title, url, card_json))

        try:
            with database.get_connection() as conn:
                conn.execute("DELETE FROM vec_cards")
                conn.execute("DELETE FROM rag_cards")
                if vec_entries:
                    conn.executemany(
                        "INSERT INTO vec_cards(card_key, category, embedding) VALUES (?, ?, ?)",
                        vec_entries,
                    )
                    conn.executemany(
                        "INSERT INTO rag_cards(card_key, category, title, url, data) VALUES (?, ?, ?, ?, ?)",
                        rag_entries,
                    )
            _INDEX_CARDS = valid_cards
            _LAST_BUILD_TS = now
            logger.info(f"Векторный индекс sqlite-vec построен: {len(_INDEX_CARDS)} карточек")
            return len(_INDEX_CARDS)
        except Exception as e:
            logger.error(f"Ошибка сохранения индекса в sqlite-vec: {e}")
            _INDEX_CARDS = valid_cards
            _LAST_BUILD_TS = now
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

    if not _INDEX_CARDS:
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
    if not _INDEX_CARDS:
        build_index()
    else:
        # Фоновое обновление при устаревании (не блокируя текущий поиск)
        now = time.monotonic()
        if now - _LAST_BUILD_TS > _REBUILD_INTERVAL_SEC:
            threading.Thread(target=build_index, daemon=True).start()

    if not _INDEX_CARDS:
        return []

    # 1. Очистка запроса от разговорных фраз и приветствий
    raw_query = query.strip()
    clean_q = re.sub(
        r"^(?:привет|здравствуй|здравствуйте|добрый день|хай|hello|hi|йоу)[,\s!.]*",
        "",
        raw_query,
        flags=re.IGNORECASE,
    )
    clean_q = re.sub(
        r"^(?:подскажи|расскажи|покажи|найди|интересует|хочу узнать(?: про)?|что есть по|посоветуй)[,\s!:]*",
        "",
        clean_q.strip(),
        flags=re.IGNORECASE,
    ).strip()

    search_query = clean_q if len(clean_q) >= 3 else raw_query

    # 2. Обогащение запроса ключевыми синонимами предметных областей
    enriched_query = search_query
    low_q = search_query.lower()
    if ("компьютерн" in low_q and "зрен" in low_q) or ("cv" in low_q.split()):
        enriched_query += " computer vision cv визуальные модели зрение сегментация детекция"
    elif "медицин" in low_q or "здравоохран" in low_q:
        enriched_query += " healthcare medical health_ai биомедицина"
    elif "аудио" in low_q or "звук" in low_q or "реч" in low_q:
        enriched_query += " audio speech ASR распознавание звука"
    elif "робототехник" in low_q or "робот" in low_q:
        enriched_query += " robotics автономные системы"
    elif "агент" in low_q:
        enriched_query += " agents мультиагентные системы tool calling"

    query_vec = dedup.text_to_vector(enriched_query)
    if not query_vec:
        return []

    category_filter = category.strip().lower() if category else "all"
    max_distance = max(0.0, min(2.0, 1.0 - min_score))
    query_blob = dedup.serialize_float32(query_vec)

    # 3. Векторный KNN-поиск через sqlite-vec (запрашиваем широкий пул кандидатов для дедупликации)
    candidate_k = max(limit * 8, 50)
    raw_candidates = []

    try:
        with database.get_connection() as conn:
            if category_filter == "all":
                cursor = conn.execute(
                    """
                    SELECT v.card_key, v.category, v.distance, c.data
                    FROM vec_cards v
                    JOIN rag_cards c ON v.card_key = c.card_key
                    WHERE v.embedding MATCH ?
                      AND k = ?
                      AND v.distance <= ?
                    ORDER BY v.distance ASC
                    """,
                    (query_blob, candidate_k, max_distance),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT v.card_key, v.category, v.distance, c.data
                    FROM vec_cards v
                    JOIN rag_cards c ON v.card_key = c.card_key
                    WHERE v.embedding MATCH ?
                      AND k = ?
                      AND v.category = ?
                      AND v.distance <= ?
                    ORDER BY v.distance ASC
                    """,
                    (query_blob, candidate_k, category_filter, max_distance),
                )

            rows = cursor.fetchall()
            for r in rows:
                dist = float(r["distance"])
                score = max(0.0, min(1.0, 1.0 - dist))
                if score < min_score:
                    continue
                try:
                    card = json.loads(r["data"])
                    raw_candidates.append({
                        "card": card,
                        "score": score,
                    })
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"Поиск через sqlite-vec не сработал ({e}), fallback на чистый Python...")
        raw_candidates = []
        for c in _INDEX_CARDS:
            c_cat = (c.get("category") or "").lower()
            if category_filter != "all" and c_cat != category_filter:
                continue
            c_text = _make_search_text(c)
            c_vec = dedup.text_to_vector(c_text)
            sim = dedup.cosine_similarity(query_vec, c_vec)
            if sim >= min_score:
                raw_candidates.append({"card": c, "score": sim})
        raw_candidates.sort(key=lambda x: x["score"], reverse=True)

    # 4. Строгая дедупликация кандидатов по нормализованному названию и URL
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    deduped_candidates = []

    for item in raw_candidates:
        c = item["card"]
        title_raw = str(c.get("title") or "").strip()
        title_norm = re.sub(r"[^\w\s]", "", title_raw.lower()).strip()
        url_norm = str(c.get("url") or "").strip().rstrip("/").lower()

        if not title_norm:
            continue
        if title_norm in seen_titles or (url_norm and url_norm in seen_urls):
            continue

        seen_titles.add(title_norm)
        if url_norm:
            seen_urls.add(url_norm)

        deduped_candidates.append(item)

    if not deduped_candidates:
        return []

    # 5. Балансировка разнообразия при category="all"
    if category_filter == "all" and len(deduped_candidates) > limit:
        by_cat: dict[str, list[dict[str, Any]]] = {
            "статья": [],
            "модель": [],
            "датасет": [],
            "репозиторий": [],
        }
        for item in deduped_candidates:
            cat = (item["card"].get("category") or "").lower()
            if cat in by_cat:
                by_cat[cat].append(item)
            else:
                by_cat.setdefault("другое", []).append(item)

        selected: list[dict[str, Any]] = []

        # а) До 2 лучших статей
        selected.extend(by_cat.get("статья", [])[:2])

        # б) До 2 лучших моделей (сначала реальные модели из hf_trending, затем arena)
        models_hf = [m for m in by_cat.get("модель", []) if not str(m["card"].get("id", "")).startswith("lb_")]
        models_lb = [m for m in by_cat.get("модель", []) if str(m["card"].get("id", "")).startswith("lb_")]
        selected.extend((models_hf + models_lb)[:2])

        # в) До 1 лучшего датасета или репозитория
        if by_cat.get("датасет"):
            selected.append(by_cat["датасет"][0])
        elif by_cat.get("репозиторий"):
            selected.append(by_cat["репозиторий"][0])

        # г) Добираем оставшиеся слоты лучшими по score из общего списка
        chosen_ids = {c["card"]["id"] for c in selected}
        for item in deduped_candidates:
            if len(selected) >= limit:
                break
            if item["card"]["id"] not in chosen_ids:
                selected.append(item)
                chosen_ids.add(item["card"]["id"])

        selected.sort(key=lambda x: x["score"], reverse=True)
        return selected[:limit]

    return deduped_candidates[:limit]


def get_catalog_stats() -> dict[str, int]:
    """Возвращает агрегированную статистику проиндексированных карточек."""
    build_index()
    stats = {
        "всего": 0,
        "модели": 0,
        "датасеты": 0,
        "репозитории": 0,
        "статьи": 0,
    }
    try:
        with database.get_connection() as conn:
            rows = conn.execute("SELECT category, count(*) FROM rag_cards GROUP BY category").fetchall()
            total = 0
            for r in rows:
                cat = (r[0] or "").lower()
                cnt = int(r[1])
                total += cnt
                if cat == "модель":
                    stats["модели"] += cnt
                elif cat == "датасет":
                    stats["датасеты"] += cnt
                elif cat == "репозиторий":
                    stats["репозитории"] += cnt
                else:
                    stats["статьи"] += cnt
            stats["всего"] = total
            if total > 0:
                return stats
    except Exception:
        pass

    # Fallback на _INDEX_CARDS
    stats["всего"] = len(_INDEX_CARDS)
    for c in _INDEX_CARDS:
        cat = (c.get("category") or "").lower()
        if cat == "модель":
            stats["модели"] += 1
        elif cat == "датасет":
            stats["датасеты"] += 1
        elif cat == "репозиторий":
            stats["репозитории"] += 1
        else:
            stats["статьи"] += 1
    return stats
