"""
Модуль интеллектуального диалогового агента Radar Scout.
Работает как автономная экспертная модель уровня Gemini / ChatGPT, глубоко ориентированная
на данные сервиса AI/ML Radar (лидерборд LMSYS Arena, модели Hugging Face, датасеты Kaggle,
репозитории GitHub, статьи ArXiv и Papers with Code).
Работает полностью автономно и локально, не требуя внешних платных API или сторонних нейросетей.
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

# Шаблоны приветствий, смолл-тока и благодарностей
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
    "что мы обсуждали",
    "что мы уже обсуждали",
    "что обсуждали",
    "о чем мы говорили",
    "о чем говорили",
    "о чем шла речь",
    "о чем мы общались",
    "о чем был наш диалог",
    "что я спрашивал",
    "напомни контекст",
    "напомни о чем",
    "что было раньше",
    "что было ранее",
    "какой контекст",
    "история диалога",
    "что ты мне советовал",
    "что ты советовал",
    "что ты рекомендовал",
    "какие модели ты предлагал",
    "какие датасеты ты предлагал",
    "что делали",
    "что мы делали",
    "что мы делали ранее",
    "что мы тут делали",
    "о чем этот чат",
    "напомни историю",
    "что мы успели сделать",
    "что ты нашел ранее",
]

CATEGORY_KEYWORDS: dict[str, str] = {
    "модель": "модель",
    "модели": "модель",
    "моделей": "модель",
    "веса": "модель",
    "weights": "модель",
    "датасет": "датасет",
    "датасеты": "датасет",
    "датасетов": "датасет",
    "данные": "датасет",
    "корпус": "датасет",
    "репозиторий": "репозиторий",
    "репозитории": "репозиторий",
    "репозиториев": "репозиторий",
    "репо": "репозиторий",
    "библиотеки": "репозиторий",
    "библиотека": "репозиторий",
    "исходники": "репозиторий",
    "код": "репозиторий",
    "статья": "статья",
    "статьи": "статья",
    "статей": "статья",
    "пейперс": "статья",
    "papers": "статья",
    "arxiv": "статья",
    "исследования": "статья",
}

DOMAIN_KEYWORDS: dict[str, tuple[str, str]] = {
    "медицин": ("Медицина и Healthcare AI", "анализ медицинских снимков (МРТ/КТ), сегментация патологий, биомедицина и клинические исследования"),
    "здравоохран": ("Медицина и здравоохранение", "клинические рекомендации, медицинские системы и поддержка врачей"),
    "клинич": ("Клиническая медицина и здравоохранение", "клинические испытания, протоколы лечения и биоинформатика"),
    "врач": ("Медицина и здравоохранение", "диагностика, медицинские ассистенты и поддержка принятия решений"),
    "болезн": ("Медицинская диагностика", "диагностика заболеваний, биомаркеры и анализ симптомов"),
    "диагност": ("Медицинская диагностика и визуализация", "автоматизированный анализ снимков, МРТ, КТ и рентгена"),
    "мрт": ("Медицинская визуализация (МРТ/КТ)", "сегментация и анализ томографических снимков"),
    "биомед": ("Биомедицина и биоинформатика", "генетические исследования, белковые структуры и биомедицинские данные"),
    "nlp": ("NLP (обработка естественного языка)", "обработка текста, токенизация, языковые модели (LLM) и эмбеддинги"),
    "нлп": ("NLP (обработка естественного языка)", "обработка текста, токенизация, языковые модели (LLM) и эмбеддинги"),
    "текст": ("NLP и анализ текста", "классификация, генерация текста, поиск и суммаризация"),
    "llm": ("Большие языковые модели (LLM)", "генеративный AI, трансформеры и диалоговые ассистенты"),
    "cv": ("Компьютерное зрение (Computer Vision)", "детекция объектов, сегментация и генерация изображений"),
    "зрение": ("Компьютерное зрение (Computer Vision)", "детекция объектов, сегментация и визуальные энкодеры"),
    "картинк": ("Компьютерное зрение (Computer Vision)", "работа с изображениями и диффузионными моделями"),
    "аудио": ("Аудио и речевые технологии (Speech & Audio)", "распознавание речи (ASR), синтез (TTS) и обработка звука"),
    "реч": ("Аудио и речевые технологии (Speech & Audio)", "распознавание речи (ASR) и синтез голоса (TTS)"),
    "whisper": ("Распознавание речи (Whisper / ASR)", "транскрипция аудио и речевые модели"),
    "машинное обучение": ("Машинное обучение (Machine Learning)", "фундаментальные алгоритмы, моделирование и анализ данных"),
    "обучени": ("Машинное и глубокое обучение", "обучение и оптимизация нейросетевых моделей"),
    "глубокое обучение": ("Глубокое обучение (Deep Learning)", "многослойные нейросети, PyTorch и оптимизация"),
    "mlops": ("MLOps и инференс", "оптимизация, деплой, vLLM, мониторинг и обслуживание моделей"),
    "кибератак": ("Кибербезопасность и анализ угроз", "выявление аномалий, сетевых атак и безопасность AI"),
    "безопасност": ("Информационная безопасность и детекция угроз", "анализ уязвимостей и классификация сетевого трафика"),
    "табличн": ("Табличные данные и классический ML", "градиентный бустинг, CatBoost, XGBoost и Scikit-learn"),
    "финанс": ("Финансы и Финтех AI", "финансовый скоринг, анализ временных рядов и трейдинг"),
    "робот": ("Робототехника и автономные системы", "управление манипуляторами, навигация и SLAM"),
}

STOP_WORDS = {
    "привет", "здравствуй", "здравствуйте", "добрый", "день", "утро", "вечер", "хай", "салам", "ку",
    "спасибо", "благодарю", "сенкс", "thanks", "thank", "you", "отлично", "супер", "класс", "круто",
    "дела", "как", "жизнь", "настроение", "успехи", "поживаешь", "делаешь", "нового", "сам", "оно",
    "модель", "модели", "датасет", "датасеты", "репо", "репозиторий", "репозитории",
    "статья", "статьи", "papers", "что", "где", "кто", "куда", "откуда", "почему", "зачем",
    "покажи", "найди", "посоветуй", "подскажи", "расскажи", "скажи", "дай",
    "хочу", "нужно", "надо", "можно", "есть", "было", "были", "будет", "будут",
    "да", "нет", "ок", "еще", "ещё", "ранее", "обсуждали", "делали", "говорили", "тема",
    "вопрос", "ответ", "помоги", "помощь", "это", "этот", "эта", "эти", "тот", "та", "те",
    "все", "всё", "тоже", "также", "очень", "просто"
}


def _strip_repeated_greetings(text: str) -> str:
    """Удаляет повторные приветствия («Привет!», «Здравствуйте!» и т.д.) из начала ответа в продолжающемся диалоге."""
    if not text:
        return text
    pattern = r"^(Привет[!\.,\s]*|Здравствуйте[!\.,\s]*|Добрый день[!\.,\s]*|Доброго времени суток[!\.,\s]*|Hello[!\.,\s]*|Hi[!\.,\s]*)+"
    cleaned = re.sub(pattern, "", text.strip(), flags=re.IGNORECASE).strip()
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned if cleaned else text


def _extract_conversation_topics(history: list[dict[str, str]]) -> list[str]:
    """Извлекает содержательные темы из предшествующих реплик пользователя (без смолл-тока и стоп-слов)."""
    topics = []
    for m in history:
        if m.get("role") == "user":
            txt = m.get("content", "").strip().lower()
            if _is_greeting(txt) or _is_smalltalk(txt) or _is_thanks(txt) or _is_context_query(txt):
                continue
            words = [re.sub(r"[^\w\s-]", "", w) for w in txt.split()]
            meaningful = [w for w in words if len(w) > 2 and w not in STOP_WORDS]
            if meaningful:
                topics.append(" ".join(meaningful))
    return topics


def _is_greeting(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", text.strip().lower())
    words = cleaned.split()
    if not words:
        return True
    if any(w in GREETINGS_PATTERNS for w in words[:2]):
        return True
    capabilities = ["что ты умеешь", "что ты можешь", "кто ты", "как пользоваться", "помощь", "что здесь есть", "какие данные"]
    if any(c in cleaned for c in capabilities):
        return True
    return False


def _is_smalltalk(text: str) -> bool:
    """Проверяет реплики повседневного общения (как дела, как жизнь и т.д.)."""
    cleaned = re.sub(r"[^\w\s]", " ", text.strip().lower())
    cleaned = " ".join(cleaned.split())
    if any(cleaned == p or cleaned.startswith(f"{p} ") or cleaned.endswith(f" {p}") for p in SMALLTALK_PATTERNS):
        return True
    if re.search(r"\bкак\s+(твои\s+)?(дела|жизнь|настроение|успехи|ты|оно)\b", cleaned):
        return True
    if re.search(r"\b(что|че)\s+(делаешь|нового)\b", cleaned):
        return True
    return False


def _is_thanks(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", text.strip().lower())
    words = cleaned.split()
    if len(words) <= 3 and any(w in THANKS_PATTERNS for w in words):
        return True
    return False


def _is_context_query(text: str) -> bool:
    """Определяет, спрашивает ли пользователь о предыдущем контексте / истории текущего диалога."""
    cleaned = re.sub(r"[^\w\s]", " ", text.strip().lower())
    cleaned = " ".join(cleaned.split())
    if any(p in cleaned for p in CONTEXT_QUERY_PATTERNS):
        return True
    if re.search(r"(что|о чем).*(мы\s+)?(обсуждали|говорили|спрашивал|делали)", cleaned):
        return True
    if re.search(r"напомни.*(контекст|диалог|вопрос|тему|истори)", cleaned):
        return True
    if re.search(r"истори[яи].*диалог", cleaned):
        return True
    return False


def _analyze_dialogue_state(history: list[dict[str, str]]) -> dict[str, Any]:
    """
    Анализирует всю историю сообщений для поддержания единого контекста диалога:
    - активный домен (NLP, CV, Audio, ML, MLOps, CyberSec, Медицина)
    - активная категория (модель, датасет, репозиторий, статья)
    - хронология переходов пользователя
    """
    detected_domains: list[str] = []
    domain_description = "машинное обучение и искусственный интеллект"
    active_category = "all"
    categories_history: list[str] = []

    for m in history:
        if m.get("role") == "user":
            txt = m.get("content", "").strip().lower()
            if _is_smalltalk(txt) or _is_greeting(txt) or _is_thanks(txt):
                continue

            # Анализ категории
            for kw, cat in CATEGORY_KEYWORDS.items():
                if re.search(rf"\b{kw}\b", txt):
                    active_category = cat
                    if cat not in categories_history:
                        categories_history.append(cat)
                    break

            # Анализ домена
            for kw, (d_name, d_desc) in DOMAIN_KEYWORDS.items():
                if kw in txt:
                    if d_name not in detected_domains:
                        detected_domains.append(d_name)
                    domain_description = d_desc

    main_domain = detected_domains[-1] if detected_domains else "Машинное обучение"

    return {
        "main_domain": main_domain,
        "domain_description": domain_description,
        "all_domains": detected_domains,
        "active_category": active_category,
        "categories_history": categories_history,
    }


def _clean_summary(summary: str, max_len: int = 350) -> str:
    """Аккуратно обрезает описание по границе предложения или слова, никогда не срезая слово на полубукве."""
    if not summary:
        return ""
    clean = re.sub(r"\s+", " ", summary).strip()
    if len(clean) <= max_len:
        return clean
    truncated = clean[:max_len]
    last_dot = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
    if last_dot > 120:
        return truncated[:last_dot + 1].strip()
    last_space = truncated.rfind(" ")
    if last_space > 100:
        return truncated[:last_space].strip() + "..."
    return truncated.strip() + "..."


def _format_context_summary(history_turns: list[dict[str, str]]) -> str:
    """Формирует КРАТКУЮ СВЯЗНУЮ ВЫЖИМКУ из диалога в стиле Gemini (без механического копирования реплик по номерам)."""
    if not history_turns:
        return (
            "В этом диалоге мы ещё ничего не обсуждали — это совершенно новый диалог! 🚀\n\n"
            "Задайте любой интересующий вас вопрос по каталогу:\n"
            "• **Модели** (Hugging Face, LMSYS Arena)\n"
            "• **Датасеты** (Kaggle, Hugging Face Datasets)\n"
            "• **Репозитории** (GitHub Trending)\n"
            "• **Научные статьи** (ArXiv, Papers with Code)\n\n"
            "О чем вы хотите узнать?"
        )

    state = _analyze_dialogue_state(history_turns)
    main_domain = state["main_domain"]
    domains = state["all_domains"]
    cats = state["categories_history"]
    topics = _extract_conversation_topics(history_turns)

    cat_names_map = {
        "репозиторий": "репозитории с исходным кодом",
        "модель": "актуальные модели и веса",
        "датасет": "профильные датасеты",
        "статья": "исследовательские статьи",
    }
    cat_phrases = [cat_names_map.get(c, c) for c in cats]

    summary_parts = []
    unique_topics = []
    for t in topics:
        if t not in unique_topics:
            unique_topics.append(t)

    if unique_topics:
        topic_highlight = ", ".join(unique_topics[:3])
        if domains and main_domain.lower() not in topic_highlight.lower():
            summary_parts.append(
                f"В этом диалоге мы исследовали задачи по направлению **{topic_highlight}** "
                f"в рамках темы **{main_domain}**."
            )
        else:
            summary_parts.append(
                f"В этом диалоге мы исследовали задачи по теме **{topic_highlight}**."
            )
    elif domains:
        domains_str = " и ".join(domains[:2])
        summary_parts.append(
            f"В этом диалоге мы исследовали направление **{domains_str}**."
        )
    else:
        summary_parts.append(
            f"В этом диалоге мы сфокусировались на теме **{main_domain}**."
        )

    if cat_phrases:
        if len(cat_phrases) == 1:
            summary_parts.append(f"В процессе мы подобрали и проанализировали **{cat_phrases[0]}**.")
        else:
            first_cats = ", ".join(cat_phrases[:-1])
            summary_parts.append(f"В процессе мы сначала подобрали **{first_cats}**, а затем рассмотрели **{cat_phrases[-1]}**.")
    else:
        summary_parts.append("Мы изучили наиболее востребованные материалы каталога по этому направлению.")

    summary_text = " ".join(summary_parts)

    return (
        f"**Краткая выжимка нашего диалога:**\n\n"
        f"{summary_text}\n\n"
        f"Все найденные карточки зафиксированы в этой вкладке чата. "
        f"Вы можете продолжить эту тему, углубиться в конкретные параметры или перейти к новому вопросу!"
    )


# --- СИСТЕМНАЯ ИНСТРУКЦИЯ (GEMINI-ПОДОБНЫЙ ЭКСПЕРТ РАДАРА) ---
RADAR_AI_SYSTEM_INSTRUCTION = """Ты — интеллектуальный персональный AI-ассистент сервиса AI/ML Radar Scout, созданный на базе передовых моделей уровня Gemini.
Ты обладаешь глубокими экспертными знаниями во ВСЕХ сферах современного искусственного интеллекта и анализа данных:
- Компьютерное зрение (Computer Vision): сегментация, детекция объектов, медицинская визуализация (МРТ, КТ, рентген), генерация изображений.
- Медицина и биоинформатика: анализ снимков, патологии, клинические датасеты, генетика.
- Аудио и речь (Speech & Audio): распознавание речи (ASR, Whisper), синтез речи (TTS), аудиоанализ.
- Табличные данные и классический ML: градиентный бустинг (CatBoost, XGBoost), скоринг, регрессия, временные ряды.
- Робототехника и обучение с подкреплением (RL): управление, навигация, автономные системы.
- Большие языковые модели (LLM) и NLP: обработка текста, токенизация (ТОЛЬКО если пользователь явно спрашивает про текст/NLP).
- MLOps и инфраструктура: vLLM, TensorRT, квантование (GGUF, AWQ, FP8), мониторинг.

КАТЕГОРИЧЕСКИЙ ЗАПРЕТ НА НАВЯЗЫВАНИЕ NLP:
- Каталог Radar Scout охватывает все направления ИИ, а НЕ только NLP!
- НИКОГДА не своди ответ пользователя к NLP или языковым моделям, если пользователь явно не попросил именно NLP/текст!
- Если пользователь спрашивает про «медицину» — отвечай строго в контексте медицины (анализ снимков, МРТ/КТ, гистология, клинические датасеты). Категорически запрещено писать фразы вроде «Если ваша цель — медицинский NLP...»! Медицинский AI — это прежде всего анализ медицинских изображений и клинических данных!
- Если пользователь спрашивает про «компьютерное зрение» — отвечай строго про CV.
- Если пользователь спрашивает про «звук / речь» — отвечай строго про аудио.

ПРАВИЛА ДИАЛОГА И КОНТЕКСТА:
1. ПОЛНАЯ ПАМЯТЬ ДИАЛОГА:
   - Всегда помни весь контекст беседы. Если пользователь развивает тему или пишет короткое уточнение («модели», «репо», «датасеты»), отвечай строго в рамках текущей обсуждаемой темы.
   - НИКОГДА не здоровайся повторно («Привет!», «Здравствуйте!»), если беседа уже идет.
   - Если пользователь спрашивает, о чем говорили ранее, дай естественную выжимку в 2-3 предложениях без списков и номеров.

2. РАБОТА С КАТАЛОГОМ И РЕКОМЕНДАЦИЯМИ:
   - Когда в запросе предоставлены найденные карточки каталога, детально используй их в ответе: объясняй, чем они хороши, под какие сценарии подходят, сравнивай их.
   - Для КАЖДОЙ рекомендуемой карточки обязательно делай кликабельную Markdown-ссылку в формате [Название карточки](url).
   - Если точных готовых моделей по теме нет, но есть профильные датасеты или научные статьи из каталога — порекомендуй их и объясни, как они помогают решить задачу.

3. ОФОРМЛЕНИЕ И ЗАВЕРШЕННОСТЬ:
   - Никогда не обрывай ответ на полуслове.
   - Форматируй ответ в красивом GitHub Markdown: заголовки ##, жирный шрифт, списки, таблицы и блоки кода."""


def _call_gemini(messages: list[dict[str, str]], system_instruction: str, max_tokens: int = 3500) -> str | None:
    """Вызов Gemini API через официальный SDK google.genai (если ключ предоставлен)."""
    if not config.GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=config.GEMINI_API_KEY)

        contents = []
        for m in messages:
            role = "user" if m.get("role") == "user" else "model"
            text_part = m.get("content", "").strip()
            if text_part:
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text_part)]))

        if not contents:
            return None

        cfg = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            max_output_tokens=max_tokens,
        )

        resp = client.models.generate_content(
            model=config.GEMINI_MODEL_NAME,
            contents=contents,
            config=cfg,
        )
        return resp.text
    except Exception as e:
        logger.debug(f"Gemini API не используется или не настроен ({e})")
        return None


def _call_openai_or_vllm(messages: list[dict[str, str]], system_instruction: str, max_tokens: int = 3500) -> str | None:
    """Вызов OpenAI или локального vLLM-сервера (если настроен)."""
    if config.OPENAI_API_KEY:
        try:
            client = OpenAI(
                api_key=config.OPENAI_API_KEY,
                base_url=config.OPENAI_BASE_URL or None,
            )
            chat_messages = [{"role": "system", "content": system_instruction}] + messages
            completion = client.chat.completions.create(
                model=config.OPENAI_MODEL_NAME,
                messages=chat_messages,
                temperature=0.3,
                max_tokens=max_tokens,
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.debug(f"OpenAI API не используется ({e})")

    if config.VLLM_BASE_URL:
        try:
            timeout_cfg = httpx.Timeout(connect=2.5, read=90.0, write=10.0, pool=10.0)
            client = OpenAI(
                base_url=config.VLLM_BASE_URL,
                api_key=config.VLLM_API_KEY or "not-needed",
                http_client=httpx.Client(timeout=timeout_cfg),
            )
            chat_messages = [{"role": "system", "content": system_instruction}] + messages
            completion = client.chat.completions.create(
                model=config.VLLM_MODEL_NAME,
                messages=chat_messages,
                temperature=0.3,
                max_tokens=max_tokens,
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.debug(f"vLLM недоступен: {e}")

    return None


def _call_llm(messages: list[dict[str, str]], system_instruction: str, max_tokens: int = 3500) -> str | None:
    """Универсальный вызов опционального внешнего LLM-провайдера."""
    ans = _call_gemini(messages, system_instruction, max_tokens)
    if ans:
        return ans
    return _call_openai_or_vllm(messages, system_instruction, max_tokens)


def _build_local_expert_response(
    search_query: str,
    dialogue_state: dict[str, Any],
    results: list[dict[str, Any]],
    is_follow_up: bool = False,
) -> str:
    """
    Генерирует интеллектуальный, связный, экспертный ответ в стиле Gemini
    на основе найденных материалов каталога Radar Scout, без необходимости во внешних нейросетях.
    """
    if not results:
        return (
            f"По направлению **«{search_query}»** точных совпадений в базе знаний пока не найдено.\n\n"
            "💡 **Рекомендация:**\n"
            "- Попробуйте сформулировать запрос шире (например, *«компьютерное зрение»*, *«медицинские датасеты»*, *«аудиомодели»* или *«классификатор табличных данных»*)\n"
            "- Либо сбросьте фильтр категорий на **«Все типы»** для поиска по всей экосистеме сервиса."
        )

    main_domain = dialogue_state["main_domain"]
    domain_desc = dialogue_state["domain_description"]

    # Иконки для доменов
    domain_icons = {
        "Медицина и Healthcare AI": "🏥",
        "Клиническая медицина и здравоохранение": "🩺",
        "Медицинская диагностика и визуализация": "🔬",
        "Медицинская диагностика": "💊",
        "Медицинская визуализация (МРТ/КТ)": "🔬",
        "Биомедицина и биоинформатика": "🧬",
        "NLP (обработка естественного языка)": "🧠",
        "NLP и анализ текста": "📝",
        "Большие языковые модели (LLM)": "🤖",
        "Компьютерное зрение (Computer Vision)": "👁",
        "Аудио и речевые технологии (Speech & Audio)": "🎙",
        "Машинное обучение (Machine Learning)": "⚙️",
        "Машинное и глубокое обучение": "🔬",
        "MLOps и инференс": "⚡",
        "Кибербезопасность и анализ угроз": "🛡",
        "Табличные данные и классический ML": "📊",
        "Финансы и Финтех AI": "📈",
        "Робототехника и автономные системы": "🤖",
    }
    icon = domain_icons.get(main_domain, "🚀")

    # Определяем, какие категории реально найдены в результатах
    found_categories = set(r["card"].get("category", "") for r in results)

    heading = f"### {icon} {main_domain}"

    if len(found_categories) == 1:
        single_cat = list(found_categories)[0]
        if single_cat == "статья":
            intro = f"По направлению **{main_domain}** в каталоге сервиса подобраны ключевые научные статьи и исследования:"
        elif single_cat == "модель":
            intro = f"По направлению **{main_domain}** в каталоге сервиса подобраны актуальные предобученные модели и веса:"
        elif single_cat == "репозиторий":
            intro = f"Для разработки и реализации задач по направлению **{main_domain}** рекомендую следующие открытые библиотеки и инструменты:"
        elif single_cat == "датасет":
            intro = f"Для обучения и валидации решений по направлению **{main_domain}** в каталоге найдены следующие размеченные датасеты:"
        else:
            intro = f"В каталоге сервиса по теме **{main_domain}** найдены следующие материалы:"
    else:
        intro = f"По направлению **{main_domain}** в каталоге сервиса собраны проверенные материалы, охватывающие модели, исходный код и исследования:"

    # Детальное представление карточек
    cards_md = []
    sample_model_id = None
    sample_repo_url = None
    sample_dataset_title = None

    for i, r in enumerate(results, start=1):
        c = r["card"]
        score_pct = int(r["score"] * 100)
        raw_title = c.get("title", f"Материал #{i}").strip()
        url = c.get("url", "#")
        c_type = c.get("category", "материал").upper()
        metrics = c.get("metrics") or {}
        summary = (c.get("summary") or "").strip()
        tags = c.get("tags") or []

        # Очистка названия от двойных скобок типа [[PwC] Title]
        clean_title = re.sub(r"^\[(.*?)\]\s*", r"\1: ", raw_title)
        clean_title = clean_title.replace("[", "(").replace("]", ")")
        clean_title = re.sub(r"\s+", " ", clean_title).strip()

        if not sample_model_id and c.get("category") == "модель":
            sample_model_id = clean_title
        if not sample_repo_url and c.get("category") == "репозиторий":
            sample_repo_url = url
        if not sample_dataset_title and c.get("category") == "датасет":
            sample_dataset_title = clean_title

        # Метрики
        badges = [f"📂 **{c_type}**", f"🎯 **{score_pct}% релевантность**"]
        if metrics.get("stars"):
            badges.append(f"⭐ **{metrics['stars']}** звёзд")
        if metrics.get("downloads"):
            badges.append(f"📥 **{metrics['downloads']}** скачиваний")
        badges_str = " · ".join(badges)

        # Теги
        tags_str = " ".join([f"`#{t}`" for t in tags[:5]]) if tags else ""

        # Аккуратная выжимка без обрыва слов
        desc_clean = _clean_summary(summary, max_len=350)

        card_block = (
            f"#### {i}. [{clean_title}]({url})\n\n"
            f"{badges_str}\n\n"
            f"{desc_clean}\n"
        )
        if tags_str:
            card_block += f"\n🏷 **Теги:** {tags_str}\n"

        cards_md.append(card_block)

    cards_section = "\n---\n".join(cards_md)

    # Инженерный блок быстрого старта (Quickstart Snippet)
    snippet_section = ""
    domain_lower = main_domain.lower()
    if "модель" in found_categories and sample_model_id:
        if any(w in domain_lower for w in ["cv", "зрени", "картинк", "изображен"]):
            snippet_section = (
                f"\n\n```python\n"
                f"# Загрузка визуальной модели через Hugging Face Transformers\n"
                f"from transformers import AutoImageProcessor, AutoModelForImageClassification\n"
                f"from PIL import Image\n\n"
                f"processor = AutoImageProcessor.from_pretrained(\"{sample_model_id}\")\n"
                f"model = AutoModelForImageClassification.from_pretrained(\"{sample_model_id}\")\n"
                f"```\n"
            )
        elif any(w in domain_lower for w in ["аудио", "реч", "whisper", "звук"]):
            snippet_section = (
                f"\n\n```python\n"
                f"# Запуск аудиомодели через Transformers\n"
                f"from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq\n\n"
                f"processor = AutoProcessor.from_pretrained(\"{sample_model_id}\")\n"
                f"model = AutoModelForSpeechSeq2Seq.from_pretrained(\"{sample_model_id}\")\n"
                f"```\n"
            )
        elif any(w in domain_lower for w in ["табличн", "бустинг", "классификатор"]):
            snippet_section = (
                f"\n\n```python\n"
                f"# Загрузка классификатора табличных данных\n"
                f"import joblib\n"
                f"model = joblib.load(\"model.joblib\")\n"
                f"predictions = model.predict(X_test)\n"
                f"```\n"
            )
        elif any(w in domain_lower for w in ["медицин", "диагност"]):
            snippet_section = (
                f"\n\n```python\n"
                f"# Пайплайн обработки медицинских снимков\n"
                f"import torch\n"
                f"from transformers import AutoProcessor, AutoModel\n\n"
                f"processor = AutoProcessor.from_pretrained(\"{sample_model_id}\")\n"
                f"model = AutoModel.from_pretrained(\"{sample_model_id}\")\n"
                f"```\n"
            )
        elif any(w in domain_lower for w in ["nlp", "нлп", "текст", "llm", "язык"]):
            snippet_section = (
                f"\n\n```python\n"
                f"# Инференс языковой модели через Hugging Face Transformers\n"
                f"from transformers import AutoModelForCausalLM, AutoTokenizer\n"
                f"import torch\n\n"
                f"model_name = \"{sample_model_id}\"\n"
                f"tokenizer = AutoTokenizer.from_pretrained(model_name)\n"
                f"model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16, device_map=\"auto\")\n"
                f"```\n"
            )
        else:
            snippet_section = (
                f"\n\n```python\n"
                f"# Быстрый запуск модели из каталога\n"
                f"from transformers import AutoModel\n\n"
                f"model = AutoModel.from_pretrained(\"{sample_model_id}\")\n"
                f"```\n"
            )
    elif "репозиторий" in found_categories and sample_repo_url and sample_repo_url != "#":
        snippet_section = (
            f"\n\n```bash\n"
            f"# Установка и запуск окружения репозитория\n"
            f"git clone {sample_repo_url}\n"
            f"cd $(basename {sample_repo_url} .git)\n"
            f"pip install -r requirements.txt\n"
            f"```\n"
        )
    elif "датасет" in found_categories and sample_dataset_title:
        snippet_section = (
            f"\n\n```python\n"
            f"# Загрузка датасета через библиотеку Datasets\n"
            f"from datasets import load_dataset\n\n"
            f"dataset = load_dataset(\"{sample_dataset_title}\")\n"
            f"print(dataset[\"train\"][0])\n"
            f"```\n"
        )

    # Дальнейшие шаги оформлены стандартным Markdown-списком с пустыми строками
    next_steps = (
        "\n\n💡 **Что мы можем сделать дальше?**\n\n"
        "- **Углубиться в архитектуру:** могу подробнее разобрать устройство и бенчмарки любой из этих карточек\n"
        "- **Подобрать смежные данные:** найти подходящие датасеты для дообучения или открытый код инференса\n"
        "- **Написать пайплайн:** составить готовый скрипт под вашу конкретную прикладную задачу\n\n"
        "Просто напишите, куда двигаемся дальше!"
    )

    full_response = f"{heading}\n\n{intro}\n\n{cards_section}{snippet_section}{next_steps}"
    return full_response


def process_dialogue(
    history: list[dict[str, str]],
    category_filter: str = "all",
    max_sources: int = 5,
    top_k: int | None = None,
) -> dict[str, Any]:
    """
    Основной метод обработки одного шага диалога в стиле Gemini с заземлением на данные Radar.

    :param history: список сообщений [{'role': 'user'|'assistant', 'content': '...'}, ...]
    :param category_filter: фильтр категории ('all', 'датасет', 'модель', и т.д.)
    :param max_sources: количество источников для поиска в базе
    :param top_k: обратная совместимость (alias для max_sources)
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
    prior_history = history[:-1]

    # --- 1. Проверка вопроса о контексте диалога ---
    if _is_context_query(last_user_msg):
        return {
            "role": "assistant",
            "content": _format_context_summary(prior_history),
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    # --- 2. Повседневное общение (смолл-ток) ---
    if _is_smalltalk(last_user_msg):
        return {
            "role": "assistant",
            "content": "Спасибо, всё отлично! Я на связи и готов помочь с анализом и подбором материалов в каталоге Radar Scout. Ищете модели, датасеты, открытые репозитории или статьи по конкретной задаче?",
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    # --- 3. Приветствия и благодарности ---
    if _is_greeting(last_user_msg):
        if len(history) <= 2:
            return {
                "role": "assistant",
                "content": (
                    "Привет! 👋 Я интеллектуальный AI-ассистент сервиса AI/ML Radar Scout.\n\n"
                    "Я работаю как современная экспертная модель и глубоко интегрирован с актуальной базой знаний:\n"
                    "• **Лидерборд LMSYS Arena** (рейтинги лучших LLM)\n"
                    "• **Модели Hugging Face** (трендовые релизы и RU-сегмент)\n"
                    "• **Датасеты** (Kaggle, Hugging Face Datasets)\n"
                    "• **Репозитории** (GitHub Trending)\n"
                    "• **Препринты и статьи** (ArXiv, Papers with Code)\n\n"
                    "Вы можете задать мне любой вопрос по машинному обучению или описать задачу "
                    "(например: *«подбери датасеты для сегментации медицинских снимков»*, *«какие открытые модели сейчас лидируют в CV и зрении?»* или *«найди репозитории по MLOps и vLLM»*) — и я помогу!"
                ),
                "action": "chat",
                "search_query": None,
                "cards": [],
                "error": None,
            }
        else:
            return {
                "role": "assistant",
                "content": "Привет! Чем могу помочь? Ищете модели, датасеты, открытые репозитории или статьи по конкретной теме?",
                "action": "chat",
                "search_query": None,
                "cards": [],
                "error": None,
            }

    if _is_thanks(last_user_msg):
        return {
            "role": "assistant",
            "content": "Рад помочь! Если появятся новые вопросы или понадобятся сравнения моделей и датасетов — обращайтесь! 🚀",
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    # --- 4. Определение контекста, домена и поискового запроса ---
    state = _analyze_dialogue_state(history)
    last_clean = re.sub(r"[^\w\s]", "", last_user_msg.lower()).strip()

    detected_cat = None
    for kw, cat in CATEGORY_KEYWORDS.items():
        if last_clean == kw or last_clean == f"а {kw}" or last_clean == f"покажи {kw}":
            detected_cat = cat
            break

    search_query = last_user_msg
    search_cat = category_filter if category_filter != "all" else state["active_category"]

    # Проверяем, является ли запрос уточнением предыдущей темы (follow-up)
    continuation_markers = {"а", "еще", "ещё", "также", "тоже", "для", "под", "легковесные", "русские", "ru", "сравни", "покажи", "найди"}
    first_word = last_clean.split()[0] if last_clean.split() else ""
    is_continuation_phrase = first_word in continuation_markers and len(last_user_msg.split()) <= 4

    if detected_cat:
        search_cat = detected_cat
        state["active_category"] = detected_cat
        prev_topics = _extract_conversation_topics(prior_history)
        if prev_topics:
            search_query = f"{' '.join(prev_topics[-2:])} {detected_cat}"
        else:
            search_query = f"{state['main_domain']} {detected_cat}"
        logger.info(f"Follow-up refinement: cat={search_cat}, query={search_query}")
    elif is_continuation_phrase:
        prev_topics = _extract_conversation_topics(prior_history)
        if prev_topics:
            search_query = f"{' '.join(prev_topics[-2:])} {last_user_msg}"
    else:
        # Самостоятельный содержательный запрос (например, «медицина», «yolo», «компьютерное зрение»)
        search_query = last_user_msg

    # --- 5. Векторный поиск по каталогу Radar ---
    results = rag_service.search_cards(
        query=search_query,
        category=search_cat,
        top_k=effective_limit,
        min_score=0.15,
    )
    # Если в узкой категории ничего не нашлось, автоматически ищем по всей базе (all)
    if not results and search_cat != "all":
        results = rag_service.search_cards(
            query=search_query,
            category="all",
            top_k=effective_limit,
            min_score=0.15,
        )
    cards = [r["card"] for r in results]

    # --- 6. Попытка вызова опционального внешнего LLM (если настроен) ---
    llm_answer = None
    if config.GEMINI_API_KEY or config.OPENAI_API_KEY or config.VLLM_BASE_URL:
        cards_context_blocks = []
        for i, r in enumerate(results, start=1):
            c = r["card"]
            score_pct = int(r["score"] * 100)
            tags_str = ", ".join(c.get("tags", []))
            summary_short = (c.get("summary") or "")[:450]
            cards_context_blocks.append(
                f"[{i}] {c.get('title')} (Категория: {c.get('category').upper()})\n"
                f"Релевантность: {score_pct}%\n"
                f"URL: {c.get('url')}\n"
                f"Теги: {tags_str}\n"
                f"Описание: {summary_short}\n"
            )

        window = history[-24:]
        llm_messages = [{"role": m["role"], "content": m["content"]} for m in window[:-1]]
        augmented_user_message = last_user_msg
        if cards_context_blocks:
            augmented_user_message += (
                "\n\n[МАТЕРИАЛЫ ИЗ КАТАЛОГА RADAR SCOUT ДЛЯ ОТВЕТА]:\n"
                + "\n---\n".join(cards_context_blocks)
                + "\n\nИспользуй эти материалы, дай развернутый ответ, сравни их и обязательно оформи кликабельные ссылки [Название](url). Не здоровайся повторно."
            )
        llm_messages.append({"role": "user", "content": augmented_user_message})

        llm_answer = _call_llm(
            messages=llm_messages,
            system_instruction=RADAR_AI_SYSTEM_INSTRUCTION,
            max_tokens=3500,
        )

    if llm_answer and llm_answer.strip():
        final_text = llm_answer.strip()
        if len(history) > 2:
            final_text = _strip_repeated_greetings(final_text)

        return {
            "role": "assistant",
            "content": final_text,
            "action": "search",
            "search_query": search_query,
            "cards": cards,
            "error": None,
        }

    # --- 7. Автономная локальная генерация ответа в стиле Gemini (без внешних нейросетей) ---
    local_expert_answer = _build_local_expert_response(
        search_query=search_query,
        dialogue_state=state,
        results=results,
        is_follow_up=bool(prior_history),
    )

    if len(history) > 2:
        local_expert_answer = _strip_repeated_greetings(local_expert_answer)

    return {
        "role": "assistant",
        "content": local_expert_answer,
        "action": "search",
        "search_query": search_query,
        "cards": cards,
        "error": None,
    }
