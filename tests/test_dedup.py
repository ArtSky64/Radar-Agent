import math
import random
import time
import pytest
import config
import database
from dedup import cosine_similarity, is_duplicate, text_to_vector

def test_identical_vectors():
    """100% дубликат: косинусное сходство идентичных векторов должно быть равно 1.0"""
    vec1 = [1.0, 2.0, 3.0]
    vec2 = [1.0, 2.0, 3.0]
    
    # Используем pytest.approx, так как операции с плавающей точкой 
    # могут выдать 0.9999999999999998 вместо 1.0
    assert cosine_similarity(vec1, vec2) == pytest.approx(1.0)

def test_orthogonal_vectors():
    """Ортогональные векторы (совершенно разные статьи): сходство должно быть 0.0"""
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [0.0, 1.0, 0.0]
    
    assert cosine_similarity(vec1, vec2) == pytest.approx(0.0)

def test_zero_vector():
    """
    Граничный случай: пустой текст дал нулевой вектор.
    Проверяем, что нет ошибки деления на ноль.
    """
    vec_zero = [0.0, 0.0, 0.0]
    vec_normal = [1.0, 1.0, 1.0]
    
    assert cosine_similarity(vec_zero, vec_normal) == 0.0

def test_is_duplicate_boundaries():
    """Пограничные значения порога сходства (по умолчанию 0.92)"""
    # Гарантируем, что порог в конфиге стоит 0.92 для этого теста
    config.DUPLICATE_THRESHOLD = 0.92
    
    base_vector = [1.0, 0.0]
    memory_vectors = [base_vector]
    
    # Вектор со сходством 0.93 (Выше порога -> это дубликат)
    duplicate_similarity = 0.93
    duplicate_vec = [
        duplicate_similarity,
        math.sqrt(1 - duplicate_similarity**2)
    ] 
    assert is_duplicate(duplicate_vec, memory_vectors) is True
    
    # Вектор со сходством 0.91 (Ниже порога -> это УНИКАЛЬНАЯ статья)
    unique_similarity = 0.91
    unique_vec = [
        unique_similarity,
        math.sqrt(1 - unique_similarity**2)
    ]
    assert is_duplicate(unique_vec, memory_vectors) is False

def test_is_duplicate_benchmark():
    """Замер производительности линейного перебора is_duplicate на 500 векторах."""
    rng = random.Random(42)
    memory_vectors = [[rng.random() for _ in range(config.VECTOR_DIM)] for _ in range(500)]
    query_vector = [rng.random() for _ in range(config.VECTOR_DIM)]

    start = time.perf_counter()
    is_duplicate(query_vector, memory_vectors)
    elapsed = time.perf_counter() - start

    print(f"\nis_duplicate на 500 векторах (dim={config.VECTOR_DIM}): {elapsed * 1000:.2f} мс")
    assert elapsed < 1.0

def test_memory_vectors_append_logic():
    """
    Проверка отсечения дубликатов внутри одного батча (без БД).
    Имитируем работу главного цикла main.py
    """
    config.DUPLICATE_THRESHOLD = 0.92
    memory_vectors = []
    
    new_article_vector = [1.0, 0.0, 0.0]
    
    # Первая статья уникальна, добавляем её вектор в кэш
    assert is_duplicate(new_article_vector, memory_vectors) is False
    memory_vectors.append(new_article_vector)
    
    # Вторая статья с точно таким же вектором (спарсили то же самое)
    # Алгоритм должен увидеть её в memory_vectors и сказать, что это дубликат
    assert is_duplicate(new_article_vector, memory_vectors) is True

def test_sqlite_vec_db_dedup():
    """Проверка нативного поиска дубликатов через sqlite-vec в базе SQLite."""
    database.init_db()
    vec1 = [0.01] * config.VECTOR_DIM
    vec2 = [0.99] * config.VECTOR_DIM
    database.save_vector(vec1)
    try:
        # Тот же вектор должен определяться как дубликат
        assert database.is_vector_duplicate_db(vec1, threshold=0.59) is True
        # Ортогональный / далекий вектор не должен быть дубликатом
        far_vec = [-0.01] * config.VECTOR_DIM
        assert database.is_vector_duplicate_db(far_vec, threshold=0.59) is False
    finally:
        with database.get_connection() as conn:
            conn.execute("DELETE FROM vec_vectors")
            conn.execute("DELETE FROM vectors")

def test_text_to_vector_deterministic(monkeypatch):
    """Один и тот же текст должен давать один и тот же вектор."""
    monkeypatch.setattr("dedup._get_model", lambda: type("Dummy", (), {"embed": lambda self, t: iter([[0.1] * config.VECTOR_DIM])})())
    v1 = text_to_vector("одна и та же статья про RAG")
    v2 = text_to_vector("одна и та же статья про RAG")
    assert v1 == v2

def test_empty_text_vector(monkeypatch):
    """Пустой текст статьи не должен приводить к падению."""
    monkeypatch.setattr("dedup._get_model", lambda: type("Dummy", (), {"embed": lambda self, t: iter([[0.0] * config.VECTOR_DIM])})())
    vec_empty = text_to_vector("")
    rng = random.Random(1)
    memory_vectors = [[rng.random() for _ in range(config.VECTOR_DIM)]]

    result = is_duplicate(vec_empty, memory_vectors)
    assert isinstance(result, bool)