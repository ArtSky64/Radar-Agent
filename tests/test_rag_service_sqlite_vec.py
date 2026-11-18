import pytest
import config
import database
import dedup
import rag_service

def test_rag_service_sqlite_vec_indexing_and_search(monkeypatch):
    """Проверяет сквозную индексацию и KNN векторный поиск через sqlite-vec."""
    database.init_db()

    # Заменяем fastembed на детерминированные векторы
    def mock_batch_vectors(texts):
        res = []
        for t in texts:
            if "модель" in t.lower():
                res.append([1.0] + [0.0] * (config.VECTOR_DIM - 1))
            elif "датасет" in t.lower():
                res.append([0.0, 1.0] + [0.0] * (config.VECTOR_DIM - 2))
            else:
                res.append([0.0, 0.0, 1.0] + [0.0] * (config.VECTOR_DIM - 3))
        return res

    def mock_query_vector(q):
        if "модель" in q.lower():
            return [1.0] + [0.0] * (config.VECTOR_DIM - 1)
        elif "датасет" in q.lower():
            return [0.0, 1.0] + [0.0] * (config.VECTOR_DIM - 2)
        return [0.0, 0.0, 1.0] + [0.0] * (config.VECTOR_DIM - 3)

    monkeypatch.setattr(dedup, "batch_texts_to_vectors", mock_batch_vectors)
    monkeypatch.setattr(dedup, "text_to_vector", mock_query_vector)

    # Заполняем тестовые карточки
    mock_cards = [
        {
            "id": "test_m1",
            "title": "LLaMA 3 Model",
            "category": "модель",
            "summary": "Большая языковая модель для текста",
            "url": "https://huggingface.co/meta-llama/llama-3",
            "tags": ["nlp", "модель"],
            "metrics": {},
            "details": {},
            "added_at": "",
        },
        {
            "id": "test_d1",
            "title": "Medical Imaging Dataset",
            "category": "датасет",
            "summary": "Медицинский датасет снимков МРТ",
            "url": "https://kaggle.com/datasets/medical-mri",
            "tags": ["health", "датасет"],
            "metrics": {},
            "details": {},
            "added_at": "",
        },
    ]

    monkeypatch.setattr(rag_service, "_load_all_cards_from_db", lambda: mock_cards)

    indexed_count = rag_service.build_index(force=True)
    assert indexed_count == 2

    # Проверяем, что в SQLite vec_cards и rag_cards созданы записи
    with database.get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM vec_cards").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM rag_cards").fetchone()[0] == 2

    # Поиск по запросу "модель"
    results_m = rag_service.search_cards("лучшая модель", top_k=5)
    assert len(results_m) >= 1
    assert results_m[0]["card"]["id"] == "test_m1"
    assert results_m[0]["score"] == pytest.approx(1.0, abs=1e-3)

    # Поиск по запросу "датасет"
    results_d = rag_service.search_cards("медицинский датасет", top_k=5)
    assert len(results_d) >= 1
    assert results_d[0]["card"]["id"] == "test_d1"
    assert results_d[0]["score"] == pytest.approx(1.0, abs=1e-3)

    # Фильтр по категории
    filtered = rag_service.search_cards("модель", category="датасет", top_k=5)
    assert len(filtered) == 0  # нет моделей в категории датасет с высоким сходством

    # Проверка статистики
    stats = rag_service.get_catalog_stats()
    assert stats["всего"] == 2
    assert stats["модели"] == 1
    assert stats["датасеты"] == 1
