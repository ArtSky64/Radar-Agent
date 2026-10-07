import os
import sqlite3
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

import config

DB_NAME = config.DB_NAME


@contextmanager
def get_connection():
    db_dir = os.path.dirname(os.path.abspath(DB_NAME))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS vectors (
            vector_data TEXT NOT NULL,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        );''')
        cursor.execute("""CREATE TABLE IF NOT EXISTS articles (
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            source_url TEXT NOT NULL,
            tags TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'статья',
            language TEXT NOT NULL DEFAULT '',
            topic_tag TEXT NOT NULL DEFAULT '',
            related_links TEXT NOT NULL DEFAULT '',
            source_article_url TEXT NOT NULL DEFAULT '',
            period TEXT NOT NULL DEFAULT '',
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        );""")

        # Миграция для БД, созданных до появления новых колонок — CREATE
        # TABLE IF NOT EXISTS не добавит колонку в уже существующую таблицу.
        existing_cols = {row['name'] for row in cursor.execute("PRAGMA table_info(articles)")}
        if 'source_type' not in existing_cols:
            cursor.execute("ALTER TABLE articles ADD COLUMN source_type TEXT NOT NULL DEFAULT 'статья'")
        if 'language' not in existing_cols:
            cursor.execute("ALTER TABLE articles ADD COLUMN language TEXT NOT NULL DEFAULT ''")
        if 'topic_tag' not in existing_cols:
            cursor.execute("ALTER TABLE articles ADD COLUMN topic_tag TEXT NOT NULL DEFAULT ''")
        if 'related_links' not in existing_cols:
            cursor.execute("ALTER TABLE articles ADD COLUMN related_links TEXT NOT NULL DEFAULT ''")
        if 'source_article_url' not in existing_cols:
            cursor.execute("ALTER TABLE articles ADD COLUMN source_article_url TEXT NOT NULL DEFAULT ''")
        if 'period' not in existing_cols:
            cursor.execute("ALTER TABLE articles ADD COLUMN period TEXT NOT NULL DEFAULT ''")
        cursor.execute('''CREATE TABLE IF NOT EXISTS leaderboard (
            category TEXT NOT NULL,
            model_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            fetched_at TEXT NOT NULL
        );''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS leaderboard_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT NOT NULL,
            analysis_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS hf_trending (
            model_name TEXT NOT NULL,
            downloads INTEGER NOT NULL,
            likes INTEGER NOT NULL,
            tags TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );''')

        # Миграция для БД, созданных до появления source_url/summary в hf_trending
        trending_cols = {row['name'] for row in cursor.execute("PRAGMA table_info(hf_trending)")}
        if 'source_url' not in trending_cols:
            cursor.execute("ALTER TABLE hf_trending ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
        if 'summary' not in trending_cols:
            cursor.execute("ALTER TABLE hf_trending ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
        if 'pipeline_tag' not in trending_cols:
            cursor.execute("ALTER TABLE hf_trending ADD COLUMN pipeline_tag TEXT NOT NULL DEFAULT ''")
        if 'license' not in trending_cols:
            cursor.execute("ALTER TABLE hf_trending ADD COLUMN license TEXT NOT NULL DEFAULT ''")
        if 'card_description' not in trending_cols:
            cursor.execute("ALTER TABLE hf_trending ADD COLUMN card_description TEXT NOT NULL DEFAULT ''")
        if 'language' not in trending_cols:
            cursor.execute("ALTER TABLE hf_trending ADD COLUMN language TEXT NOT NULL DEFAULT ''")
        if 'variant' not in trending_cols:
            cursor.execute("ALTER TABLE hf_trending ADD COLUMN variant TEXT NOT NULL DEFAULT ''")
        conn.commit()


# ==========================================
# ОСНОВНОЕ ХРАНИЛИЩЕ (Векторы и Статьи)
# ==========================================

def save_vector(vector: list[float]) -> None:
    with get_connection() as conn:
        conn.execute('INSERT INTO vectors (vector_data) VALUES (?)', (json.dumps(vector),))


def get_all_vectors():
    with get_connection() as conn:
        cursor = conn.execute('SELECT vector_data FROM vectors')
        for row in cursor:
            yield json.loads(row['vector_data'])


def save_article(article: dict) -> None:
    # source_type: 'статья' | 'модель' | 'датасет' | 'репозиторий' — проставляется
    # фетчером через main.py (_tag_source_type). Если источник его не передал,
    # по умолчанию считаем это обычной статьёй, чтобы не сломать старые вызовы.
    related_links = article.get('related_links', '')
    if isinstance(related_links, (list, dict)):
        related_links = json.dumps(related_links, ensure_ascii=False)

    tags = article.get('tags', [])
    if isinstance(tags, (list, dict)):
        tags_str = json.dumps(tags, ensure_ascii=False)
    else:
        tags_str = str(tags)

    with get_connection() as conn:
        conn.execute('''
            INSERT INTO articles (
                title, summary, source_url, tags, source_type, language,
                topic_tag, related_links, source_article_url, period
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            article['title'],
            article.get('summary', ''),
            article['source_url'],
            tags_str,
            article.get('source_type', 'статья'),
            article.get('language', ''),
            article.get('topic_tag', ''),
            related_links,
            article.get('source_article_url', ''),
            article.get('period', ''),
        ))


def upsert_related_material(material: dict, source_article_url: str) -> None:
    """
    ТЗ 1.3: Связанные датасеты/модели из карточки статьи.
    Если модели/датасета ещё нет в БД — вставляем;
    если есть — добавляем source_article_url к записи.
    """
    name = material.get('name') or material.get('title') or ''
    source_url = material.get('url') or material.get('source_url') or ''
    source_type = material.get('type') or material.get('source_type') or 'модель'
    summary = material.get('summary', f"Связанный материал к статье: {source_article_url}")

    if not source_url and not name:
        return

    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT rowid, source_article_url FROM articles WHERE (source_url != '' AND source_url = ?) OR (title = ? AND source_type = ?)",
            (source_url, name, source_type)
        )
        row = cursor.fetchone()
        if row:
            curr_source = row['source_article_url'] or ''
            if source_article_url and source_article_url not in curr_source:
                new_source = f"{curr_source}, {source_article_url}".strip(", ")
                conn.execute(
                    "UPDATE articles SET source_article_url = ? WHERE rowid = ?",
                    (new_source, row['rowid'])
                )
        else:
            conn.execute('''
                INSERT INTO articles (
                    title, summary, source_url, tags, source_type, language,
                    topic_tag, related_links, source_article_url, period
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                name,
                summary,
                source_url,
                json.dumps([source_type], ensure_ascii=False),
                source_type,
                '',
                '',
                '',
                source_article_url,
                '',
            ))


def get_all_articles() -> list[dict]:
    with get_connection() as conn:
        # Без ORDER BY SQLite отдаёт по rowid (порядок вставки) — старые статьи
        # были наверху. Сортируем по added_at, новые сначала; rowid DESC как
        # тай-брейк для записей с одинаковой секундой добавления.
        cursor = conn.execute('SELECT rowid, * FROM articles ORDER BY added_at DESC, rowid DESC')
        articles = []
        for row in cursor:
            article = dict(row)
            try:
                article['tags'] = json.loads(article['tags'])
            except Exception:
                pass
            if 'related_links' in article and article['related_links']:
                try:
                    article['related_links'] = json.loads(article['related_links'])
                except Exception:
                    pass
            articles.append(article)
        return articles



def clear_articles() -> None:
    with get_connection() as conn:
        conn.execute('DELETE FROM articles')


def delete_old_vectors(days: int = 14) -> None:
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    with get_connection() as conn:
        conn.execute('DELETE FROM vectors WHERE added_at < ?', (cutoff_date,))


# ==========================================
# ХРАНИЛИЩЕ ЛИДЕРБОРДА (arena.ai)
# ==========================================

def save_leaderboard_data(data: dict) -> None:
    fetched_at = data['fetched_at']
    records_to_insert = []

    # 1. Разворачиваем структуру categories в плоский список записей
    for category, models in data['categories'].items():
        for model in models:
            records_to_insert.append((category, model['name'], model['rating'], fetched_at))

    with get_connection() as conn:
        # 2. Проверяем существование таблицы (на всякий случай, по ТЗ)
        conn.execute('''CREATE TABLE IF NOT EXISTS leaderboard (
            category TEXT NOT NULL,
            model_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            fetched_at TEXT NOT NULL
        );''')

        # 3. Проверка текущего объема (ищем уникальные даты)
        cursor = conn.execute('SELECT DISTINCT fetched_at FROM leaderboard ORDER BY fetched_at DESC')
        dates = [row['fetched_at'] for row in cursor.fetchall()]

        # 4. Условие удаления: берет самую старую и полностью удаляет
        if len(dates) >= 2:
            oldest_date = dates[-1]
            conn.execute('DELETE FROM leaderboard WHERE fetched_at = ?', (oldest_date,))

        # 5. Массовая вставка всех записей одной операцией
        conn.executemany('''
            INSERT INTO leaderboard (category, model_name, rating, fetched_at)
            VALUES (?, ?, ?, ?)
        ''', records_to_insert)


def save_analysis(fetched_at: str, analysis_text: str) -> None:
    """
    Сохраняет новый текстовый анализ лидерборда. В отличие от save_leaderboard_data,
    НИЧЕГО не удаляет — каждый анализ добавляется к истории, чтобы следующий анализ
    мог опираться на всё, что было написано раньше.
    """
    with get_connection() as conn:
        conn.execute('''
            INSERT INTO leaderboard_analysis (fetched_at, analysis_text)
            VALUES (?, ?)
        ''', (fetched_at, analysis_text))


def get_latest_analysis() -> dict | None:
    """Самый свежий сохранённый анализ (или None, если анализов ещё не было)."""
    with get_connection() as conn:
        cursor = conn.execute(
            'SELECT * FROM leaderboard_analysis ORDER BY id DESC LIMIT 1'
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_analysis_history(limit: int = 10) -> list[dict]:
    """История анализов от новых к старым — для отображения динамики на фронтенде."""
    with get_connection() as conn:
        cursor = conn.execute(
            'SELECT * FROM leaderboard_analysis ORDER BY id DESC LIMIT ?', (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]



def save_trending_models(models: list[dict]) -> None:
    """
    Полностью заменяет предыдущую витрину трендовых моделей новой.
    models: [{"name": str, "downloads": int, "likes": int, "tags": list[str], "url": str, "summary": str, "pipeline_tag": str, "license": str, "card_description": str, "language": str, "variant": str}, ...]
    """
    fetched_at = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute('DELETE FROM hf_trending')
        conn.executemany('''
            INSERT INTO hf_trending (
                model_name, downloads, likes, tags, source_url, summary, fetched_at,
                pipeline_tag, license, card_description, language, variant
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', [
            (
                m["name"],
                m["downloads"],
                m["likes"],
                json.dumps(m["tags"]),
                m.get("url") or f"https://huggingface.co/{m['name']}",
                m.get("summary") or "",
                fetched_at,
                m.get("pipeline_tag") or "",
                m.get("license") or "",
                m.get("card_description") or "",
                m.get("language") or "",
                m.get("variant") or ""
            )
            for m in models
        ])


def get_trending_models() -> list[dict]:
    """Текущая витрина трендовых моделей (порядок сохранён как при сохранении)."""
    with get_connection() as conn:
        cursor = conn.execute('SELECT rowid, * FROM hf_trending ORDER BY rowid ASC')
        result = []
        for row in cursor:
            item = dict(row)
            item['tags'] = json.loads(item['tags'])
            result.append(item)
        return result


def get_all_leaderboard_snapshots() -> list[dict]:
    with get_connection() as conn:
        # Вычитывает все данные из leaderboard
        cursor = conn.execute('SELECT * FROM leaderboard ORDER BY fetched_at DESC')
        rows = cursor.fetchall()

    snapshots_map = {}

    # Код автоматически группирует плоские строки обратно в формат исходных "мега-словарей"
    for row in rows:
        f_at = row['fetched_at']
        if f_at not in snapshots_map:
            snapshots_map[f_at] = {
                "fetched_at": f_at,
                "categories": {}
            }

        cat = row['category']
        if cat not in snapshots_map[f_at]["categories"]:
            snapshots_map[f_at]["categories"][cat] = []

        snapshots_map[f_at]["categories"][cat].append({
            "name": row['model_name'],
            "rating": row['rating']
        })

    return list(snapshots_map.values())


# ==========================================
# БЛОК ДЛЯ ТЕСТИРОВАНИЯ И ПРОСМОТРА ТАБЛИЦ
# ==========================================
if __name__ == '__main__':
    print("--- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---")
    init_db()
    print("Таблицы успешно созданы.\n")

    print("--- СОХРАНЕНИЕ ТЕСТОВЫХ ДАННЫХ ---")
    # Добавляем статью
    save_article({
        "title": "GPT-5 взломал Пентагон",
        "summary": "Шуточная статья для теста.",
        "source_url": "https://test.com",
        "tags": ["ии", "новости"]
    })

    # Добавляем вектор
    save_vector([0.1, 0.2, 0.3])

    # Добавляем 3 слепка лидерборда (чтобы проверить ротацию).
    # Старый "Слепок 1" должен автоматически удалиться!
    snapshot_1 = {"fetched_at": "2026-07-01", "categories": {"text": [{"name": "Model-A", "rating": 1000}]}}
    snapshot_2 = {"fetched_at": "2026-07-02", "categories": {"text": [{"name": "Model-B", "rating": 1100}]}}
    snapshot_3 = {"fetched_at": "2026-07-03", "categories": {"text": [{"name": "Model-C", "rating": 1200}]}}

    save_leaderboard_data(snapshot_1)
    save_leaderboard_data(snapshot_2)
    save_leaderboard_data(snapshot_3)  # Тут сработает удаление первого слепка
    print("Данные сохранены! Ротация лидерборда отработала.\n")

    print("    ВИЗУАЛИЗАЦИЯ ТАБЛИЦ ИЗ БАЗЫ ДАННЫХ    ")

    # 1. Показываем статьи
    print(">>> ТАБЛИЦА: articles")
    articles = get_all_articles()
    for a in articles:
        print(f"[{a.get('added_at', 'Только что')}] {a['title']} | Теги: {a['tags']} | Ссылка: {a['source_url']}")
    print("-" * 40)

    # 2. Показываем векторы
    print("\n>>> ТАБЛИЦА: vectors")
    with get_connection() as conn:
        for row in conn.execute('SELECT * FROM vectors'):
            print(f"[{row['added_at']}] Вектор: {row['vector_data']}")
    print("-" * 40)

    # 3. Показываем лидерборд
    print("\n>>> ТАБЛИЦА: leaderboard (Максимум 2 слепка!)")
    snapshots = get_all_leaderboard_snapshots()
    for snap in snapshots:
        print(f"Слепок от: {snap['fetched_at']}")
        for cat, models in snap['categories'].items():
            print(f"  Категория '{cat}':")
            for m in models:
                print(f"    - Модель: {m['name']}, Рейтинг: {m['rating']}")
    print("==========================================")