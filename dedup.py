# в этом файле хранятся функции инструменты, в дальнейшем используемые test_dedup.py, это нужно чтобы банально не нагромождать их в main.py
import atexit
import hashlib
import json
import logging
import math
import os
import struct
import threading
import uuid
from pathlib import Path
from typing import Any

import config
import database

logger = logging.getLogger("dedup")

def serialize_float32(vector: list[float]) -> bytes:
    """Сериализует вектор в байты float32 для передачи в sqlite-vec."""
    return database.serialize_float32(vector)

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
_unsaved_updates_count: int = 0
_CACHE_FLUSH_INTERVAL: int = 30


def flush_embeddings_cache() -> None:
    """Сбрасывает накопленный кэш эмбеддингов на диск."""
    global _unsaved_updates_count, _cache
    with _CACHE_LOCK:
        if _cache is not None and _unsaved_updates_count > 0:
            _save_cache(_cache)
            _unsaved_updates_count = 0


atexit.register(flush_embeddings_cache)


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


def text_to_vector(text: str) -> list[float]:
    """
    Реальный эмбеддинг текста через fastembed.
    Возвращает список float32 размерности config.VECTOR_DIM (без numpy).

    Результат кэшируется на диск по sha256-хэшу текста — если статья
    уже встречалась (тот же текст), эмбеддинг не пересчитывается заново,
    а берётся из кэша.
    """
    global _cache
    with _CACHE_LOCK:
        if _cache is None:
            _cache = _load_cache()

    key = hashlib.sha256(text.encode("utf-8")).hexdigest()

    with _CACHE_LOCK:
        if key in _cache:
            return [float(x) for x in _cache[key]]

    model = _get_model()
    raw_vector = next(model.embed([text]))
    vec_list = raw_vector.tolist() if hasattr(raw_vector, "tolist") else list(raw_vector)
    vec_list = [float(x) for x in vec_list]

    with _CACHE_LOCK:
        global _unsaved_updates_count
        _cache[key] = vec_list
        _unsaved_updates_count += 1
        if _unsaved_updates_count >= _CACHE_FLUSH_INTERVAL:
            _save_cache(_cache)
            _unsaved_updates_count = 0

    return vec_list


def batch_texts_to_vectors(texts: list[str]) -> list[list[float]]:
    """
    Высокопроизводительная пакетная векторизация списка текстов:
    - Проверяет кэш в памяти.
    - Для отсутствующих текстов выполняет model.embed(..., batch_size=64) в ОДИН проход.
    - Сохраняет кэш на диск ОДИН раз за весь пакет, а не на каждом элементе.
    Возвращает список векторов list[float] (без numpy).
    """
    if not texts:
        return []

    global _cache
    with _CACHE_LOCK:
        if _cache is None:
            _cache = _load_cache()

    keys = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
    results: list[list[float] | None] = [None] * len(texts)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []

    with _CACHE_LOCK:
        for idx, (t, k) in enumerate(zip(texts, keys)):
            if k in _cache:
                results[idx] = [float(x) for x in _cache[k]]
            else:
                uncached_indices.append(idx)
                uncached_texts.append(t)

    if uncached_texts:
        model = _get_model()
        vectors_gen = model.embed(uncached_texts, batch_size=64)
        new_entries: dict[str, list[float]] = {}

        for idx, vec in zip(uncached_indices, vectors_gen):
            vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
            vec_list = [float(x) for x in vec_list]
            results[idx] = vec_list
            new_entries[keys[idx]] = vec_list

        with _CACHE_LOCK:
            _cache.update(new_entries)
            _save_cache(_cache)

    dim = config.VECTOR_DIM
    return [r if r is not None else [0.0] * dim for r in results]


def cosine_similarity(a: list[float] | Any, b: list[float] | Any) -> float:
    """Вычисляет косинусное сходство между двумя векторами (чистый Python, без numpy)."""
    if hasattr(a, "tolist"):
        a = a.tolist()
    if hasattr(b, "tolist"):
        b = b.tolist()
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    denom = norm_a * norm_b
    if denom == 0:
        return 0.0
    return float(dot / denom)


def is_duplicate(new_vector: list[float] | Any, memory_vectors: list[list[float] | Any] | None = None) -> bool:
    """
    Сравнивает new_vector с векторами в памяти,
    либо напрямую проверяет через sqlite-vec в базе данных.
    """
    if memory_vectors:
        for vec in memory_vectors:
            if cosine_similarity(new_vector, vec) >= config.DUPLICATE_THRESHOLD:
                return True
        return False
    return database.is_vector_duplicate_db(list(new_vector))
