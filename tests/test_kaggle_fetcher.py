import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from kaggle_fetcher import (
    _extract_tags,
    _extract_kernel_count,
    _extract_vote_count,
    _extract_full_text,
    _build_kaggle_code_link,
    SelectionResult,
    fetch_trending_kaggle_datasets,
    stream_kaggle_articles,
)


def test_extract_tags():
    detail = {
        "tags": [
            {"name": "biology", "ref": "bio"},
            {"title": "machine learning"},
            "nlp",
            {"name": "biology"},  # duplicate
            "",
            None,
        ]
    }
    list_item = {"tags": [{"name": "deep learning"}, "nlp"]}
    tags = _extract_tags(detail, list_item)
    assert tags == ["biology", "machine learning", "nlp"]


def test_extract_kernel_count():
    assert _extract_kernel_count({"kernelCount": 150}, {}) == 150
    assert _extract_kernel_count({}, {"totalKernels": "42"}) == 42
    assert _extract_kernel_count({}, {}) is None


def test_extract_vote_count():
    assert _extract_vote_count({"voteCount": 85}, {}) == 85
    assert _extract_vote_count({}, {"votes": "12"}) == 12
    assert _extract_vote_count({}, {}) == 0


def test_extract_full_text():
    # Both subtitle and description
    det = {"subtitle": "Short summary", "description": "Full details about dataset."}
    text = _extract_full_text(det, {})
    assert "Short summary" in text
    assert "Full details about dataset." in text

    # Empty description fallback to title
    det_empty = {"title": "Dataset Title"}
    text_empty = _extract_full_text(det_empty, {})
    assert text_empty == "Dataset Title"


def test_build_kaggle_code_link():
    link_with_count = _build_kaggle_code_link("https://www.kaggle.com/datasets/user/data/code", 42)
    assert link_with_count["type"] == "kaggle_code"
    assert link_with_count["name"] == "Решения (Code)"
    assert link_with_count["url"] == "https://www.kaggle.com/datasets/user/data/code"
    assert link_with_count["count"] == 42

    link_no_count = _build_kaggle_code_link("https://www.kaggle.com/datasets/user/data/code", None)
    assert "count" not in link_no_count


def test_selection_result_schema():
    res = SelectionResult(selected_ids=["dataset:user/ds1", "dataset:user/ds2"])
    assert res.selected_ids == ["dataset:user/ds1", "dataset:user/ds2"]


def test_fetch_trending_kaggle_datasets_mocked():
    async def _test():
        with patch("kaggle_fetcher._collect_trending_dataset_candidates", new_callable=AsyncMock) as mock_collect:
            mock_collect.return_value = [
                {
                    "id": "dataset:testuser/test-dataset",
                    "ref": "testuser/test-dataset",
                    "title": "Test Trending Dataset",
                    "full_text": "Comprehensive description of the test dataset for AI research.",
                    "url": "https://www.kaggle.com/datasets/testuser/test-dataset",
                    "tags": ["ai", "tabular"],
                    "votes": 50,
                    "kernel_count": 25,
                    "related_links": [_build_kaggle_code_link("https://www.kaggle.com/datasets/testuser/test-dataset/code", 25)],
                }
            ]

            results = await fetch_trending_kaggle_datasets(limit=1)
            assert len(results) == 1
            art = results[0]
            assert art["title"] == "[Kaggle] Test Trending Dataset"
            assert art["source_type"] == "датасет"
            assert art["source_url"] == "https://www.kaggle.com/datasets/testuser/test-dataset"
            assert art["tags"] == ["ai", "tabular"]
            assert art["stars"] == 50
            assert art["has_code"] == 1
            assert len(art["related_links"]) == 1
            assert art["related_links"][0]["type"] == "kaggle_code"
            assert art["related_links"][0]["count"] == 25

    asyncio.run(_test())
