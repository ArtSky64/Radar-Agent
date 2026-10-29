"""
Модуль диалогового RAG-агента с классификацией намерений и скользящим окном диалога.

Логика:
1. Скользящее окно сообщений (история диалога).
2. Роутер намерений (Intent Router):
   - 'chat': приветствие, благодарность, смол-ток -> ответ без поиска
   - 'clarify': общий/размытый запрос ('что-то для здоровья') -> уточняющие вопросы без поиска
   - 'search': конкретный запрос -> Query Rewriting (синтез поискового запроса из истории)
3. Векторный поиск (rag_service.search_cards) по Top-K карточкам
4. Генерация итоговых рекомендаций моделью Qwen по найденным карточкам
5. Отказоустойчивый fallback при недоступности vLLM
"""

import json
import logging
import re
from typing import Any

import httpx
from openai import OpenAI

import config
import rag_service

logger = logging.getLogger("rag_agent")

# Быстрые эвристики для простых приветствий (0 мс, 0 VRAM)
GREETINGS_PATTERNS = {
    "привет", "здравствуй", "здравствуйте", "добрый день", "доброе утро",
    "добрый вечер", "хай", "салам", "ку", "hello", "hi", "hey"
}

THANKS_PATTERNS = {
    "спасибо", "благодарю", "сенкс", "thanks", "thank you", "отлично", "супер"
}


def _is_greeting(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", text.strip().lower())
    words = cleaned.split()
    if not words:
        return True
    # Простые приветствия
    if any(w in GREETINGS_PATTERNS for w in words[:2]):
        return True
    # Вопросы о возможностях ассистента
    capabilities = ["что ты умеешь", "что ты можешь", "кто ты", "как пользоваться", "помощь", "что здесь есть", "какие данные"]
    if any(c in cleaned for c in capabilities):
        return True
    return False


def _is_thanks(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", text.strip().lower())
    words = cleaned.split()
    if len(words) <= 3 and any(w in THANKS_PATTERNS for w in words):
        return True
    return False


def _is_vague(text: str) -> bool:
    cleaned = text.strip().lower()
    words = cleaned.split()
    vague_phrases = ["что-то", "что-нибудь", "посоветуй", "посоветуйте", "хочу что-то", "мне нужно что-то", "подскажи что-то", "для здоровья"]
    vague_topics = ["здоровье", "медицина", "cv", "nlp", "аудио", "модели", "датасеты"]
    if any(p in cleaned for p in vague_phrases):
        return True
    if len(words) <= 3 and any(t in cleaned for t in vague_topics):
        return True
    return False


def _get_client() -> OpenAI:
    """Возвращает OpenAI-клиент для vLLM / Qwen с быстрым таймаутом на подключение."""
    timeout_cfg = httpx.Timeout(connect=2.5, read=90.0, write=10.0, pool=10.0)
    http_client = httpx.Client(timeout=timeout_cfg)
    return OpenAI(
        base_url=config.VLLM_BASE_URL,
        api_key=config.VLLM_API_KEY or "not-needed",
        http_client=http_client,
    )


ROUTER_SYSTEM_PROMPT = """Ты — интеллектуальный классификатор и консультант каталога AI/ML ресурсов (датасеты, модели, репозитории, статьи).
Твоя задача — проанализировать последнее сообщение пользователя с учетом истории диалога и определить действие:

1. "chat" — если сообщение является приветствием, благодарностью, вежливым смол-током или прощанием.
   В поле reply напиши дружелюбный ответ и кратко напомни, что в базе есть датасеты, модели и статьи.

2. "clarify" — если запрос слишком общий, абстрактный или размытый (например: "мне нужно что-то для здоровья", "посоветуй модель", "хочу что-то по CV", "а что у вас есть?").
   Пользователь ещё не указал конкретную задачу или тип данных.
   В поле reply задай 1-2 наводящих вопроса: что именно интересует (модели или сырые датасеты, снимки, текст или табличные данные).

3. "search" — если в запросе (или совместно с историей диалога) уже есть конкретика (задача, тематика, тип данных или название).
   В поле search_query сформулируй полный, ёмкий поисковый запрос на русском языке, ОБЪЕДИНИВ контекст из всей истории диалога.
   В поле category укажи категорию: "датасет", "модель", "репозиторий", "статья" или "all".

Отвечай СТРОГО валидным JSON-объектом без лишних символов и разметки:
{
  "action": "chat" | "clarify" | "search",
  "reply": "текст ответа пользователю (для chat и clarify, либо пустая строка для search)",
  "search_query": "поисковый запрос (только для search)",
  "category": "датасет" | "модель" | "репозиторий" | "статья" | "all"
}"""


RECOMMENDER_SYSTEM_PROMPT = """Ты — ведущий эксперт по машинному обучению и персональный консультант каталога AI/ML ресурсов.
Тебе предоставлены:
1. История диалога с пользователем.
2. Поисковый запрос.
3. Топ наиболее релевантных карточек, найденных в базе данных по векторному сходству.

Твоя задача — составить связный, грамотный и структурированный ответ с рекомендациями:
1. Кратко подтверди запрос пользователя и сообщи, что удалось найти в каталоге.
2. Подробно разбери каждую предложенную карточку:
   - В чем её суть и главная ценность под задачу пользователя.
   - Особенности (объем, форматы, теги, метрики — скачивания/звезды, если есть).
3. Сравни их между собой или порекомендуй, с чего лучше начать эксперименты.
Будь конкретен, не придумывай несуществующие данные, опирайся строго на предоставленный контекст карточек.
Пиши живым языком с красивым оформлением (списки, жирный шрифт)."""


def process_dialogue(
    history: list[dict[str, str]],
    category_filter: str = "all",
    top_k: int = 5,
) -> dict[str, Any]:
    """
    Основной метод обработки одного шага диалога.

    :param history: список сообщений [{'role': 'user'|'assistant', 'content': '...'}, ...]
    :param category_filter: принудительный фильтр из интерфейса ('all', 'датасет', 'модель', и т.д.)
    :param top_k: количество карточек для выдачи
    :return: dict со структурой:
        {
            "role": "assistant",
            "content": str,
            "action": "chat" | "clarify" | "search",
            "search_query": str | None,
            "cards": list[dict],
            "error": str | None
        }
    """
    if not history:
        return {
            "role": "assistant",
            "content": "Здравствуйте! Чем могу помочь? Ищете датасеты, модели или статьи?",
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    last_user_msg = history[-1]["content"].strip()

    # --- Шаг 1: Быстрые эвристики (0 мс, экономим инференс) ---
    if len(history) <= 2:
        if _is_greeting(last_user_msg):
            return {
                "role": "assistant",
                "content": (
                    "Привет! 👋 Я интеллектуальный ассистент каталога AI/ML ресурсов.\n\n"
                    "У меня есть проверенная база с тысячами материалов:\n"
                    "• **Датасеты** (Hugging Face, Kaggle)\n"
                    "• **Трендовые модели** (LLM, Vision, Audio)\n"
                    "• **Репозитории и препринты статей**\n\n"
                    "Опишите задачу, над которой работаете (например: *«найди датасеты для анализа кибератак»* "
                    "или *«посоветуй легкую модель для классификации текста»*) — и я подберу лучшее!"
                ),
                "action": "chat",
                "search_query": None,
                "cards": [],
                "error": None,
            }

        if _is_thanks(last_user_msg):
            return {
                "role": "assistant",
                "content": "Пожалуйста! Рад помочь. Если понадобятся ещё датасеты или модели — обращайтесь! 🚀",
                "action": "chat",
                "search_query": None,
                "cards": [],
                "error": None,
            }

    # --- Шаг 2: Скользящее окно (берём последние 6 сообщений) ---
    window = history[-6:]

    # Попытка связаться с Qwen (vLLM)
    try:
        client = _get_client()

        # Формируем запрос к классификатору намерений
        router_messages = [{"role": "system", "content": ROUTER_SYSTEM_PROMPT}]
        for msg in window:
            router_messages.append({"role": msg["role"], "content": msg["content"]})

        completion = client.chat.completions.create(
            model=config.VLLM_MODEL_NAME,
            messages=router_messages,
            temperature=0.1,
            max_tokens=400,
        )

        raw_reply = completion.choices[0].message.content or "{}"
        # Очищаем возможные markdown-блоки вида ```json ... ```
        clean_json = re.sub(r"^```json\s*", "", raw_reply.strip())
        clean_json = re.sub(r"\s*```$", "", clean_json)

        try:
            decision = json.loads(clean_json)
        except Exception:
            # Если Qwen выдал текст не в JSON, пробуем найти JSON внутри
            match = re.search(r"\{.*\}", clean_json, re.DOTALL)
            if match:
                decision = json.loads(match.group(0))
            else:
                # Если всё равно не JSON, считаем поиском по последнему сообщению
                decision = {
                    "action": "search",
                    "search_query": last_user_msg,
                    "category": category_filter,
                }

        action = decision.get("action", "search")

        # Если это чат или уточнение — отдаём ответ модели сразу без похода в векторную БД
        if action in ("chat", "clarify") and decision.get("reply"):
            return {
                "role": "assistant",
                "content": decision["reply"],
                "action": action,
                "search_query": None,
                "cards": [],
                "error": None,
            }

        # Если действие — поиск (action == 'search')
        search_query = decision.get("search_query") or last_user_msg
        search_cat = category_filter if category_filter != "all" else decision.get("category", "all")

        # Выполняем векторный поиск в базе карточек
        results = rag_service.search_cards(
            query=search_query,
            category=search_cat,
            top_k=top_k,
            min_score=0.15,
        )

        if not results:
            return {
                "role": "assistant",
                "content": (
                    f"К сожалению, по запросу **«{search_query}»** в текущей базе не нашлось точных совпадений.\n\n"
                    "Попробуйте переформулировать запрос более общими словами или переключить фильтр категории на «Все материалы»."
                ),
                "action": "search",
                "search_query": search_query,
                "cards": [],
                "error": None,
            }

        cards = [r["card"] for r in results]

        # Шаг 3: Генерация финальной рекомендации моделью Qwen по найденным карточкам
        context_blocks = []
        for i, r in enumerate(results, start=1):
            c = r["card"]
            score_pct = int(r["score"] * 100)
            tags_str = ", ".join(c.get("tags", []))
            summary_short = (c.get("summary") or "")[:400]
            context_blocks.append(
                f"[{i}] {c.get('title')} ({c.get('category').upper()})\n"
                f"Релевантность: {score_pct}%\n"
                f"Ссылка: {c.get('url')}\n"
                f"Теги: {tags_str}\n"
                f"Описание: {summary_short}\n"
            )

        rag_prompt = (
            f"Поисковый запрос пользователя: {search_query}\n\n"
            f"Найденные карточки из базы знаний:\n"
            + "\n---\n".join(context_blocks)
        )

        recommender_messages = [
            {"role": "system", "content": RECOMMENDER_SYSTEM_PROMPT},
            {"role": "user", "content": rag_prompt},
        ]

        rec_completion = client.chat.completions.create(
            model=config.VLLM_MODEL_NAME,
            messages=recommender_messages,
            temperature=0.3,
            max_tokens=900,
        )

        final_answer = rec_completion.choices[0].message.content

        return {
            "role": "assistant",
            "content": final_answer,
            "action": "search",
            "search_query": search_query,
            "cards": cards,
            "error": None,
        }

    except Exception as e:
        logger.warning(f"vLLM недоступен ({e}), активируется локальный семантический режим.")
        # --- Резервный режим (Fallback): быстрый векторный поиск без LLM ---
        # Если запрос похож на неопределенный короткий ("мне нужно что-то для здоровья", "посоветуй модель")
        if _is_vague(last_user_msg):
            return {
                "role": "assistant",
                "content": (
                    f"Тема **«{last_user_msg}»** достаточно обширна! Уточните, пожалуйста:\n\n"
                    "1. Вас интересуют готовые **модели** или сырые **датасеты** для обучения?\n"
                    "2. С каким типом данных вы планируете работать (текст, изображения/снимки, аудио или табличные данные)?\n\n"
                    "После вашего ответа я сформирую точную подборку!"
                ),
                "action": "clarify",
                "search_query": None,
                "cards": [],
                "error": None,
            }

        # Иначе выполняем чистый локальный косинусный поиск карточек
        results = rag_service.search_cards(
            query=last_user_msg,
            category=category_filter,
            top_k=top_k,
            min_score=0.15,
        )

        if not results:
            return {
                "role": "assistant",
                "content": f"По запросу **«{last_user_msg}»** подходящих карточек не найдено. Попробуйте изменить формулировку.",
                "action": "search",
                "search_query": last_user_msg,
                "cards": [],
                "error": "offline_mode",
            }

        cards = [r["card"] for r in results]
        summary_text = (
            f"🔍 По вашему запросу **«{last_user_msg}»** найдено **{len(cards)}** наиболее релевантных карточек "
            f"в локальной базе знаний по векторному сходству:\n\n"
        )
        for i, r in enumerate(results, 1):
            c = r["card"]
            score_pct = int(r["score"] * 100)
            summary_text += f"**{i}. [{c['category'].upper()}] {c['title']}** (сходство: {score_pct}%)\n"
            if c.get("summary"):
                summary_text += f"> {c['summary'][:200]}...\n\n"

        return {
            "role": "assistant",
            "content": summary_text,
            "action": "search",
            "search_query": last_user_msg,
            "cards": cards,
            "error": "offline_mode",
        }
