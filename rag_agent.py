"""
Модуль интеллектуального диалогового агента Radar Scout на базе PydanticAI и Qwen/Qwen3.6-27B.
Работает полностью автономно и локально через vLLM, ориентируясь по базе знаний Radar
с помощью нативных инструментов (Function Calling / Tools).
"""

import asyncio
import concurrent.futures
from dataclasses import dataclass, field
import json
import logging
import os
import re
import time
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

import config
import database
import rag_service

logger = logging.getLogger("rag_agent")

# Кэш состояния онлайн-сервера vLLM для предотвращения задержек
_VLLM_STATUS: dict[str, Any] = {"online": None, "checked_at": 0.0}


def _clean_card_title(raw_title: str) -> str:
    """Удаляет вложенные квадратные скобки [[Kaggle] Title] для корректного Markdown."""
    if not raw_title:
        return "Материал"
    clean = re.sub(r"^\[(.*?)\]\s*", r"\1: ", raw_title.strip())
    clean = clean.replace("[", "(").replace("]", ")")
    return re.sub(r"\s+", " ", clean).strip()


def _is_vllm_online() -> bool:
    """
    Быстро проверяет доступность vLLM сервера с кэшированием статуса на 15 секунд.
    Позволяет мгновенно переключаться на локальный резерв, если сервер не запущен.
    """
    now = time.monotonic()
    if _VLLM_STATUS["online"] is not None and (now - _VLLM_STATUS["checked_at"] < 15.0):
        return _VLLM_STATUS["online"]

    base_url = config.VLLM_BASE_URL or "http://192.168.10.65:8901/v1"
    models_url = f"{base_url.rstrip('/')}/models"
    try:
        with httpx.Client(timeout=0.3) as client:
            resp = client.get(models_url)
            is_ok = (resp.status_code == 200)
    except Exception:
        is_ok = False

    _VLLM_STATUS["online"] = is_ok
    _VLLM_STATUS["checked_at"] = now
    return is_ok


# --- ПРОВАЙДЕР ЛОКАЛЬНОЙ МОДЕЛИ QWEN 3.6 27B ---

def get_rag_model() -> OpenAIChatModel:
    """
    Возвращает модель OpenAI-совместимого провайдера (vLLM Qwen 3.6 27B).
    Параметры берутся из config.py / .env.
    """
    base_url = config.VLLM_BASE_URL or "http://192.168.10.65:8901/v1"
    model_name = config.VLLM_MODEL_NAME or "Qwen/Qwen3.6-27B"
    api_key = config.VLLM_API_KEY or "not-needed"

    if config.OPENAI_BASE_URL:
        base_url = config.OPENAI_BASE_URL
        model_name = config.OPENAI_MODEL_NAME or model_name
        api_key = config.OPENAI_API_KEY or api_key

    timeout_cfg = httpx.Timeout(connect=3.0, read=60.0, write=10.0, pool=10.0)
    http_client = httpx.AsyncClient(timeout=timeout_cfg)

    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            base_url=base_url,
            api_key=api_key,
            http_client=http_client,
        ),
    )


# --- КОНТЕКСТ ДИАЛОГА И ТУЛОВ ---

@dataclass
class RagAgentDeps:
    """Контекст исполнения запроса агентом: собирает вызванные карточки и параметры."""
    category: str = "all"
    limit: int = 5
    retrieved_cards: list[dict[str, Any]] = field(default_factory=list)
    search_query: str | None = None
    used_leaderboard: bool = False


RADAR_SYSTEM_PROMPT = """Ты — интеллектуальный персональный AI-ассистент сервиса AI/ML Radar Scout на базе Qwen.
Твоя база знаний охватывает:
- Предобученные модели (Hugging Face, рейтинги LMSYS Arena).
- Датасеты для обучения и валидации (Kaggle, Hugging Face Datasets).
- Репозитории с исходным кодом и инструментами (GitHub Trending).
- Исследовательские статьи и препринты (ArXiv, Papers with Code).

ТВОИ ИНСТРУМЕНТЫ (TOOLS):
1. search_radar: используй для семантического поиска по базе знаний, когда пользователь ищет модели, датасеты, код или статьи по конкретной задаче или домену (CV, NLP, Audio, медицина, табличные данные, MLOps и т.д.). Формулируй понятный поисковый запрос (например: «сегментация снимков МРТ», «распознавание речи whisper», «градиентный бустинг»).
2. get_leaderboard_data: используй, когда пользователь спрашивает про рейтинги, арену LMSYS или топовые LLM.
3. Если пользователь просто здоровается («Привет»), благодарит («Спасибо»), ведет смолл-ток («Как дела?») или спрашивает о контексте разговора («Что мы обсуждали?») — НЕ вызывай инструменты поиска, отвечай напрямую как дружелюбный эксперт.

ТРЕБОВАНИЯ К ОТВЕТУ:
- Отвечай структурированно, профессионально и живо на русском языке.
- Для КАЖДОЙ рекомендуемой карточки обязательно делай кликабельную Markdown-ссылку в формате [Название карточки](url).
- Анализируй и сравнивай найденные материалы: поясняй, чем они хороши, под какие сценарии подходят.
- Оформляй ответ в красивом GitHub Markdown: заголовки ##, жирный шрифт, списки, таблицы или блоки кода при необходимости.
"""


def _create_rag_agent() -> Agent[RagAgentDeps, str]:
    """Создает PydanticAI-агента с нативными инструментами поиска для Qwen 3.6 27B."""
    agent: Agent[RagAgentDeps, str] = Agent(
        model=get_rag_model(),
        deps_type=RagAgentDeps,
        system_prompt=RADAR_SYSTEM_PROMPT,
    )

    @agent.tool
    def search_radar(
        ctx: RunContext[RagAgentDeps],
        query: str,
        category: str = "all",
    ) -> list[dict[str, Any]]:
        """
        Семантический поиск по локальной векторной базе знаний Radar Scout.
        :param query: поисковая фраза (по теме задачи, архитектуре или домену).
        :param category: фильтр: 'all', 'модель', 'датасет', 'репозиторий', 'статья'.
        :return: список найденных карточек с метаданными.
        """
        eff_cat = category if category and category != "all" else ctx.deps.category
        results = rag_service.search_cards(
            query=query,
            category=eff_cat,
            top_k=ctx.deps.limit,
            min_score=0.15,
        )
        if not results and eff_cat != "all":
            results = rag_service.search_cards(
                query=query,
                category="all",
                top_k=ctx.deps.limit,
                min_score=0.15,
            )

        cards: list[dict[str, Any]] = []
        compact_payload: list[dict[str, Any]] = []
        for r in results:
            c = dict(r["card"])
            score_val = float(r.get("score", 0.0))
            c["similarity"] = score_val
            c["title"] = _clean_card_title(c.get("title", ""))
            cards.append(c)

            compact_payload.append({
                "title": c.get("title"),
                "category": c.get("category"),
                "url": c.get("url"),
                "summary": (c.get("summary") or "")[:350],
                "tags": c.get("tags", [])[:5],
                "similarity": round(score_val, 2),
            })

        ctx.deps.retrieved_cards = cards
        ctx.deps.search_query = query
        return compact_payload

    @agent.tool
    def get_leaderboard_data(ctx: RunContext[RagAgentDeps]) -> list[dict[str, Any]]:
        """Возвращает актуальный снимок лидерборда моделей LMSYS Arena."""
        ctx.deps.used_leaderboard = True
        try:
            snapshots = database.get_all_leaderboard_snapshots()
            return snapshots[:8] if isinstance(snapshots, list) else []
        except Exception as e:
            logger.warning(f"Ошибка получения лидерборда: {e}")
            return []

    return agent


def _safe_run_agent(agent: Agent, prompt: str, **kwargs) -> Any:
    """Безопасный синхронный вызов PydanticAI-агента даже внутри существующего loop'а FastAPI."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(agent.run_sync, prompt, **kwargs).result()
    else:
        return agent.run_sync(prompt, **kwargs)


# --- ЛОКАЛЬНЫЙ РЕЗЕРВНЫЙ ПАЙПЛАЙН (КОГДА VLLM ОФФЛАЙН / ДЛЯ ТЕСТОВ) ---

GREETINGS_PATTERNS = {
    "привет", "здравствуй", "здравствуйте", "добрый день", "доброе утро",
    "добрый вечер", "хай", "салам", "ку", "hello", "hi", "hey"
}
SMALLTALK_PATTERNS = {
    "как дела", "как жизнь", "как ты", "как поживаешь", "как настроение",
    "что делаешь", "че делаешь", "как успехи", "что нового", "как сам",
    "че как", "как оно", "как делишки", "как твои дела", "how are you"
}
THANKS_PATTERNS = {
    "спасибо", "благодарю", "сенкс", "thanks", "thank you", "отлично", "супер", "класс", "круто"
}
CONTEXT_QUERY_PATTERNS = [
    "что мы обсуждали", "что мы уже обсуждали", "что обсуждали", "о чем мы говорили",
    "о чем говорили", "о чем шла речь", "о чем мы общались", "о чем был наш диалог",
    "что я спрашивал", "напомни контекст", "напомни о чем", "что было раньше",
    "что было ранее", "какой контекст", "история диалога", "что ты мне советовал",
    "что ты советовал", "что ты рекомендовал", "какие модели ты предлагал",
    "какие датасеты ты предлагал", "что делали", "что мы делали", "что мы делали ранее",
    "что мы тут делали", "о чем этот чат", "напомни историю", "что мы успели сделать",
    "что ты нашел ранее"
]
CATEGORY_KEYWORDS = {
    "модель": "модель", "модели": "модель", "веса": "модель",
    "датасет": "датасет", "датасеты": "датасет", "данные": "датасет",
    "репозиторий": "репозиторий", "репозитории": "репозиторий", "репо": "репозиторий",
    "статья": "статья", "статьи": "статья", "papers": "статья", "arxiv": "статья",
}


def _is_greeting(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", text.strip().lower())
    words = cleaned.split()
    return bool(words and any(w in GREETINGS_PATTERNS for w in words[:2]))


def _is_smalltalk(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", " ", text.strip().lower())
    cleaned = " ".join(cleaned.split())
    if any(cleaned == p or cleaned.startswith(f"{p} ") or cleaned.endswith(f" {p}") for p in SMALLTALK_PATTERNS):
        return True
    return bool(re.search(r"\bкак\s+(твои\s+)?(дела|жизнь|настроение|успехи|ты|оно)\b", cleaned))


def _is_context_query(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", " ", text.strip().lower())
    cleaned = " ".join(cleaned.split())
    if any(p in cleaned for p in CONTEXT_QUERY_PATTERNS):
        return True
    return bool(re.search(r"(что|о чем).*(мы\s+)?(обсуждали|говорили|спрашивал|делали)|напомни.*(контекст|диалог|вопрос|истори)", cleaned))


def _format_context_summary(history_turns: list[dict[str, str]]) -> str:
    if not history_turns:
        return (
            "В этом диалоге мы ещё ничего не обсуждали — это совершенно новый диалог! 🚀\n\n"
            "Задайте любой интересующий вас вопрос по каталогу:\n"
            "• **Модели** (Hugging Face, LMSYS Arena)\n"
            "• **Датасеты** (Kaggle, Hugging Face Datasets)\n"
            "• **Репозитории** (GitHub Trending)\n"
            "• **Научные статьи** (ArXiv, Papers with Code)"
        )
    user_topics = []
    for m in history_turns:
        if m.get("role") == "user":
            txt = m.get("content", "").strip()
            if not _is_greeting(txt) and not _is_smalltalk(txt) and not _is_context_query(txt):
                if txt.lower() in ("нлп", "nlp"):
                    user_topics.append("NLP (обработка естественного языка)")
                elif "машинн" in txt.lower() or "обучен" in txt.lower():
                    user_topics.append("машинное обучение")
                else:
                    user_topics.append(txt)

    unique_topics = []
    for t in user_topics:
        if t not in unique_topics:
            unique_topics.append(t)

    topic_str = ", ".join(unique_topics) if unique_topics else "машинное обучение"
    return (
        f"**Краткая выжимка нашего диалога:**\n\n"
        f"В этом диалоге мы исследовали задачи и подбирали материалы по темам: **{topic_str}**.\n\n"
        f"Все найденные карточки зафиксированы в этой вкладке чата. Вы можете продолжить эту тему или задать новый вопрос!"
    )


def _local_fallback_dialogue(
    history: list[dict[str, str]],
    category_filter: str = "all",
    max_sources: int = 5,
) -> dict[str, Any]:
    """
    Резервный локальный обработчик (срабатывает, если vLLM временно выключен).
    """
    last_user_msg = history[-1]["content"].strip()
    prior_history = history[:-1]

    if _is_context_query(last_user_msg):
        return {
            "role": "assistant",
            "content": _format_context_summary(prior_history),
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    if _is_smalltalk(last_user_msg):
        return {
            "role": "assistant",
            "content": "Спасибо, всё отлично! Я на связи и готов помочь с подбором моделей, датасетов и статей в Radar Scout. Какую задачу решаем?",
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    if _is_greeting(last_user_msg):
        return {
            "role": "assistant",
            "content": "Привет! 👋 Я ассистент каталога AI/ML Radar Scout. Готов найти нужные модели, датасеты, репозитории и статьи. О чем вы хотите узнать?",
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    # Определение категории и поискового запроса для фоллбэка
    search_cat = category_filter
    search_query = last_user_msg
    last_clean = re.sub(r"[^\w\s]", "", last_user_msg.lower()).strip()

    for kw, cat in CATEGORY_KEYWORDS.items():
        if last_clean == kw or last_clean == f"а {kw}" or last_clean == f"покажи {kw}":
            search_cat = cat
            for m in reversed(prior_history):
                if m.get("role") == "user":
                    prev_text = m.get("content", "").strip()
                    if not _is_greeting(prev_text) and not _is_smalltalk(prev_text):
                        search_query = f"{prev_text} {cat}"
                        break
            break

    results = rag_service.search_cards(
        query=search_query,
        category=search_cat,
        top_k=max_sources,
        min_score=0.15,
    )
    if not results and search_cat != "all":
        results = rag_service.search_cards(
            query=search_query,
            category="all",
            top_k=max_sources,
            min_score=0.15,
        )

    cards = []
    card_blocks = []
    for i, r in enumerate(results, start=1):
        c = dict(r["card"])
        clean_title = _clean_card_title(c.get("title", f"Материал #{i}"))
        c["title"] = clean_title
        cards.append(c)

        url = c.get("url", "#")
        c_type = c.get("category", "материал").upper()
        summary = (c.get("summary") or "")[:350].strip()
        score_pct = int(r.get("score", 0.0) * 100)

        card_blocks.append(
            f"#### {i}. [{clean_title}]({url})\n\n"
            f"📂 **{c_type}** · 🎯 **{score_pct}% релевантность**\n\n"
            f"{summary}\n"
        )

    if not results:
        return {
            "role": "assistant",
            "content": f"По направлению **«{search_query}»** в каталоге пока ничего не найдено. Попробуйте сформулировать запрос иначе.",
            "action": "search",
            "search_query": search_query,
            "cards": [],
            "error": None,
        }

    text_resp = (
        f"### Материалы по направлению «{search_query}»\n\n"
        f"В каталоге Radar Scout найдены следующие материалы:\n\n"
        + "\n---\n".join(card_blocks)
        + "\n\n💡 Могу подробнее рассказать о любой из этих карточек или подобрать код запуска!"
    )

    return {
        "role": "assistant",
        "content": text_resp,
        "action": "search",
        "search_query": search_query,
        "cards": cards,
        "error": None,
    }


# --- ГЛАВНАЯ ТОЧКА ВХОДА ДИАЛОГА ---

def process_dialogue(
    history: list[dict[str, str]],
    category_filter: str = "all",
    max_sources: int = 5,
    top_k: int | None = None,
) -> dict[str, Any]:
    """
    Основной метод обработки одного шага диалога:
    - Задействует автономного PydanticAI-агента на Qwen 3.6 27B с Function Calling.
    - Агент самостоятельно принимает решение о необходимости поиска по базе знаний.
    - В случае недоступности vLLM мгновенно переключается на чистый локальный резерв.
    """
    effective_limit = top_k if top_k is not None else max_sources

    if not history:
        return {
            "role": "assistant",
            "content": "Здравствуйте! Чем могу помочь? Ищете датасеты, модели, репозитории или статьи?",
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    last_user_msg = history[-1]["content"].strip()

    # 1. Если vLLM онлайн — отдаем управление умному агенту PydanticAI с Qwen 3.6 27B
    if _is_vllm_online():
        try:
            deps = RagAgentDeps(category=category_filter, limit=effective_limit)
            agent = _create_rag_agent()

            model_history: list[ModelMessage] = []
            for m in history[:-1]:
                role = m.get("role", "")
                cnt = m.get("content", "").strip()
                if not cnt:
                    continue
                if role == "user":
                    model_history.append(ModelRequest(parts=[UserPromptPart(content=cnt)]))
                elif role == "assistant":
                    model_history.append(ModelResponse(parts=[TextPart(content=cnt)]))

            res = _safe_run_agent(
                agent,
                last_user_msg,
                deps=deps,
                message_history=model_history,
            )

            final_text = str(res.output).strip()
            cards = deps.retrieved_cards
            search_query = deps.search_query
            action = "search" if cards or deps.used_leaderboard else "chat"

            return {
                "role": "assistant",
                "content": final_text,
                "action": action,
                "search_query": search_query,
                "cards": cards,
                "error": None,
            }
        except Exception as e:
            logger.debug(f"Ошибка вызова агента vLLM/Qwen ({type(e).__name__}: {e}). Переключение на локальный резерв.")

    # 2. Локальный резерв (когда vLLM оффлайн или во время unit-тестов)
    return _local_fallback_dialogue(history, category_filter, effective_limit)
