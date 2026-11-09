try:
    import pytest
except ImportError:
    class _MockPytest:
        class mark:
            @staticmethod
            def parametrize(*args, **kwargs):
                return lambda fn: fn
    pytest = _MockPytest()

from leaderboard_view import (
    aggregate_all_categories,
    build_latest_records,
    category_count_label,
    format_rating,
)


def snap(fetched_at, **categories):
    return {
        "fetched_at": fetched_at,
        "categories": {
            cat: [{"name": n, "rating": r} for n, r in models]
            for cat, models in categories.items()
        },
    }


def test_only_latest_snapshot_per_category():
    old = snap("2026-07-01T10:00:00", text=[("A", 1000), ("B", 900)])
    new = snap("2026-07-04T10:00:00", text=[("A", 1010), ("B", 905)])
    records = build_latest_records([old, new])  # порядок входа не важен
    assert len(records) == 2
    assert {r["model_name"]: r["rating"] for r in records} == {"A": 1010, "B": 905}


def test_partial_scrape_falls_back_to_previous_snapshot():
    old = snap("2026-07-01T10:00:00", text=[("A", 1000)], vision=[("V", 800)])
    new = snap("2026-07-04T10:00:00", text=[("A", 1010)])  # vision не собрался
    records = build_latest_records([new, old])
    by_cat = {r["category"]: r for r in records}
    assert by_cat["text"]["rating"] == 1010
    assert by_cat["vision"]["rating"] == 800


def test_invalid_ratings_and_names_are_skipped():
    s = snap("2026-07-01", text=[("A", "n/a"), ("B", None), ("", 5), ("C", "1200"), ("D", float("nan"))])
    records = build_latest_records([s])
    assert [(r["model_name"], r["rating"]) for r in records] == [("C", 1200.0)]


def test_empty_input():
    assert build_latest_records([]) == []
    assert aggregate_all_categories([]) == []


def test_aggregate_average_sort_and_categories():
    s = snap(
        "2026-07-01",
        text=[("A", 1400), ("B", 1290)],
        vision=[("A", 1200), ("C", 1250)],
    )
    result = aggregate_all_categories(build_latest_records([s]))
    assert [r["model_name"] for r in result] == ["A", "B", "C"]  # 1300, 1290, 1250
    a = next(r for r in result if r["model_name"] == "A")
    assert a["rating"] == 1300
    assert a["categories"] == ["text", "vision"]
    assert a["category"] == "2 категории"
    # результат отсортирован по убыванию
    ratings = [r["rating"] for r in result]
    assert ratings == sorted(ratings, reverse=True)


def test_aggregate_max_method():
    s = snap(
        "2026-07-01",
        text=[("A", 1400), ("B", 1290)],
        vision=[("A", 1200), ("C", 1250)],
    )
    result = aggregate_all_categories(build_latest_records([s]), method="max")
    a = next(r for r in result if r["model_name"] == "A")
    assert a["rating"] == 1400  # Максимум из 1400 и 1200
    assert a["category"] == "МАКС: TEXT (2 категории: TEXT, VISION)"


@pytest.mark.parametrize("n,expected", [
    (1, "1 категория"), (2, "2 категории"), (4, "4 категории"),
    (5, "5 категорий"), (11, "11 категорий"), (12, "12 категорий"),
    (21, "21 категория"), (22, "22 категории"),
])
def test_category_count_label(n, expected):
    assert category_count_label(n) == expected


def test_format_rating():
    assert format_rating(1234.0) == "1234"
    assert format_rating(1403.666) == "1403.7"


def test_summary_is_generated_when_missing():
    s = snap("2026-07-01", text=[("Claude Opus 5.5", 1800)])
    records = build_latest_records([s])
    assert len(records) == 1
    assert "Anthropic" in records[0]["summary"]
    assert len(records[0]["summary"]) > 20
    assert "•" not in records[0]["summary"]


def test_aggregate_summary_is_preserved_or_generated():
    s = snap("2026-07-01", text=[("DeepSeek-V3", 1400)])
    records = build_latest_records([s])
    agg = aggregate_all_categories(records)
    assert len(agg) == 1
    assert "DeepSeek" in agg[0]["summary"]
    assert "•" not in agg[0]["summary"]
