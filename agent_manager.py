import logging
import threading
import time

import httpx2
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
)

import config

logger = logging.getLogger("agent_manager")

import threading
_RATE_LIMIT_LOCK=threading.Lock()
_last_call_ts = 0.0
_MIN_INTERVAL_SEC = 1.05
def _throttle() -> None:
    global _last_call_ts
    with _RATE_LIMIT_LOCK:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SEC - (now - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.monotonic()


class ArticleAnalysis(BaseModel):
    """Структурированный результат анализа статьи."""
    summary: str = Field(description="Краткое summary статьи, 2-4 предложения")
    tags: list[str] = Field(description="3-6 релевантных тегов, напр. ['LLM', 'RAG', 'Fine-tuning']")


SYSTEM_PROMPT = """
Ты — эксперт по машинному обучению и NLP. Тебе дают заголовок и текст статьи.
Твоя задача:
1. Написать краткое summary (2-4 предложения).
2. Сгенерировать 3-6 релевантных тегов по теме статьи (технологии, методы, область применения).
Отвечай строго в структурированном виде, без лишнего текста.
"""

def get_model() -> OpenAIChatModel:
    if not config.VLLM_BASE_URL:
        raise RuntimeError(
            "VLLM_BASE_URL не найден. Создай файл .env на основе .env.example "
            "и укажи там адрес своего vLLM (например, http://127.0.0.1:2233/v1)."
        )
    http_client = httpx2.AsyncClient(timeout=180.0)
    return OpenAIChatModel(
        config.VLLM_MODEL_NAME,
        provider=OpenAIProvider(
            base_url=config.VLLM_BASE_URL,
            api_key=config.VLLM_API_KEY,
            http_client=http_client,
        ),
    )


def _get_article_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=ArticleAnalysis,
        system_prompt=SYSTEM_PROMPT,
    )


class AnalysisError(Exception):
    """Кидается, если агент не смог получить валидный структурированный ответ."""


def _is_retryable_error(exception: BaseException) -> bool:
    """
    True для ошибок, на которые имеет смысл ретраить с backoff:
    - 429 (rate limit) от Mistral;
    - сетевые/таймаут-ошибки httpx (ReadTimeout, ConnectTimeout, PoolTimeout,
      ConnectError и т.п.) — у них str(exception) часто ПУСТОЙ, поэтому раньше
      они не матчились ни под одно условие и падали без retry с пустым текстом
      ошибки в логах.
    """
    status_code = getattr(exception, "status_code", None)
    if status_code == 429:
        return True
    if isinstance(exception, (httpx2.TimeoutException, httpx2.TransportError)):
        return True
    text = str(exception).lower()
    return "429" in text or "rate limit" in text


# Оставлено для обратной совместимости (использовалось в старых импортах).
_is_rate_limit_error = _is_retryable_error


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(7),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_agent(prompt: str):
    """Внутренний вызов агента с retry+backoff только на 429 (rate limit)."""
    _throttle()
    return _get_article_agent().run_sync(prompt)


class LeaderboardAnalysis(BaseModel):
    """Структурированный результат инкрементального анализа лидерборда Arena.ai."""
    summary: str = Field(description="Общий обзор текущего состояния лидерборда, 3-5 предложений")
    trends: list[str] = Field(
        description="3-6 ключевых изменений по сравнению с предыдущим анализом: "
                    "новые лидеры, кто вырос/упал в рейтинге, какие тенденции прошлого "
                    "анализа подтвердились или сломались"
    )


LEADERBOARD_SYSTEM_PROMPT = """
Ты — аналитик рынка LLM и генеративных ИИ-моделей. Тебе дают:
1. Текущий снимок лидерборда Arena.ai (топ-5 моделей по категориям с рейтингом Elo).
2. Предыдущий снимок лидерборда (может отсутствовать, если это самый первый анализ).
3. Предыдущий текстовый анализ, который ты сам (или предыдущая версия тебя) написал
   в прошлый раз (может отсутствовать, если это первый анализ).

Твоя задача — построить анализ С УЧЁТОМ ИСТОРИИ, а не пересказать текущие цифры с нуля:
объясни, что изменилось со времени предыдущего анализа (новые лидеры, кто вырос или упал
в рейтинге, какие тенденции из прошлого анализа продолжились, а какие сломались).
Если предыдущего снимка и анализа нет — прямо укажи, что это первый анализ, и опиши
только текущую картину, без сравнений.

Отвечай строго в структурированном виде, без лишнего текста и без markdown-заголовков.
"""


def _get_leaderboard_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=LeaderboardAnalysis,
        system_prompt=LEADERBOARD_SYSTEM_PROMPT,
    )


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(7),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_leaderboard_agent(prompt: str):
    _throttle()
    return _get_leaderboard_agent().run_sync(prompt)


def _format_snapshot(snapshot: dict | None) -> str:
    """Превращает снимок лидерборда в компактный текст для промпта."""
    if not snapshot:
        return "(нет данных — снимок отсутствует)"
    lines = [f"Снимок от {snapshot['fetched_at']}:"]
    for category, models in snapshot["categories"].items():
        models_str = ", ".join(f"{m['name']} ({m['rating']})" for m in models)
        lines.append(f"  - {category}: {models_str}")
    return "\n".join(lines)


def analyze_leaderboard(
    current_snapshot: dict,
    previous_snapshot: dict | None,
    previous_analysis: str | None,
) -> LeaderboardAnalysis:
    """
    Строит НОВЫЙ анализ лидерборда на основе текущего снимка + предыдущего снимка +
    предыдущего текстового анализа. Это инкрементальный анализ: агент видит, что он
    писал в прошлый раз, и продолжает мысль, а не начинает с чистого листа.
    """
    prompt = (
        "=== ТЕКУЩИЙ СНИМОК ===\n"
        f"{_format_snapshot(current_snapshot)}\n\n"
        "=== ПРЕДЫДУЩИЙ СНИМОК ===\n"
        f"{_format_snapshot(previous_snapshot)}\n\n"
        "=== ПРЕДЫДУЩИЙ АНАЛИЗ (текст, написанный тобой ранее) ===\n"
        f"{previous_analysis or '(отсутствует — это первый анализ)'}\n"
    )
    try:
        result = _call_leaderboard_agent(prompt)
        return result.output
    except Exception as e:
        logger.error(f"Ошибка анализа лидерборда: {e!r}")
        raise AnalysisError(f"Не удалось проанализировать лидерборд: {e!r}") from e


class TrendingModelSummary(BaseModel):
    """Короткое саммари для карточки трендовой модели HF."""
    summary: str = Field(description="1-2 предложения о том, что это за модель и для чего она нужна")


TRENDING_MODEL_SYSTEM_PROMPT = """
Ты — эксперт по машинному обучению. Тебе дают название модели с Hugging Face,
её теги (архитектура, задача, библиотека и т.п.) и выдержку из её карточки (README).
Твоя задача — кратко (1-2 предложения) объяснить на русском языке, что это
за модель и для чего она обычно используется. Выделяй главное.
Отвечай строго по существу, без лишнего текста.
"""


def _get_trending_model_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=TrendingModelSummary,
        system_prompt=TRENDING_MODEL_SYSTEM_PROMPT,
    )


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(7),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_trending_model_agent(prompt: str):
    _throttle()
    return _get_trending_model_agent().run_sync(prompt)


def summarize_trending_model(name: str, tags: list[str], card_description: str = "") -> str:
    """
    Генерирует короткое саммари для трендовой модели HF по названию, тегам и карточке.
    """
    tags_str = ", ".join(tags) if tags else "(теги отсутствуют)"
    prompt = f"Название модели: {name}\nТеги: {tags_str}\n\nОписание карточки:\n{card_description[:2500]}"
    try:
        result = _call_trending_model_agent(prompt)
        return result.output.summary
    except Exception as e:
        logger.error(f"Ошибка саммари трендовой модели '{name}': {e!r}")
        raise AnalysisError(f"Не удалось получить саммари для модели '{name}': {e!r}") from e


def analyze_article(title: str, text: str) -> ArticleAnalysis:
    """
    Синхронная обертка над агентом.
    Принимает title+text статьи, возвращает провалидированный ArticleAnalysis.
    При 429 (rate limit) автоматически повторяет запрос с экспоненциальной
    задержкой (до 5 попыток). Любая другая ошибка (невалидный JSON, сеть) —
    сразу оборачивается в AnalysisError, main.py ловит и пропускает статью.
    """
    prompt = f"Заголовок: {title}\n\nТекст статьи:\n{text}"
    try:
        result = _call_agent(prompt)
        return result.output
    except Exception as e:
        logger.error(f"Ошибка анализа статьи '{title}': {e!r}")
        raise AnalysisError(f"Не удалось проанализировать статью '{title}': {e!r}") from e