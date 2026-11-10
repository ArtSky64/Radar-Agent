"""Подготовка данных лидерборда для frontend.py.

Чистая логика без Streamlit: так её можно покрыть тестами
(frontend.py выполняет код отрисовки прямо при импорте).
"""
import math
from collections import defaultdict
from arena_scraper import get_model_url

ALL_CATEGORIES = "Все категории"


def _to_number(value) -> float | None:
    """Приводит рейтинг к float. Мусор (строка, None, NaN, inf) -> None.

    arena_scraper.parse() при ValueError оставляет рейтинг строкой, а SQLite
    с INTEGER-колонкой такую строку принимает без ошибок — поэтому во
    фронтенд может дойти не число.
    """
    if isinstance(value, bool):
        return None
    
    # Если пришла строка с процентами (вдруг спарсился winrate вместо elo)
    if isinstance(value, str):
        value = value.replace('%', '').strip()
        
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_latest_records(snapshots: list[dict]) -> list[dict]:
    """Плоский список записей: по каждой категории берётся ТОЛЬКО самый
    свежий снимок, в котором эта категория есть.
    """
    records: list[dict] = []
    seen_categories: set[str] = set()

    for snap in sorted(snapshots, key=lambda s: s.get("fetched_at") or "", reverse=True):
        fetched_at = snap.get("fetched_at")
        for category, models in (snap.get("categories") or {}).items():
            if category in seen_categories:
                continue
            seen_categories.add(category)
            for m in models:
                name = m.get("name")
                rating = _to_number(m.get("rating"))
                if not name or rating is None:
                    continue
                org = m.get("organization") or ""
                lic = m.get("license") or ""
                url = m.get("url") or get_model_url(name, org, lic, category)
                records.append({
                    "category": category,
                    "model_name": name,
                    "rating": rating,
                    "fetched_at": fetched_at,
                    "organization": org,
                    "license": lic,
                    "vote_count": int(m.get("vote_count", 0) or 0),
                    "summary": m.get("summary") or "",
                    "url": url,
                })
    return records


def aggregate_all_categories(records: list[dict], method: str = "avg") -> list[dict]:
    """Режим «Все категории»: одна строка на модель.
    method='avg': рейтинг — среднее по категориям, где модель присутствует.
    method='max': рейтинг — максимум по категориям.
    """
    by_model = defaultdict(list)
    for r in records:
        by_model[r["model_name"]].append(r)

    result = []
    for name, rows in by_model.items():
        if method == "max":
            best_row = max(rows, key=lambda x: x["rating"])
            rating = best_row["rating"]
            cat_list = ", ".join(sorted(r["category"].upper() for r in rows))
            cat_label = f"МАКС: {best_row['category'].upper()} ({len(rows)} {category_count_label(len(rows)).split()[1]}: {cat_list})"
        else:
            rating = sum(r["rating"] for r in rows) / len(rows)
            cat_label = category_count_label(len(rows))

        first_row = rows[0]
        result.append({
            "model_name": name,
            "rating": rating,
            "categories": sorted(r["category"] for r in rows),
            "category": cat_label,
            "organization": first_row.get("organization") or "",
            "license": first_row.get("license") or "",
            "vote_count": sum(r.get("vote_count", 0) for r in rows),
            "summary": first_row.get("summary") or "",
            "url": first_row.get("url") or "",
        })

    return sorted(result, key=lambda x: x["rating"], reverse=True)


def category_count_label(n: int) -> str:
    """Возвращает строку с правильным склонением слова «категория»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} категория"
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return f"{n} категории"
    else:
        return f"{n} категорий"


def format_rating(rating: float) -> str:
    """Форматирует число рейтинга: целое без нулей на конце, иначе 1 знак после запятой."""
    if rating.is_integer():
        return str(int(rating))
    return f"{rating:.1f}"