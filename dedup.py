# в этом файле хранятся функции инструменты, в дальнейшем используемые test_dedup.py, это нужно чтобы банально не нагромождать их в main.py
import hashlib
import json
import logging
import os
import threading
import uuid
from pathlib import Path

import numpy as np
import config

logger = logging.getLogger("dedup")

CACHE_DIR = Path(__file__).parent / ".embeddings_cache"
CACHE_FILE = CACHE_DIR / "cache.json"

# Потокобезопасный лок для предотвращения гонок внутри одного процесса
_CACHE_LOCK = threading.Lock()

# Модель грузится лениво (только при первом реальном вызове text_to_vector),
# чтобы просто импортировать dedup.py (например, в тестах на цельность
# косинусного сходства) не тянуло за собой загрузку модели в память.
_model = None

# In-memory кэш эмбеддингов, подгружается с диска при первом обращении.
_cache: dict | None = None


def _get_model():
    """
    Ленивая инициализация модели эмбеддингов.
    Используем fastembed (ONNX Runtime) вместо sentence-transformers —
    та тянет за собой torch, а torch на PyPI по умолчанию тащит ещё и
    CUDA-библиотеки для GPU (гигабайты веса), которые на CPU-only
    машине не нужны и только рвут скачивание на нестабильной сети.

    Модель sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2:
    384-мерные векторы (совпадает с VECTOR_DIM), поддерживает русский
    язык (мультиязычная, ~50 языков), работает полностью локально
    после первого скачивания весов.
    """
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        logger.info("Загружаю модель эмбеддингов paraphrase-multilingual-MiniLM-L12-v2...")
        _model = TextEmbedding(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        logger.info("Модель эмбеддингов загружена.")
    return _model


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Файл кэша эмбеддингов поврежден ({e}), сбрасываю кэш...")
            try:
                corrupted_bak = CACHE_DIR / "cache_corrupted.bak"
                CACHE_FILE.replace(corrupted_bak)
            except Exception:
                pass
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    """
    Безопасное атомарное сохранение кэша на диск.
    Использует уникальный временный файл с PID и UUID,
    чтобы исключить состояние гонки (race condition) между
    фоновым пайплайном сбора и FastAPI API сервисом.
    """
    tmp_file = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        disk_data = _load_cache()
        merged = {**disk_data, **cache}

        tmp_file = CACHE_DIR / f"cache_{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(merged, f)

        tmp_file.replace(CACHE_FILE)
    except Exception as e:
        logger.warning(f"Не удалось сохранить кэш эмбеддингов: {e}")
        if tmp_file and tmp_file.exists():
            try:
                tmp_file.unlink()
            except Exception:
                pass


def text_to_vector(text: str) -> np.ndarray:
    """
    Реальный эмбеддинг текста через fastembed (замена
    прежней хэш-заглушки, Sprint 3).

    Результат кэшируется на диск по sha256-хэшу текста — если статья
    уже встречалась (тот же текст), эмбеддинг не пересчитывается заново,
    а берётся из кэша. Это экономит время и не грузит модель на CPU
    повторно для одинаковых текстов.
    """
    global _cache
    with _CACHE_LOCK:
        if _cache is None:
            _cache = _load_cache()

    key = hashlib.sha256(text.encode("utf-8")).hexdigest()

    with _CACHE_LOCK:
        if key in _cache:
            return np.array(_cache[key], dtype=np.float32)

    model = _get_model()
    vector = next(model.embed([text]))

    with _CACHE_LOCK:
        _cache[key] = vector.tolist()
        _save_cache(_cache)

    return vector


def batch_texts_to_vectors(texts: list[str]) -> list[np.ndarray]:
    """
    Высокопроизводительная пакетная векторизация списка текстов:
    - Проверяет кэш в памяти.
    - Для отсутствующих текстов выполняет model.embed(..., batch_size=64) в ОДИН проход.
    - Сохраняет кэш на диск ОДИН раз за весь пакет, а не на каждом элементе.
    """
    if not texts:
        return []

    global _cache
    with _CACHE_LOCK:
        if _cache is None:
            _cache = _load_cache()

    keys = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
    results: list[np.ndarray | None] = [None] * len(texts)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []

    with _CACHE_LOCK:
        for idx, (t, k) in enumerate(zip(texts, keys)):
            if k in _cache:
                results[idx] = np.array(_cache[k], dtype=np.float32)
            else:
                uncached_indices.append(idx)
                uncached_texts.append(t)

    if uncached_texts:
        model = _get_model()
        vectors_gen = model.embed(uncached_texts, batch_size=64)
        new_entries: dict[str, list[float]] = {}

        for idx, vec in zip(uncached_indices, vectors_gen):
            vec_f32 = np.array(vec, dtype=np.float32)
            results[idx] = vec_f32
            new_entries[keys[idx]] = vec_f32.tolist()

        with _CACHE_LOCK:
            _cache.update(new_entries)
            _save_cache(_cache)

    dim = config.VECTOR_DIM
    return [r if r is not None else np.zeros(dim, dtype=np.float32) for r in results]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def is_duplicate(new_vector: np.ndarray, memory_vectors: list[np.ndarray]) -> bool:
    """Сравнивает new_vector со всеми векторами, накопленными в памяти."""
    for vec in memory_vectors:
        if cosine_similarity(new_vector, vec) >= config.DUPLICATE_THRESHOLD:
            return True
    return False
