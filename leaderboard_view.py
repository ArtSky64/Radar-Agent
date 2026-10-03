"""Подготовка данных лидерборда для frontend.py.

Чистая логика без Streamlit: так её можно покрыть тестами
(frontend.py выполняет код отрисовки прямо при импорте).
"""
import math
from collections import defaultdict

ALL_CATEGORIES = "Все категории"


def _to_number(value) -> float | None:
    """Приводит рейтинг к float. Мусор (строка, None, NaN, inf) -> None.

    arena_scraper.parse() при ValueError оставляет рейтинг строкой, а SQLite
    с INTEGER-колонкой такую строку принимает без ошибок — поэтому во
    фронтенд может дойти не число.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_latest_records(snapshots: list[dict]) -> list[dict]:
    """Плоский список записей: по каждой категории берётся ТОЛЬКО самый
    свежий снимок, в котором эта категория есть.

    Раньше фронтенд сваливал в один список все снимки (в БД их до 2),
    и одна модель дублировалась даже внутри одной категории. Выбор «свежий
    снимок категории», а не «последний снимок целиком», страхует от
    частичного скрапинга: если в новом снимке часть категорий провалилась,
    они не пропадут из интерфейса, а подтянутся из предыдущего.
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
                records.append({
                    "category": category,
                    "model_name": name,
                    "rating": rating,
                    "fetched_at": fetched_at,
                })
    return records


def aggregate_all_categories(records: list[dict]) -> list[dict]:
    """Режим «Все категории»: одна строка на модель, рейтинг — среднее
    по категориям, где модель присутствует (вариант A из ТЗ, п.5)."""
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_model[r["model_name"]].append(r)

    aggregated = []
    for name, rows in by_model.items():
        categories = sorted({r["category"] for r in rows})
        aggregated.append({
            "model_name": name,
            "rating": sum(r["rating"] for r in rows) / len(rows),
            "categories": categories,
            "category": category_count_label(len(categories)),
        })
    return sorted(aggregated, key=lambda x: x["rating"], reverse=True)


def format_rating(value: float) -> str:
    """1234.0 -> '1234', 1403.666 -> '1403.7'."""
    rounded = round(value)
    return str(int(rounded)) if abs(value - rounded) < 1e-9 else f"{value:.1f}"


def category_count_label(n: int) -> str:
    """Склонение: 1 категория, 2 категории, 5 категорий."""
    if 11 <= n % 100 <= 14:
        word = "категорий"
    elif n % 10 == 1:
        word = "категория"
    elif 2 <= n % 10 <= 4:
        word = "категории"
    else:
        word = "категорий"
    return f"{n} {word}"
