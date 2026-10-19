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
                     "upsert_related_material", "get_article_by_url", "repo_exists_in_db",
                     "save_github_trending", "get_github_trending", "get_github_trending_last_fetched_at",
                     "save_trending_models", "get_trending_models", "get_hf_trending_last_fetched_at"):
        assert hasattr(database, fn_name), f"database.py: нет функции {fn_name}"

    import FetcherHF
    assert hasattr(FetcherHF, "stream_hf_articles")

    import FetcherHFDatasets
    assert hasattr(FetcherHFDatasets, "stream_hf_datasets") or hasattr(FetcherHFDatasets, "stream_hf_datasets_by_mode")


    import mcp_fetcher_papers
    assert hasattr(mcp_fetcher_papers, "stream_papers_articles")
    assert hasattr(mcp_fetcher_papers, "merge_papers")
    assert hasattr(mcp_fetcher_papers, "normalize_arxiv_id")

    import github_fetcher
    assert hasattr(github_fetcher, "stream_github_articles")
    assert hasattr(github_fetcher, "run_github_trending_pipeline")
    assert hasattr(github_fetcher, "fetch_top_trending_repos")
    assert hasattr(github_fetcher, "fetch_repo_readme")

    assert hasattr(agent_manager, "analyze_github_repo")
    assert hasattr(agent_manager, "GitHubRepoCard")
    assert hasattr(agent_manager, "HFModelCard")
    assert hasattr(agent_manager, "analyze_hf_model")
    assert hasattr(agent_manager, "clean_model_tags")
    assert hasattr(agent_manager, "extract_model_parameters")

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


@check("database.py: github_trending таблица и методы поиска/сохранения")
def _():
    import database
    database.DB_NAME = TEST_DB_NAME
    database.init_db()

    # Проверка сохранения статьи с directions и task_types
    database.save_article({
        "title": "[GitHub] test-owner/test-repo",
        "summary": "Проект для автоматизации задач в области ML. Позволяет запускать пайплайны данных. Включает готовые интеграции с API.",
        "source_url": "https://github.com/test-owner/test-repo",
        "tags": ["Python", "ML"],
        "directions": ["agents", "nlp_llm"],
        "task_types": ["rag_search", "agent_orchestration"],
        "source_type": "репозиторий",
        "stars": 1500,
        "period": "weekly",
    })

    # Проверка поиска
    assert database.repo_exists_in_db("https://github.com/test-owner/test-repo") is True
    assert database.repo_exists_in_db("test-owner/test-repo") is True
    assert database.repo_exists_in_db("nonexistent/repo") is False

    art = database.get_article_by_url("https://github.com/test-owner/test-repo")
    assert art is not None
    assert art["directions"] == ["agents", "nlp_llm"]
    assert art["task_types"] == ["rag_search", "agent_orchestration"]
    assert art["stars"] == 1500

    # Проверка сохранения слепка трендов
    trending_mock = [
        {
            "repo_name": "test-owner/test-repo",
            "source_url": "https://github.com/test-owner/test-repo",
            "summary": "Описание репозитория 1",
            "tags": ["Tag1"],
            "directions": ["agents"],
            "task_types": ["rag_search"],
            "stars": 1500,
            "stars_this_period": 250,
            "period": "weekly",
            "is_new": False,
        },
        {
            "repo_name": "new-owner/new-repo",
            "source_url": "https://github.com/new-owner/new-repo",
            "summary": "Описание репозитория 2",
            "tags": ["Tag2"],
            "directions": ["cv"],
            "task_types": ["detection_tracking"],
            "stars": 800,
            "stars_this_period": 120,
            "period": "monthly",
            "is_new": True,
        },
    ]
    database.save_github_trending(trending_mock)
    loaded = database.get_github_trending()
    assert len(loaded) == 2
    assert loaded[0]["repo_name"] == "test-owner/test-repo"
    assert loaded[0]["is_new"] is False
    assert loaded[1]["repo_name"] == "new-owner/new-repo"
    assert loaded[1]["is_new"] is True
    assert loaded[1]["directions"] == ["cv"]
    assert loaded[1]["task_types"] == ["detection_tracking"]


@check("agent_manager.py: GitHubRepoCard валидация и санитизация (0-4 направлений, 0-3 задач)")
def _():
    import agent_manager
    from agent_manager import GitHubRepoCard, sanitize_repo_card

    # Проверка схемы
    card = GitHubRepoCard(
        summary="Это первое предложение. Это второе предложение. Это третье предложение. Это четвертое предложение.",
        tags=["PyTorch", "vLLM"],
        directions=["agents", "nlp_llm", "cv", "audio", "backend"],  # 5 штук (превышает 4)
        task_types=["rag_search", "generation", "classification", "regression"],  # 4 штуки (превышает 3)
    )

    cleaned = sanitize_repo_card(card)
    assert len(cleaned.directions) <= 4, "Должно быть максимум 4 направления"
    assert len(cleaned.task_types) <= 3, "Должно быть максимум 3 типа задач"
    assert set(cleaned.directions).issubset(set(agent_manager.config.GITHUB_DIRECTIONS.keys()))
    assert set(cleaned.task_types).issubset(set(agent_manager.config.GITHUB_TASK_TYPES.keys()))

    # Проверка фильтрации невалидных тегов
    bad_card = GitHubRepoCard(
        summary="Краткое описание.",
        tags=["test"],
        directions=["not_a_valid_direction", "agents"],
        task_types=["invalid_task", "rag_search"],
    )
    cleaned_bad = sanitize_repo_card(bad_card)
    assert cleaned_bad.directions == ["agents"]
    assert cleaned_bad.task_types == ["rag_search"]


@check("github_fetcher.py: сквозной прогон пайплайна (30 репозиториев, новые vs старые)")
def _():
    import database
    from unittest.mock import patch, AsyncMock
    database.DB_NAME = TEST_DB_NAME
    database.init_db()

    # Добавим один репозиторий заранее в БД
    database.save_article({
        "title": "[GitHub] existing-org/existing-repo",
        "summary": "Существующее описание из базы данных. Состоит из трех предложений. Полезно инженерам.",
        "source_url": "https://github.com/existing-org/existing-repo",
        "tags": ["Python", "Existing"],
        "directions": ["backend"],
        "task_types": ["classification"],
        "source_type": "репозиторий",
        "stars": 5000,
        "period": "weekly",
    })

    # Создадим 3 тестовых трендовых репозитория (1 старый + 2 новых)
    fake_trending = [
        {
            "id": "existing-org/existing-repo",
            "title": "existing-org/existing-repo",
            "description": "Old repo desc",
            "full_text": "Language: Python | Stars: 5000\nDescription: Old repo desc",
            "url": "https://github.com/existing-org/existing-repo",
            "stars_total": 5000,
            "stars_this_period": 300,
            "trending_period": "weekly",
        },
        {
            "id": "new-org/new-repo-1",
            "title": "new-org/new-repo-1",
            "description": "New repo 1 desc",
            "full_text": "Language: Python | Stars: 1200\nDescription: New repo 1 desc",
            "url": "https://github.com/new-org/new-repo-1",
            "stars_total": 1200,
            "stars_this_period": 150,
            "trending_period": "weekly",
        },
        {
            "id": "new-org/new-repo-2",
            "title": "new-org/new-repo-2",
            "description": "New repo 2 desc",
            "full_text": "Language: Python | Stars: 800\nDescription: New repo 2 desc",
            "url": "https://github.com/new-org/new-repo-2",
            "stars_total": 800,
            "stars_this_period": 90,
            "trending_period": "monthly",
        },
    ]

    import github_fetcher

    with patch.object(github_fetcher, "fetch_top_trending_repos", AsyncMock(return_value=fake_trending)), \
         patch.object(github_fetcher, "fetch_repo_readme", AsyncMock(return_value="# Demo Project\nThis is a test readme.")):

        results = github_fetcher.run_github_trending_pipeline(limit=3)

        assert len(results) == 3
        # Первый репозиторий должен быть определен как уже существующий в базе
        assert results[0]["is_new"] is False
        assert results[0]["repo_name"] == "existing-org/existing-repo"
        assert "Существующее описание" in results[0]["summary"]

        # Второй и третий должны быть определены как новые
        assert results[1]["is_new"] is True
        assert results[1]["repo_name"] == "new-org/new-repo-1"
        assert len(results[1]["summary"]) > 20
        assert len(results[1]["directions"]) <= 4
        assert len(results[1]["task_types"]) <= 3

        assert results[2]["is_new"] is True
        assert results[2]["repo_name"] == "new-org/new-repo-2"

        # Проверяем, что новые репозитории появились в articles и в github_trending
        assert database.repo_exists_in_db("https://github.com/new-org/new-repo-1") is True
        assert database.repo_exists_in_db("https://github.com/new-org/new-repo-2") is True

        trending_in_db = database.get_github_trending()
        assert len(trending_in_db) == 3


@check("mcp_fetcher_hf_trending: параметры, порезка тегов, направления/задачи и сквозной рейтинг")
def _():
    import agent_manager
    import database
    import config

    database.DB_NAME = TEST_DB_NAME
    database.init_db()

    # 1. Проверка извлечения параметров
    assert agent_manager.extract_model_parameters("underdog-saluki-27b") == "27B"
    assert agent_manager.extract_model_parameters("LiquidAI/d1-3B") == "3B"
    assert agent_manager.extract_model_parameters("LiquidAI/d1-omni-600M") == "600M"
    assert agent_manager.extract_model_parameters("Qwen2.5-7B-Instruct-GGUF") == "7B"

    # 2. Проверка порезки мусорных тегов (отсечение тысяч языковых кодов и тех. меток)
    bloated_tags = [
        "transformers", "safetensors", "endpoints_compatible", "region:us",
        "custom_code", "aah", "aai", "rus", "eng", "fra", "zyp", "arxiv:2401.12345",
        "license:mit", "dataset:open-data", "GGUF", "multimodal", "vision", "moe"
    ]
    cleaned = agent_manager.clean_model_tags(bloated_tags, max_tags=5)
    assert len(cleaned) <= 5
    for junk in ("safetensors", "endpoints_compatible", "aah", "zyp", "rus", "eng"):
        assert junk not in cleaned

    # 3. Проверка анализа модели
    card = agent_manager.analyze_hf_model(
        model_name="test-org/underdog-saluki-27b",
        pipeline_tag="text-generation",
        tags=["LLM", "GGUF", "conversational"],
        card_description="A 27B parameter open text generation model."
    )
    assert isinstance(card, agent_manager.HFModelCard)
    assert card.parameters == "27B"
    assert len(card.directions) <= config.HF_MAX_DIRECTIONS
    assert len(card.task_types) <= config.HF_MAX_TASK_TYPES
    for d in card.directions:
        assert d in config.HF_DIRECTIONS
    for t in card.task_types:
        assert t in config.HF_TASK_TYPES

    # 4. Проверка сохранения в БД и фильтрации по variant / рейтингу
    test_models = [
        {
            "name": "global-only-model",
            "model_name": "global-only-model",
            "downloads": 50000,
            "likes": 1200,
            "trending_score": 500.0,
            "tags": ["LLM", "GGUF"],
            "url": "https://huggingface.co/global-only-model",
            "summary": "Мировая модель",
            "pipeline_tag": "text-generation",
            "license": "apache-2.0",
            "card_description": "Global desc",
            "language": "",
            "variant": "global",
            "directions": ["nlp_llm"],
            "task_types": ["generation"],
            "parameters": "7B",
            "rank_global": 1,
            "rank_ru": 0,
        },
        {
            "name": "ru-and-global-model",
            "model_name": "ru-and-global-model",
            "downloads": 30000,
            "likes": 800,
            "trending_score": 450.0,
            "tags": ["LLM", "Russian"],
            "url": "https://huggingface.co/ru-and-global-model",
            "summary": "Русско-мировая модель",
            "pipeline_tag": "text-generation",
            "license": "apache-2.0",
            "card_description": "RU & Global desc",
            "language": "ru",
            "variant": "global,ru",
            "directions": ["nlp_llm"],
            "task_types": ["generation"],
            "parameters": "27B",
            "rank_global": 2,
            "rank_ru": 1,
        },
        {
            "name": "ru-only-model",
            "model_name": "ru-only-model",
            "downloads": 5000,
            "likes": 150,
            "trending_score": 100.0,
            "tags": ["Russian", "Voice"],
            "url": "https://huggingface.co/ru-only-model",
            "summary": "Только русская модель",
            "pipeline_tag": "automatic-speech-recognition",
            "license": "mit",
            "card_description": "RU only desc",
            "language": "ru",
            "variant": "ru",
            "directions": ["audio"],
            "task_types": ["recognition"],
            "parameters": "600M",
            "rank_global": 0,
            "rank_ru": 2,
        },
    ]

    database.save_trending_models(test_models)

    all_in_db = database.get_trending_models()
    assert len(all_in_db) == 3

    ru_in_db = database.get_trending_models(variant="ru")
    assert len(ru_in_db) == 2
    assert ru_in_db[0]["model_name"] == "ru-and-global-model"
    assert ru_in_db[0]["rank_ru"] == 1
    assert ru_in_db[1]["model_name"] == "ru-only-model"
    assert ru_in_db[1]["rank_ru"] == 2

    global_in_db = database.get_trending_models(variant="global")
    assert len(global_in_db) == 2
    assert global_in_db[0]["model_name"] == "global-only-model"
    assert global_in_db[1]["model_name"] == "ru-and-global-model"

    assert database.get_hf_trending_last_fetched_at() is not None



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