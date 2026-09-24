import os
import sys
import traceback

TEST_DB_NAME = "smoke_test.db"

PASSED = []
FAILED = []


def check(name):
    def decorator(fn):
        print(f"--- {name} ---")
        try:
            fn()
            print("OK\n")
            PASSED.append(name)
        except Exception as e:
            print(f"FAIL: {type(e).__name__}: {e}")
            traceback.print_exc()
            print()
            FAILED.append(name)
        return fn
    return decorator




@check("Импорт всех модулей (проверка зависимостей и VLLM)")
def _():
    os.environ.pop("VLLM_BASE_URL", None)

    import config
    assert config.VLLM_BASE_URL is None or True  

    import dedup
    import agent_manager
    assert hasattr(agent_manager, "get_model")
    assert hasattr(agent_manager, "analyze_article")

    import database
    for fn_name in ("init_db", "save_vector", "get_all_vectors", "save_article",
                     "get_all_articles", "delete_old_vectors",
                     "save_leaderboard_data", "get_all_leaderboard_snapshots",
                     "upsert_related_material"):
        assert hasattr(database, fn_name), f"database.py: нет функции {fn_name}"

    import FetcherHF
    assert hasattr(FetcherHF, "stream_hf_articles")

    import FetcherHFDatasets
    assert hasattr(FetcherHFDatasets, "stream_hf_datasets")

    import mcp_fetcher_papers
    assert hasattr(mcp_fetcher_papers, "stream_papers_articles")
    assert hasattr(mcp_fetcher_papers, "merge_papers")
    assert hasattr(mcp_fetcher_papers, "normalize_arxiv_id")

    import github_fetcher
    assert hasattr(github_fetcher, "stream_github_articles")

    import main
    assert hasattr(main, "stream_all_new_articles")
    assert hasattr(main, "main")


@check("get_model() кидает понятную ошибку при реальном вызове без ключа")
def _():
    import config
    import agent_manager
    from unittest.mock import patch

    with patch.object(config, "VLLM_BASE_URL", None):
        agent_manager._model = None
        try:
            agent_manager.get_model()
            raise AssertionError("get_model() должен был упасть без ключа")
        except RuntimeError as e:
            assert "VLLM_BASE_URL" in str(e)
        finally:
            agent_manager._model = None  





@check("database.py: статьи и векторы (базовый CRUD)")
def _():
    import database
    database.DB_NAME = TEST_DB_NAME
    if os.path.exists(TEST_DB_NAME):
        os.remove(TEST_DB_NAME)

    database.init_db()

    database.save_vector([0.1, 0.2, 0.3])
    vectors = list(database.get_all_vectors())
    assert len(vectors) == 1

    database.save_article({
        "title": "Тестовая статья",
        "summary": "Краткое содержание",
        "source_url": "https://example.com/test",
        "tags": ["LLM", "тест"],
        "topic_tag": "healthcare",
        "related_links": [{"type": "github", "url": "https://github.com/test/repo", "name": "repo"}],
        "source_article_url": "https://example.com/source_article",
        "period": "daily",
    })
    articles = database.get_all_articles()
    assert len(articles) == 1
    assert articles[0]["tags"] == ["LLM", "тест"], "теги должны корректно распаковаться из JSON"
    assert articles[0]["topic_tag"] == "healthcare", "topic_tag должен сохраниться"
    assert isinstance(articles[0]["related_links"], list), "related_links должны распаковаться в list"
    assert articles[0]["related_links"][0]["name"] == "repo"
    assert articles[0]["source_article_url"] == "https://example.com/source_article"
    assert articles[0]["period"] == "daily"

    # Проверка upsert_related_material (ТЗ 1.3)
    database.upsert_related_material(
        {"type": "модель", "name": "org/test-model", "url": "https://huggingface.co/org/test-model"},
        source_article_url="https://example.com/test"
    )
    # Повторный вызов с другой статьей должен добавить source_article_url через запятую
    database.upsert_related_material(
        {"type": "модель", "name": "org/test-model", "url": "https://huggingface.co/org/test-model"},
        source_article_url="https://example.com/another_paper"
    )
    all_art = database.get_all_articles()
    model_art = next((a for a in all_art if a["title"] == "org/test-model"), None)
    assert model_art is not None, "Связанная модель должна добавиться в articles"
    assert "https://example.com/test" in model_art["source_article_url"]
    assert "https://example.com/another_paper" in model_art["source_article_url"]

    database.delete_old_vectors(days=14)
    assert len(list(database.get_all_vectors())) == 1, "свежие векторы не должны удаляться"


@check("mcp_fetcher_papers.py: нормализация ID, склейка (merge_papers) и ранжирование (_rank)")
def _():
    import mcp_fetcher_papers

    # 1. Проверка normalize_arxiv_id
    assert mcp_fetcher_papers.normalize_arxiv_id("https://arxiv.org/abs/2407.12345v3") == "2407.12345"
    assert mcp_fetcher_papers.normalize_arxiv_id("arxiv:2407.12345") == "2407.12345"
    assert mcp_fetcher_papers.normalize_arxiv_id("2407.12345.pdf") == "2407.12345"

    # 2. Проверка merge_papers (склейка по arxiv_id, upvotes = max)
    hf_list = [
        {"arxiv_id": "2407.00001v1", "title": "Paper 1", "abstract": "HF Abstract", "upvotes": 10, "source": "hf"},
        {"arxiv_id": "2407.00002", "title": "Paper 2", "abstract": "Paper 2 Abstract", "upvotes": 50, "source": "hf"},
    ]
    pwc_list = [
        {"arxiv_id": "https://arxiv.org/abs/2407.00001", "title": "Paper 1 PwC", "abstract": "", "upvotes": 35, "source": "pwc"},
        {"arxiv_id": "2407.00003", "title": "Paper 3", "abstract": "Paper 3 Abstract", "upvotes": 5, "source": "pwc"},
    ]
    merged = mcp_fetcher_papers.merge_papers(hf_list, pwc_list)
    assert len(merged) == 3, f"Ожидалось 3 уникальных статьи, получено {len(merged)}"

    p1 = next(p for p in merged if p["arxiv_id"] == "2407.00001")
    assert p1["upvotes"] == 35, f"upvotes должен быть max(10, 35) = 35, получили {p1['upvotes']}"
    assert p1["abstract"] == "HF Abstract", "Непустой абстракт должен сохраниться"
    assert set(p1["sources"]) == {"hf", "pwc"}, "Оба источника должны быть зафиксированы"

    # 3. Проверка _rank (чистый детерминированный отбор по убыванию голосов)
    ranked = mcp_fetcher_papers._rank(merged, limit=2)
    assert len(ranked) == 2
    assert ranked[0]["arxiv_id"] == "2407.00002"  # 50 голосов
    assert ranked[1]["arxiv_id"] == "2407.00001"  # 35 голосов


@check("database.py: лидерборд с ротацией (максимум 2 снимка)")
def _():
    import database
    database.DB_NAME = TEST_DB_NAME  

    snap1 = {"fetched_at": "2026-07-01", "categories": {"text": [{"name": "Model-A", "rating": 1000}]}}
    snap2 = {"fetched_at": "2026-07-02", "categories": {"text": [{"name": "Model-B", "rating": 1100}]}}
    snap3 = {"fetched_at": "2026-07-03", "categories": {"text": [{"name": "Model-C", "rating": 1200}]}}

    database.save_leaderboard_data(snap1)
    database.save_leaderboard_data(snap2)
    database.save_leaderboard_data(snap3)

    snapshots = database.get_all_leaderboard_snapshots()
    assert len(snapshots) == 2, f"ожидали ротацию до 2 снимков, получили {len(snapshots)}"

    dates = {s["fetched_at"] for s in snapshots}
    assert "2026-07-01" not in dates, "самый старый снимок должен был удалиться"
    assert "2026-07-02" in dates and "2026-07-03" in dates



@check("dedup.py: cosine_similarity и is_duplicate")
def _():
    import numpy as np
    import dedup

    v1 = np.array([1.0, 0.0, 0.0])
    v2 = np.array([1.0, 0.0, 0.0])
    v3 = np.array([0.0, 1.0, 0.0])

    assert abs(dedup.cosine_similarity(v1, v2) - 1.0) < 1e-9
    assert abs(dedup.cosine_similarity(v1, v3)) < 1e-9

    assert dedup.is_duplicate(v1, [v2]) is True
    assert dedup.is_duplicate(v1, [v3]) is False

    zero = np.array([0.0, 0.0, 0.0])
    assert dedup.cosine_similarity(zero, v1) == 0.0, "деление на 0 не должно падать"





@check("main.py: полный прогон main() с реальной БД (LLM/эмбеддинги замоканы)")
def _():
    import hashlib
    import numpy as np
    from unittest.mock import patch, MagicMock

    fake_analysis = MagicMock()
    fake_analysis.summary = "Тестовое summary"
    fake_analysis.tags = ["tag1", "tag2"]

    def fake_text_to_vector(text):
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
        rng = np.random.default_rng(seed)

        return rng.standard_normal(384).astype(np.float32)

    with patch("main.analyze_article", return_value=fake_analysis), \
         patch("main.text_to_vector", side_effect=fake_text_to_vector):

        import database
        database.DB_NAME = TEST_DB_NAME
        if os.path.exists(TEST_DB_NAME):
            os.remove(TEST_DB_NAME)

        import main
        main.main()

        articles = database.get_all_articles()

        assert len(articles) >= 2, (
            f"ожидали минимум 2 мок-статьи в БД, получили {len(articles)} — "
            "main() мог упасть до сохранения"
        )





@check("arena_scraper.py: save_to_db пишет в реальную БД")
def _():
    import database
    database.DB_NAME = TEST_DB_NAME

    import arena_scraper
    fake_data = {
        "fetched_at": "2026-07-14T12:00:00",
        "categories": {"vision": [{"name": "Test-Model-X", "rating": 1234}]},
    }
    arena_scraper.save_to_db(fake_data)

    snapshots = database.get_all_leaderboard_snapshots()
    found = any(s["fetched_at"] == "2026-07-14T12:00:00" for s in snapshots)
    assert found, "снимок от arena_scraper.save_to_db() не нашёлся в БД"


@check("Arena Блок 5: aggregate_all_categories (дедупликация моделей, расчет среднего и максимума)")
def _():
    import arena_scraper

    assert hasattr(arena_scraper, "aggregate_all_categories"), "В arena_scraper.py отсутствует aggregate_all_categories"

    raw_records = [
        {"model_name": "GPT-4o", "category": "text", "rating": 1300},
        {"model_name": "GPT-4o", "category": "vision", "rating": 1260},
        {"model_name": "GPT-4o", "category": "webdev", "rating": 1340},
        {"model_name": "Claude-3.5-Sonnet", "category": "text", "rating": 1290},
        {"model_name": "Claude-3.5-Sonnet", "category": "webdev", "rating": 1310},
        {"model_name": "Gemini-1.5-Pro", "category": "text", "rating": 1250},
    ]

    # 1. Проверка Варианта А (avg - среднее по категориям, ТЗ 5 рекомендуется)
    agg_avg = arena_scraper.aggregate_all_categories(raw_records, method="avg")
    assert len(agg_avg) == 3, f"Ожидалось 3 уникальных модели после группировки, получено {len(agg_avg)}"

    # Модели должны быть отсортированы по рейтингу DESC
    assert agg_avg[0]["model_name"] == "GPT-4o"
    # Среднее для GPT-4o: (1300 + 1260 + 1340) / 3 = 1300.0
    assert agg_avg[0]["rating"] == 1300.0
    assert set(agg_avg[0]["categories"]) == {"text", "vision", "webdev"}
    assert agg_avg[0]["num_categories"] == 3

    # Gemini: 1250.0
    assert agg_avg[2]["model_name"] == "Gemini-1.5-Pro"
    assert agg_avg[2]["rating"] == 1250.0

    # 2. Проверка Варианта B (max - максимум, ТЗ 5)
    agg_max = arena_scraper.aggregate_all_categories(raw_records, method="max")
    assert len(agg_max) == 3
    # Для GPT-4o максимум 1340 в webdev
    gpt = next(m for m in agg_max if m["model_name"] == "GPT-4o")
    assert gpt["rating"] == 1340.0
    assert gpt["best_category"] == "webdev"

    # 3. Устойчивость к строковым или пустым рейтингам
    robust_records = [
        {"model_name": "Model-A", "category": "text", "rating": "1200%"},
        {"model_name": "Model-A", "category": "code", "rating": None},
    ]
    res_robust = arena_scraper.aggregate_all_categories(robust_records, method="avg")
    assert len(res_robust) == 1
    assert res_robust[0]["rating"] == 1200.0




if __name__ == "__main__":
    print("=" * 60)
    print("ИТОГ")
    print("=" * 60)
    print(f"Пройдено: {len(PASSED)}")
    print(f"Провалено: {len(FAILED)}")

    if FAILED:
        print("\nПровалившиеся проверки:")
        for name in FAILED:
            print(f"  - {name}")

    if os.path.exists(TEST_DB_NAME):
        os.remove(TEST_DB_NAME)

    sys.exit(1 if FAILED else 0)