"""
Модуль интеллектуального диалогового агента Radar Scout на базе Qwen/Qwen3.6-27B.
Работает как полноценный автономный AI-чат через OpenAI-совместимый API vLLM,
понимает контекст диалога, подбирает релевантные сущности (модели, датасеты, статьи, код)
и обеспечивает естественное ведение многошаговой беседы без шаблонных повторений.
"""

from dataclasses import dataclass, field
import json
import logging
import os
import re
import time
from typing import Any

import httpx

import config
import database
import rag_service

logger = logging.getLogger("rag_agent")

# Кэш состояния онлайн-сервера vLLM для предотвращения задержек
_VLLM_STATUS: dict[str, Any] = {"online": None, "checked_at": 0.0}


# =========================================================================
# 1. ПРОВЕРКА ДОСТУПНОСТИ И ВЫЗОВ ЛОКАЛЬНОГО ИНФЕРЕНСА QWEN (vLLM)
# =========================================================================

def _is_vllm_online() -> bool:
    """
    Проверяет доступность vLLM сервера с кэшированием статуса на 20 секунд.
    """
    now = time.monotonic()
    if _VLLM_STATUS["online"] is not None and (now - _VLLM_STATUS["checked_at"] < 20.0):
        return _VLLM_STATUS["online"]

    base_url = (config.VLLM_BASE_URL or "http://192.168.10.65:8901/v1").rstrip("/")
    models_url = f"{base_url}/models"
    try:
        with httpx.Client(timeout=4.0) as client:
            headers = {}
            if config.VLLM_API_KEY and config.VLLM_API_KEY != "not-needed":
                headers["Authorization"] = f"Bearer {config.VLLM_API_KEY}"
            resp = client.get(models_url, headers=headers)
            is_ok = (resp.status_code == 200)
    except Exception as e:
        logger.warning(f"Сервер vLLM недоступен по {models_url}: {e}")
        is_ok = False

    _VLLM_STATUS["online"] = is_ok
    _VLLM_STATUS["checked_at"] = now
    return is_ok


def _clean_qwen_output(text: str) -> str:
    """
    Очищает ответ модели:
    1. Срезает любые шаблонные приветствия («Приветствую. Давай разберем...»).
    2. Срезает любые паразитные вступительные или заключительные оговорки о базе/чужих моделях.
    Ответ должен быть кристально чистым, глубоким и сразу по существу.
    """
    if not text:
        return text
    cleaned = text.strip()

    # 1. Срезаем приветствия
    greeting_pattern = (
        r"^\s*(?:"
        r"(?:Приветствую|Здравствуйте|Привет|Доброго\s+времени\s+суток)[!\.,]?\s*(?:Давай(?:те)?\s+[^.\n]+[.\n])?"
        r"|Давай(?:те)?\s+(?:разберем|проанализируем|сразу\s+проясним|рассмотрим|взглянем)[^.\n]*[.\n]"
        r")\s*"
    )
    for _ in range(3):
        m = re.match(greeting_pattern, cleaned, flags=re.IGNORECASE)
        if m:
            cleaned = cleaned[m.end():].lstrip()
        else:
            break

    # 2. Срезаем вступительные дисклеймеры о базе или о неподходящих материалах
    cleaned = re.sub(
        r"^\s*(?:В\s+(?:предоставленной|локальной)\s+базе[^\n]*(?:\n(?![0-9#\*\-]|Для|Ниже|Ключевые)[^\n]*)*\n+)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 3. Срезаем концевые предупреждения о неподходящих моделях в базе
    cleaned = re.sub(
        r"\n*\s*⚠️\s*Внимание:\s*Предложенные\s+ранее[^\n]*(?:\n[^\n]*)*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 4. Срезаем оправдательные фразы о неподходящих материалах из базы
    cleaned = re.sub(
        r"\n*\s*(?:Остальные|Другие)\s+материалы\s+из\s+базы[^\n]*?(?:относятся\s+к|выходят\s+за\s+рамки|не\s+являются)[^\n]*?(?:\n|$)",
        "\n",
        cleaned,
        flags=re.IGNORECASE,
    )

    return cleaned.strip() if cleaned.strip() else text


def call_qwen_chat(
    messages: list[dict[str, str]],
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> str | None:
    """
    Выполняет прямой вызов локальной модели Qwen через OpenAI-совместимый API vLLM (/chat/completions).
    Работает со всеми версиями vLLM без требований к сложным парсерам tool-calling.
    """
    base_url = (config.VLLM_BASE_URL or "http://192.168.10.65:8901/v1").rstrip("/")
    chat_url = f"{base_url}/chat/completions"
    model_name = config.VLLM_MODEL_NAME or "Qwen/Qwen3.6-27B"

    headers = {"Content-Type": "application/json"}
    if config.VLLM_API_KEY and config.VLLM_API_KEY != "not-needed":
        headers["Authorization"] = f"Bearer {config.VLLM_API_KEY}"

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # Таймаут: 15с на подключение (защита от кратковременных пауз vLLM) и 120с на чтение генерации
    timeout_cfg = httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0)
    try:
        logger.info(f"Запрос к Qwen ({model_name}) по {chat_url}, реплик: {len(messages)}")
        with httpx.Client(timeout=timeout_cfg) as client:
            resp = client.post(chat_url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                cleaned_content = _clean_qwen_output(content.strip())
                return cleaned_content
            else:
                logger.error(f"Ошибка vLLM HTTP {resp.status_code}: {resp.text[:400]}")
                return None
    except Exception as e:
        logger.error(f"Сбой прямого обращения к vLLM ({type(e).__name__}: {e})", exc_info=True)
        return None


# =========================================================================
# 2. СИСТЕМНЫЕ ПРОМПТЫ ДЛЯ ПЕРСОНЫ AI-АССИСТЕНТА
# =========================================================================

RADAR_CHAT_SYSTEM_PROMPT = """Ты — экспертный Senior AI/ML диалоговый ассистент каталога «AI/ML Radar Scout» на базе Qwen.
Твоя специализация:
- Архитектуры нейросетей и модели (Hugging Face, LMSYS Arena).
- Датасеты и корпуса данных (Hugging Face Datasets, Kaggle).
- Открытые репозитории с исходным кодом и утилитами (GitHub Trending).
- Исследовательские научные публикации и препринты (ArXiv, Papers with Code).

КАТЕГОРИЧЕСКИЙ ЗАПРЕТ НА ПРИВЕТСТВИЯ:
- ЗАПРЕЩЕНО писать любые приветствия («Привет», «Приветствую», «Здравствуйте», «Давай разберем», «Давай проанализируем», «Давай сразу проясним») в диалоге!
- Начинай КАЖДЫЙ свой ответ СРАЗУ ПО СУЩЕСТВУ ВОПРОСА С ПЕРВОГО СЛОВА (с фактов, рекомендаций, кода или структуры).

ПРИНЦИПЫ И ЧЕТКАЯ ИЗОЛЯЦИЯ ТЕМ:
1. Веди живой, глубокий технический разговор как Senior AI/ML Engineer.
2. Помни историю диалога и активную архитектуру/модель, о которой идет речь.
3. ПРИ ЗАПРОСЕ СТАТЕЙ И ИССЛЕДОВАНИЙ («статьи», «исследования», «papers», «arxiv», «публикации»):
   - Отвечай ИСКЛЮЧИТЕЛЬНО научными статьями, публикациями и препринтами ArXiv, релевантными архитектуре и модальности обсуждаемой модели.
   - Для каждой статьи указывай авторов/лабораторию, кликабельную ссылку [Название](https://arxiv.org/abs/...) и её значение для понимания архитектуры.
   - СТРОЖАЙШЕ ЗАПРЕЩЕНО упоминать, перечислять или обсуждать посторонние модели или генераторы медиа!
4. ПРИ ЗАПРОСЕ ДАТАСЕТОВ («датасет», «на чем обучить», «данные», «выборка»):
   - Рекомендуй ИСКЛЮЧИТЕЛЬНО датасеты и обучающие корпуса данных под задачу и модальность модели.
   - Приводи кликабельные ссылки на датасеты [Название](https://huggingface.co/datasets/...) или Kaggle и структуру формата данных (JSONL).
   - Никогда не называй модели датасетами и не предлагай обучать модель на модели.
5. ЗАПРЕЩЕНО оправдываться или обсуждать посторонние материалы, которых нет в вопросе пользователя. Если локальная база каталога не содержит специализированных статей по конкретной редкой архитектуре — сразу называй общепризнанные мировые публикации с ArXiv.
6. Для всех упоминаемых материалов формируй понятные кликабельные Markdown-ссылки [Название](url).
7. Форматируй ответ в аккуратном GitHub Flavored Markdown (структурированные списки, выделения, блоки кода с подсветкой синтаксиса).
"""


# =========================================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОЧИСТКИ И ФОРМАТИРОВАНИЯ
# =========================================================================

def _clean_card_title(raw_title: str) -> str:
    """Удаляет вложенные квадратные скобки [[Kaggle] Title] для корректного Markdown."""
    if not raw_title:
        return "Материал"
    clean = re.sub(r"^\[(.*?)\]\s*", r"\1: ", raw_title.strip())
    clean = clean.replace("[", "(").replace("]", ")")
    return re.sub(r"\s+", " ", clean).strip()


def _format_single_card_for_ui(c: dict[str, Any]) -> dict[str, Any]:
    """Форматирует единственную карточку для аккуратного отображения под сообщением."""
    clean_title = _clean_card_title(c.get("title", "Материал"))
    summary = c.get("summary") or c.get("full_description") or ""
    if len(summary) > 280:
        summary = summary[:280].rstrip() + "..."
    return {
        "id": str(c.get("id", "")),
        "title": clean_title,
        "category": c.get("category", "материал"),
        "url": c.get("url") or c.get("source_url") or "",
        "summary": summary,
        "tags": c.get("tags", [])[:6] if isinstance(c.get("tags"), list) else [],
        "metrics": c.get("metrics") or {},
        "similarity": round(float(c.get("similarity", 0.95)), 2),
    }


def _is_short_conversational(text: str) -> bool:
    """Определяет, является ли реплика короткой разговорной фразой ('да', 'нет', 'привет', 'ок', 'спасибо')."""
    cleaned = re.sub(r"[^\w\s]", "", text.strip().lower())
    words = cleaned.split()
    if not words:
        return True

    conversational_words = {
        "да", "давай", "ок", "хорошо", "ага", "конечно", "yes", "yep", "sure",
        "нет", "не", "не надо", "no", "nope",
        "спасибо", "благодарю", "thanks", "сенкс", "круто", "супер", "отлично", "класс",
        "привет", "здравствуй", "здравствуйте", "добрый день", "хай", "hello", "hi",
        "понял", "ясно", "clear", "got it", "понятно",
        "как дела", "как ты", "что нового",
    }

    if len(words) <= 3 and (" ".join(words) in conversational_words or words[0] in conversational_words):
        return True

    return False


def _is_context_query(text: str) -> bool:
    """Определяет, просит ли пользователь вспомнить историю диалога."""
    cleaned = re.sub(r"[^\w\s]", " ", text.strip().lower())
    cleaned = " ".join(cleaned.split())
    patterns = [
        "что мы обсуждали", "что обсуждали", "о чем мы говорили", "о чем говорили",
        "о чем шла речь", "напомни контекст", "напомни о чем", "что было раньше",
        "что было ранее", "какой контекст", "история диалога", "что делали", "что мы делали",
        "о чем этот чат", "что ты мне советовал", "что советовал",
    ]
    if any(p in cleaned for p in patterns):
        return True
    return bool(re.search(r"(что|о чем).*(мы\s+)?(обсуждали|говорили|спрашивал|делали)|напомни.*(контекст|диалог|истори)", cleaned))


def _format_context_summary(history_turns: list[dict[str, str]]) -> str:
    """Формирует понятную сводку тем диалога."""
    if not history_turns:
        return (
            "В этом диалоге мы ещё ничего не обсуждали — это совершенно новый диалог!\n\n"
            "Задайте любой интересующий вас вопрос по каталогу:\n"
            "• **Модели** (Hugging Face, рейтинги LMSYS Arena)\n"
            "• **Датасеты** (Kaggle, Hugging Face Datasets)\n"
            "• **Репозитории** (GitHub Trending)\n"
            "• **Научные статьи** (ArXiv, Papers with Code)"
        )

    user_topics = []
    for m in history_turns:
        if m.get("role") == "user":
            txt = m.get("content", "").strip()
            if not _is_short_conversational(txt) and not _is_context_query(txt):
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

    topic_str = ", ".join(unique_topics) if unique_topics else "машинное обучение и поиск в каталоге"
    return (
        f"**Краткая выжимка нашего диалога:**\n\n"
        f"В этом диалоге мы исследовали задачи и подбирали материалы по темам: **{topic_str}**.\n\n"
        f"Все найденные карточки зафиксированы в этой вкладке чата. Вы можете продолжить эту тему или задать новый вопрос!"
    )


def _detect_target_card(
    query: str,
    category_filter: str = "all",
    card_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Определяет, относится ли запрос к конкретной карточке.
    """
    if card_context and isinstance(card_context, dict) and card_context.get("title"):
        title = card_context.get("title", "").strip()
        db_card = rag_service.get_card_by_title_or_id(title, category=category_filter)
        if not db_card and card_context.get("id"):
            db_card = rag_service.get_card_by_title_or_id(card_context["id"], category=category_filter)

        merged = dict(card_context)
        if db_card:
            for k in ("full_description", "summary", "details", "tags", "metrics", "url", "category"):
                if db_card.get(k) and (not merged.get(k) or len(str(merged.get(k))) < len(str(db_card.get(k)))):
                    merged[k] = db_card[k]
        return merged

    # Поиск по кавычкам или паттернам
    quotes = re.findall(r'["«]([^"»\n]+)["»]', query)
    candidates = list(quotes)

    patterns = [
        r'(?:про модель|о модели|модель|обзор модели)\s+([a-zA-Z0-9_\-\.\/]+)',
        r'(?:обзор датасета|датасет|про датасет|о датасете)\s+["«]?([a-zA-Z0-9_\-\.\/]+)["«]?',
        r'(?:разбор статьи|статья|про статью|о статье)\s+["«]?([^"»:\n]+)["«]?',
        r'(?:про репозиторий|репозиторий|о репозитории|репо)\s+["«]?([^"»:\n]+)["«]?',
        r'\b([a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+)\b',
    ]
    for p in patterns:
        m = re.search(p, query, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            if cand and cand not in candidates:
                candidates.append(cand)

    for cand in candidates:
        found = rag_service.get_card_by_title_or_id(cand, category=category_filter)
        if found:
            return found

    return None


def _find_active_subject_from_history(
    history: list[dict[str, str]],
    card_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Находит активный обсуждаемый объект (в первую очередь целевую модель диалога).
    """
    if card_context and isinstance(card_context, dict) and card_context.get("title"):
        found = rag_service.get_card_by_title_or_id(card_context["title"])
        if found:
            return found
        if card_context.get("id"):
            found = rag_service.get_card_by_title_or_id(card_context["id"])
            if found:
                return found
        return card_context

    if not history:
        return None

    # 1. Поиск модели в самом первом сообщении (корень текущей вкладки)
    first_msg = history[0].get("content", "")
    for pattern in [
        r"(?:про модель|о модели|модель|обзор модели)\s+([a-zA-Z0-9_\-\.\/]+)",
        r"\b([a-zA-Z0-9_\-\.]+\/[a-zA-Z0-9_\-\.]+)\b",
    ]:
        m = re.search(pattern, first_msg, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            found = rag_service.get_card_by_title_or_id(cand)
            if found and found.get("category") == "модель":
                return found

    # 2. Поиск модели во всей истории сообщений (от новых к старым)
    for msg in reversed(history):
        cnt = msg.get("content", "")
        if not cnt:
            continue

        # Заголовок обзора
        m = re.search(r"##\s*📌\s*Развёрнутый\s*технический\s*обзор:\s*\[([^\]]+)\]", cnt)
        if m:
            cand = m.group(1).strip()
            found = rag_service.get_card_by_title_or_id(cand)
            if found:
                return found

        # Упоминание модели
        m = re.search(r"(?:про модель|о модели|модель|обзор модели)\s+([a-zA-Z0-9_\-\.\/]+)", cnt, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            found = rag_service.get_card_by_title_or_id(cand)
            if found and found.get("category") == "модель":
                return found

        # Hugging Face model id
        m = re.search(r"\b([a-zA-Z0-9_\-\.]+\/[a-zA-Z0-9_\-\.]+)\b", cnt)
        if m:
            cand = m.group(1).strip()
            found = rag_service.get_card_by_title_or_id(cand)
            if found and found.get("category") == "модель":
                return found

    # 3. Если модель не найдена — любая карточка
    for msg in reversed(history):
        cnt = msg.get("content", "")
        m = re.search(r"\b([a-zA-Z0-9_\-\.]+\/[a-zA-Z0-9_\-\.]+)\b", cnt)
        if m:
            cand = m.group(1).strip()
            found = rag_service.get_card_by_title_or_id(cand)
            if found:
                return found

    return None


def _detect_followup_intent(user_msg: str, active_card: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Определяет, является ли вопрос развитием темы вокруг активного объекта.
    Учитывает русскую морфологию и падежи: датасет, датасета, датасете, датасету, датасетов,
    статьи, статей, публикации, исследования, arxiv, papers,
    обучить, дообучить, fine-tuning, данные, корпус, разметка.
    """
    if not active_card:
        return None

    clean_msg = user_msg.lower().strip()

    # 1. Запрос ДАТАСЕТА для модели:
    # «а на каком датасете обучить эту модель», «какой датасет пойдет», «данные для обучения», «чем дообучить»
    if re.search(r"(датасет\w*|данн\w*|выборк\w*|корпус\w*|разметк\w*|обуч\w*|дообуч\w*|трениров\w*|файнтюн\w*|fine[- ]?tun\w*)", clean_msg):
        return {"type": "dataset", "category": "датасет"}

    # 2. Запрос НАУЧНЫХ СТАТЕЙ / ПУБЛИКАЦИЙ / ИССЛЕДОВАНИЙ для модели:
    # «а накинь мне статей под это все», «какие статьи почитать», «исследования», «papers», «arxiv», «публикации»
    if re.search(r"(стать\w*|paper\w*|исследован\w*|публикац\w*|arxiv\b)", clean_msg):
        return {"type": "papers", "category": "статья"}

    # 3. Запрос РЕКОМЕНДАЦИЙ В СВЯЗКЕ / ЧТО ЕЩЕ («что еще посоветуешь к этой модели», «с чем использовать»)
    if re.search(r"(что еще|что ещё|посоветуй\w*|дополн\w*|в связке|пайплайн|стек|экосистем\w*)", clean_msg):
        return {"type": "ecosystem", "category": "all"}

    # 4. Запрос КОДА / ЗАПУСКА
    if re.search(r"(как запустить|как развернуть|как использовать|покажи код|пример кода|код запуска|инференс|скрипт)", clean_msg):
        return {"type": "code", "category": active_card.get("category", "модель")}

    # 5. Запрос ТРЕБОВАНИЙ К ЖЕЛЕЗУ / VRAM
    if re.search(r"(сколько памяти|какая видеокарта|требования|vram|видеопамят|потянет ли|на каком железе|gpu)", clean_msg):
        return {"type": "hardware", "category": active_card.get("category", "модель")}

    # 6. Запрос АНАЛОГОВ / АЛЬТЕРНАТИВ
    if re.search(r"(аналог\w*|похож\w*|альтернатив\w*|с чем сравнить|конкурент\w*)", clean_msg):
        return {"type": "alternatives", "category": active_card.get("category", "модель")}

    return None


def _generate_code_snippet(card: dict[str, Any]) -> str:
    """Генерирует специализированный, рабочий кодовый шаблон запуска."""
    clean_title = _clean_card_title(card.get("title", "Материал"))
    cat = (card.get("category") or "материал").lower()
    details = card.get("details") or {}
    tags = [str(t).lower() for t in (card.get("tags") or [])]
    p_tag = str(details.get("pipeline_tag") or "").lower()
    lib = str(details.get("library_name") or "").lower()

    if cat == "модель":
        if (
            "automatic-speech-recognition" in p_tag
            or "speech" in p_tag
            or "audio" in p_tag
            or "nemo" in lib
            or "nemo" in tags
            or "nemotron" in clean_title.lower()
        ):
            if "nemo" in lib or "nemotron" in clean_title.lower() or "nemo" in tags:
                return (
                    "```python\n"
                    "# Установка: pip install nemo_toolkit['asr'] torch torchaudio\n"
                    "import nemo.collections.asr as nemo_asr\n\n"
                    f'model_id = "{clean_title}"\n'
                    "print(f'Загрузка модели NeMo ASR: {model_id}...')\n"
                    "model = nemo_asr.models.ASRModel.from_pretrained(model_id)\n\n"
                    "# Транскрибация аудиозаписи (WAV/FLAC 16 kHz)\n"
                    "transcriptions = model.transcribe(['audio_sample.wav'])\n"
                    "print('Результат транскрипции:', transcriptions[0])\n"
                    "```"
                )
            return (
                "```python\n"
                "# Установка: pip install transformers torch torchaudio accelerate\n"
                "import torch\n"
                "from transformers import pipeline\n\n"
                f'model_id = "{clean_title}"\n'
                'device = "cuda:0" if torch.cuda.is_available() else "cpu"\n'
                "asr_pipe = pipeline(\n"
                '    "automatic-speech-recognition",\n'
                "    model=model_id,\n"
                "    torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,\n"
                "    device=device,\n"
                ")\n\n"
                "result = asr_pipe('audio_sample.wav', return_timestamps=True)\n"
                "print('Текст транскрипции:', result['text'])\n"
                "```"
            )

        if "image-to-text" in p_tag or "visual-question-answering" in p_tag or "vision" in tags or "image" in p_tag:
            return (
                "```python\n"
                "# Установка: pip install transformers pillow torch accelerate\n"
                "import torch\n"
                "from PIL import Image\n"
                "from transformers import AutoProcessor, AutoModelForVision2Seq\n\n"
                f'model_id = "{clean_title}"\n'
                "processor = AutoProcessor.from_pretrained(model_id)\n"
                "model = AutoModelForVision2Seq.from_pretrained(\n"
                "    model_id, torch_dtype=torch.bfloat16, device_map='auto'\n"
                ")\n"
                "image = Image.open('sample.jpg')\n"
                "inputs = processor(text='<image>\\nОпиши изображение.', images=image, return_tensors='pt').to('cuda')\n"
                "outputs = model.generate(**inputs, max_new_tokens=150)\n"
                "print(processor.decode(outputs[0], skip_special_tokens=True))\n"
                "```"
            )

        return (
            "```python\n"
            "# Установка: pip install transformers torch accelerate\n"
            "import torch\n"
            "from transformers import AutoModelForCausalLM, AutoTokenizer\n\n"
            f'model_id = "{clean_title}"\n'
            "tokenizer = AutoTokenizer.from_pretrained(model_id)\n"
            "model = AutoModelForCausalLM.from_pretrained(\n"
            "    model_id, torch_dtype=torch.bfloat16, device_map='auto'\n"
            ")\n"
            "inputs = tokenizer('Привет! Расскажи о своих возможностях.', return_tensors='pt').to('cuda')\n"
            "outputs = model.generate(**inputs, max_new_tokens=256)\n"
            "print(tokenizer.decode(outputs[0], skip_special_tokens=True))\n"
            "```"
        )

    elif cat == "датасет":
        return (
            "```python\n"
            "# Установка: pip install datasets\n"
            "from datasets import load_dataset\n\n"
            f'dataset = load_dataset("{clean_title}")\n'
            "print('Сплиты:', list(dataset.keys()))\n"
            "print(dataset['train'][0] if 'train' in dataset else dataset)\n"
            "```"
        )
    elif cat == "репозиторий":
        repo_dir = clean_title.split("/")[-1]
        return (
            "```bash\n"
            f"git clone https://github.com/{clean_title}.git\n"
            f"cd {repo_dir}\n"
            "pip install -r requirements.txt\n"
            "```"
        )
    else:
        return (
            "```python\n"
            "# Первоисточник исследовательской публикации:\n"
            f'# {card.get("url") or "https://arxiv.org"}\n'
            "```"
        )


def _build_detailed_card_breakdown(card: dict[str, Any]) -> str:
    """
    Формирует развёрнутый технический разбор карточки без сырого JSON.
    """
    clean_title = _clean_card_title(card.get("title", "Материал"))
    cat = (card.get("category") or "материал").lower()
    url = card.get("url") or card.get("source_url") or "#"
    tags = card.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    metrics = card.get("metrics") or {}
    details = card.get("details") or {}

    full_desc = (card.get("full_description") or card.get("summary") or "").strip()
    summary = (card.get("summary") or "").strip()

    meta, clean_text = rag_service.parse_hf_metadata(full_desc)
    if meta:
        full_desc = rag_service.build_human_readable_full_description(
            title=clean_title,
            summary=summary or clean_text,
            meta=meta,
            clean_text=clean_text,
            details=details,
        )
    elif full_desc.startswith("---") and "---" in full_desc[3:]:
        parts = full_desc[3:].split("---", 1)
        if len(parts) > 1:
            full_desc = parts[1].strip()

    meta_badges = []
    if cat == "модель":
        meta_badges.append("📂 **МОДЕЛЬ**")
        if details.get("parameters"):
            meta_badges.append(f"🧠 **Параметры:** `{details['parameters']}`")
        if details.get("pipeline_tag"):
            meta_badges.append(f"🎯 **Задача:** `{details['pipeline_tag']}`")
        if details.get("license"):
            meta_badges.append(f"📜 **Лицензия:** `{details['license']}`")
        if metrics.get("downloads"):
            meta_badges.append(f"📥 **{metrics['downloads']:,} скачиваний**")
        if metrics.get("likes"):
            meta_badges.append(f"❤️ **{metrics['likes']:,} лайков**")
    elif cat == "датасет":
        meta_badges.append("📂 **ДАТАСЕТ**")
        if metrics.get("stars"):
            meta_badges.append(f"⭐ **{metrics['stars']} upvotes**")
    elif cat == "репозиторий":
        meta_badges.append("📂 **РЕПОЗИТОРИЙ**")
        if metrics.get("stars"):
            meta_badges.append(f"⭐ **{metrics['stars']:,} stars**")
    else:
        meta_badges.append("📂 **НАУЧНАЯ СТАТЬЯ**")

    badges_str = " · ".join(meta_badges)
    tags_str = ", ".join([f"`{t}`" for t in tags[:7]]) if tags else "ML/AI"

    sections = [
        f"## 📌 Развёрнутый технический обзор: [{clean_title}]({url})\n\n{badges_str}",
        f"🏷️ **Ключевые теги:** {tags_str}",
    ]

    # 1. Архитектурный контекст
    if cat == "модель":
        p_tag = details.get("pipeline_tag") or "machine learning"
        params = details.get("parameters") or ""
        base_m = details.get("base_model") or ""
        ctx_bullets = [
            f"- **Назначение:** автоматизация и высокопроизводительное решение задач класса `{p_tag}`.",
            f"- **Стек и окружение:** архитектура семейства `{clean_title.split('/')[-1]}`, фреймворк `{details.get('library_name') or 'PyTorch / Transformers'}`.",
        ]
        if params:
            ctx_bullets.append(f"- **Вычислительный объём:** масштаб параметров `{params}`.")
        if base_m:
            ctx_bullets.append(f"- **Основа весов:** обучена на фундаменте базовой модели `{base_m}`.")
        sections.append("### 1. Архитектурный контекст и профиль задачи\n" + "\n".join(ctx_bullets))
    elif cat == "датасет":
        sections.append(
            "### 1. Профиль данных и область задач\n"
            f"- **Назначение:** обучающая и валидационная выборка для задач в области {tags_str}.\n"
            f"- **Платформа публикации:** {details.get('platform') or 'Hugging Face Datasets / Kaggle'}."
        )
    elif cat == "репозиторий":
        sections.append(
            "### 1. Назначение и экосистема инструмента\n"
            f"- **Репозиторий:** `github.com/{clean_title}`.\n"
            f"- **Стек разработки:** язык `{details.get('language') or 'Python'}`."
        )
    else:
        sections.append(
            "### 1. Научный контекст публикации\n"
            f"- **Тематика исследования:** {tags_str}.\n"
            f"- **Источник статьи:** [{clean_title}]({url})."
        )

    # 2. Описание первоисточника
    sections.append(f"### 2. Развёрнутое описание первоисточника\n{full_desc}")

    # 3. Характеристики и окружение
    if cat == "модель":
        params_str = str(details.get("parameters") or "").upper()
        if "52B" in params_str or "50B" in params_str or "30B" in params_str or "27B" in params_str or "32B" in params_str:
            vram_rec = "FP16/BF16 требует ~60–110 ГБ VRAM (2× A100/H100 80GB). В 4-битном квантовании (AWQ/GPTQ/GGUF) запускается на 24–40 ГБ VRAM (RTX 3090/4090 24GB)."
        elif "70B" in params_str or "72B" in params_str:
            vram_rec = "FP16 требует ~140 ГБ VRAM (2× A100 80GB). В 4-битном квантовании помещается в 40–48 ГБ VRAM."
        elif "7B" in params_str or "8B" in params_str or "9B" in params_str:
            vram_rec = "FP16/BF16 требует ~14–16 ГБ VRAM. В 4-битном квантовании запускается в 6–8 ГБ VRAM."
        else:
            vram_rec = "Рекомендуется инференс на GPU с FP16/BF16 или квантование (AWQ/GPTQ/GGUF)."

        lic = details.get("license") or "open-access / custom"
        sections.append(
            "### 3. Технические характеристики и окружение\n"
            f"- **Семейство весов / архитектура:** `{clean_title}`\n"
            f"- **Тип пайплайна:** `{details.get('pipeline_tag') or 'machine learning'}`\n"
            f"- **Лицензия:** `{lic}`\n"
            f"- **Требования к оборудованию:** {vram_rec}"
        )
    else:
        sections.append("### 3. Спецификация и применение\n- Готово к использованию в прикладных пайплайнах.")

    # 4. Код запуска
    code_block = _generate_code_snippet(card)
    sections.append(f"### 4. Инструкция по запуску и кодовый шаблон\n{code_block}")

    # 5. Первоисточник
    sections.append(f"### 5. Первоисточник\n🔗 Прямая ссылка на материал: [{clean_title}]({url})")

    return "\n\n".join(sections)


# =========================================================================
# 4. ОСНОВНОЙ ДИАЛОГОВЫЙ ДВИЖОК: process_dialogue
# =========================================================================

def process_dialogue(
    history: list[dict[str, str]],
    category_filter: str = "all",
    max_sources: int = 5,
    top_k: int | None = None,
    card_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Основная точка входа для общения с AI-ассистентом Radar Scout:
    - Работает на базе локальной языковой модели Qwen/Qwen3.6-27B через vLLM.
    - Ведёт осмысленный многошаговый диалог, помнит контекст и сущность обсуждения.
    - На вопросы о датасетах («на каком датасете обучить») выдаёт ИСКЛЮЧИТЕЛЬНО датасеты под задачу.
    - На вопросы о статьях («накинь статей под это все») выдаёт ИСКЛЮЧИТЕЛЬНО научные статьи.
    - Категорически не спамит приветствиями («Приветствую», «Давай разберем») в каждом сообщении.
    """
    effective_limit = top_k if top_k is not None else max_sources

    if not history:
        return {
            "role": "assistant",
            "content": "Здравствуйте! Чем могу помочь? Ищете модели, датасеты, репозитории или статьи в Radar Scout?",
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    last_user_msg = history[-1]["content"].strip()
    prior_history = history[:-1]

    # ---------------------------------------------------------------------
    # ШАГ 1: Определение активного объекта обсуждения
    # ---------------------------------------------------------------------
    target_card = _detect_target_card(
        query=last_user_msg,
        category_filter=category_filter,
        card_context=card_context,
    )
    active_subject = target_card or _find_active_subject_from_history(history, card_context)

    # ---------------------------------------------------------------------
    # ШАГ 2: Обработка мета-запроса («что мы обсуждали ранее?»)
    # ---------------------------------------------------------------------
    if _is_context_query(last_user_msg):
        return {
            "role": "assistant",
            "content": _format_context_summary(prior_history),
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    # ---------------------------------------------------------------------
    # ШАГ 3: Запрос полного технического обзора («Спросить ассистента» в UI)
    # ---------------------------------------------------------------------
    is_initial_breakdown = (
        target_card is not None
        and (
            len(history) == 1
            or last_user_msg.startswith("Расскажи подробно про")
            or last_user_msg.startswith("Сделай технический обзор")
        )
    )

    if is_initial_breakdown and target_card:
        clean_title = _clean_card_title(target_card.get("title", "Материал"))
        ui_card = _format_single_card_for_ui(target_card)

        full_breakdown_prompt = _build_detailed_card_breakdown(target_card)
        llm_messages = [
            {"role": "system", "content": RADAR_CHAT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Сформируй глубокий технический обзор для материала «{clean_title}» из каталога Radar Scout:\n\n"
                    f"{full_breakdown_prompt}\n\n"
                    f"СТРОЖАЙШИЕ ТРЕБОВАНИЯ:\n"
                    f"1. НАЧИНАЙ СРАЗУ с сути (с заголовка или предупреждения). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать «Приветствую», «Давай разберем»!\n"
                    f"2. Твой ответ должен быть посвящен ИСКЛЮЧИТЕЛЬНО материалу «{clean_title}». Запрещено рекомендовать другие модели/датасеты.\n"
                    f"3. Запрещено выводить сырой JSON. Используй чистый русский язык и аккуратный GitHub Markdown.\n"
                    f"4. Разбери архитектуру, модальность, назначение, требования к GPU/памяти и предоставь рабочий кодовый пример запуска.\n"
                    f"5. Если модель мультимодальная (image-text-to-text, VLM) — укажи на использование AutoProcessor / AutoModelForVision2Seq."
                ),
            },
        ]

        qwen_reply = call_qwen_chat(llm_messages, temperature=0.3)
        final_content = qwen_reply if qwen_reply else full_breakdown_prompt

        return {
            "role": "assistant",
            "content": final_content,
            "action": "card_detail",
            "search_query": clean_title,
            "cards": [ui_card],
            "error": None,
        }

    # ---------------------------------------------------------------------
    # ШАГ 4: Короткая разговорная реплика («да», «нет», «спасибо», «ок»)
    # ---------------------------------------------------------------------
    if _is_short_conversational(last_user_msg):
        llm_messages = [{"role": "system", "content": RADAR_CHAT_SYSTEM_PROMPT}]
        for m in history:
            llm_messages.append({"role": m["role"], "content": m["content"]})

        context_hint = ""
        if active_subject:
            c_t = _clean_card_title(active_subject.get("title", ""))
            context_hint = f" В фокусе диалога находится объект «{c_t}»."

        llm_messages.append({
            "role": "system",
            "content": (
                f"[Инструкция]: Пользователь ответил коротко: «{last_user_msg}».{context_hint} "
                f"Ответь дружелюбно и профессионально по теме разговора без вступительных приветствий ('Приветствую'). "
                f"Предложи следующие конкретные шаги (запуск кода, расчет VRAM, подбор обучающих датасетов). "
                f"НИКОГДА не повторяй заново весь технический обзор карточки!"
            ),
        })

        qwen_reply = call_qwen_chat(llm_messages, temperature=0.5, max_tokens=500)
        if qwen_reply:
            return {
                "role": "assistant",
                "content": qwen_reply,
                "action": "chat",
                "search_query": None,
                "cards": [],
                "error": None,
            }

        subj_name = _clean_card_title(active_subject.get("title", "этой модели")) if active_subject else "выбранного материала"
        return {
            "role": "assistant",
            "content": (
                f"Чем именно могу помочь по **{subj_name}**?\n\n"
                f"Могу подробно разобрать:\n"
                f"• **Запуск и код:** готовый скрипт инференса или интеграции в пайплайн\n"
                f"• **Железо и VRAM:** расчет памяти, подбор квантования (AWQ, GGUF)\n"
                f"• **Датасеты:** подбор обучающих корпусов под эту задачу"
            ),
            "action": "chat",
            "search_query": None,
            "cards": [],
            "error": None,
        }

    # ---------------------------------------------------------------------
    # ШАГ 5: Уточняющий вопрос по активной карточке (датасеты, статьи, код, железо, экосистема)
    # ---------------------------------------------------------------------
    followup_intent = _detect_followup_intent(last_user_msg, active_subject)

    # 5.1: Пользователь спрашивает ДАТАСЕТЫ для активной модели («на каком датасете обучить эту модель»)
    if active_subject and followup_intent and followup_intent.get("type") == "dataset":
        clean_title = _clean_card_title(active_subject.get("title", "Модель"))
        url = active_subject.get("url") or active_subject.get("source_url") or "#"
        details = active_subject.get("details") or {}
        p_tag = str(details.get("pipeline_tag") or "").lower()
        tags = active_subject.get("tags") or []
        tags_str = ", ".join([str(t) for t in tags[:6]]) if tags else p_tag

        dataset_cards: list[dict[str, Any]] = []
        context_cards_text: list[str] = []

        # 1. Извлекаем официальные обучающие датасеты из метаданных модели
        known_datasets = details.get("datasets") or []
        if isinstance(known_datasets, str):
            try:
                known_datasets = json.loads(known_datasets)
            except Exception:
                known_datasets = [known_datasets]

        if isinstance(known_datasets, list):
            for kd in known_datasets:
                kd_url = f"https://huggingface.co/datasets/{kd}"
                context_cards_text.append(f"- **[{kd}]({kd_url})** (Официальный обучающий корпус)")
                dataset_cards.append({
                    "id": f"ds_{kd}",
                    "title": str(kd),
                    "category": "датасет",
                    "url": kd_url,
                    "summary": f"Официальный обучающий корпус для {clean_title}.",
                    "tags": ["official", "dataset"],
                    "metrics": {"stars": 150},
                    "similarity": 1.0,
                })

        # 2. Поиск датасетов строго в категории 'датасет' в локальной базе
        raw_results = rag_service.search_cards(
            query=f"{clean_title} {p_tag} {tags_str} dataset датасет",
            category="датасет",
            top_k=effective_limit,
            min_score=0.25,
        )
        for r in raw_results:
            c = r["card"]
            c_title = _clean_card_title(c.get("title", "Датасет"))
            if c_title in [d.get("title") for d in dataset_cards]:
                continue
            formatted = _format_single_card_for_ui(c)
            dataset_cards.append(formatted)
            context_cards_text.append(f"- **[{formatted['title']}]({formatted['url']})**: {formatted['summary']}")

        llm_messages = [{"role": "system", "content": RADAR_CHAT_SYSTEM_PROMPT}]
        for m in history[-4:-1]:
            llm_messages.append({"role": m["role"], "content": m["content"]})

        db_hint = ""
        if context_cards_text:
            db_hint = "Датасеты из локального каталога:\n" + "\n".join(context_cards_text[:7]) + "\n\n"

        prompt_content = (
            f"Вопрос пользователя: «{last_user_msg}» для модели **[{clean_title}]({url})**.\n"
            f"Задача и модальность модели: `{p_tag or 'deep learning'}`. Теги: {tags_str}.\n\n"
            f"{db_hint}"
            f"ТРЕБОВАНИЯ К ОТВЕТУ:\n"
            f"1. Начинай СРАЗУ по существу, без приветствий («Приветствую» и т.п.)!\n"
            f"2. Рекомендуй ИСКЛЮЧИТЕЛЬНО ДАТАСЕТЫ (data/datasets) под эту задачу и модальность.\n"
            f"3. Для каждого датасета дай кликабельную ссылку [Название](https://huggingface.co/datasets/...) или Kaggle, опиши структуру и формат данных (JSONL).\n"
            f"4. СТРОЖАЙШЕ ЗАПРЕЩЕНО называть модели датасетами или обсуждать посторонние сущности, которых нет в вопросе!"
        )
        llm_messages.append({"role": "user", "content": prompt_content})

        qwen_reply = call_qwen_chat(llm_messages, temperature=0.3)
        if qwen_reply:
            cleaned_reply = _clean_qwen_output(qwen_reply)

            # Извлекаем ссылки на HF / Kaggle датасеты для UI карточек
            extracted_ds = re.findall(r'\[([^\]]{4,})\]\((https?://(?:huggingface\.co/datasets|kaggle\.com/datasets)[^\)]+)\)', cleaned_reply)
            for ds_title, ds_url in extracted_ds[:effective_limit]:
                clean_ds_title = _clean_card_title(ds_title)
                if clean_ds_title not in [d["title"] for d in dataset_cards]:
                    dataset_cards.append({
                        "id": f"ds_{abs(hash(ds_url)) % 1000000}",
                        "title": clean_ds_title,
                        "category": "датасет",
                        "url": ds_url.strip(),
                        "summary": f"Обучающий датасет для {clean_title}.",
                        "tags": ["dataset", "fine-tuning"],
                        "metrics": {"stars": 150},
                        "similarity": 0.95,
                    })

            return {
                "role": "assistant",
                "content": cleaned_reply,
                "action": "search",
                "search_query": f"датасеты для {clean_title}",
                "cards": dataset_cards[:effective_limit],
                "error": None,
            }

        # Резервный ответ при оффлайн LLM
        blocks = []
        for i, dc in enumerate(dataset_cards[:effective_limit], start=1):
            blocks.append(
                f"#### {i}. [{dc['title']}]({dc['url']})\n\n"
                f"📂 **ДАТАСЕТ**\n\n"
                f"{dc['summary']}\n"
            )
        resp_text = (
            f"### 📊 Датасеты для дообучения [{clean_title}]({url})\n\n"
            f"Для обучения и валидации **[{clean_title}]({url})** рекомендуются следующие датасеты:\n\n"
            + "\n\n---\n\n".join(blocks)
        )
        return {
            "role": "assistant",
            "content": resp_text,
            "action": "search",
            "search_query": f"датасеты для {clean_title}",
            "cards": dataset_cards[:effective_limit],
            "error": None,
        }

    # 5.2: Пользователь спрашивает НАУЧНЫЕ СТАТЬИ / ПУБЛИКАЦИИ («накинь мне статей под это все»)
    if active_subject and followup_intent and followup_intent.get("type") == "papers":
        clean_title = _clean_card_title(active_subject.get("title", "Модель"))
        url = active_subject.get("url") or active_subject.get("source_url") or "#"
        details = active_subject.get("details") or {}
        p_tag = str(details.get("pipeline_tag") or "").lower()
        tags = active_subject.get("tags") or []
        tags_str = ", ".join([str(t) for t in tags[:6]]) if tags else p_tag

        paper_cards: list[dict[str, Any]] = []
        context_papers_text: list[str] = []

        # 1. Поиск релевантных статей строго в категории 'статья' в локальной базе
        raw_papers = rag_service.search_cards(
            query=f"{clean_title} {p_tag} {tags_str}",
            category="статья",
            top_k=effective_limit,
            min_score=0.25,
        )
        for r in raw_papers:
            c = r["card"]
            formatted = _format_single_card_for_ui(c)
            paper_cards.append(formatted)
            context_papers_text.append(f"- **[{formatted['title']}]({formatted['url']})**: {formatted['summary']}")

        llm_messages = [{"role": "system", "content": RADAR_CHAT_SYSTEM_PROMPT}]
        for m in history[-4:-1]:
            llm_messages.append({"role": m["role"], "content": m["content"]})

        db_hint = ""
        if context_papers_text:
            db_hint = "Статьи из локального каталога:\n" + "\n".join(context_papers_text) + "\n\n"

        prompt_content = (
            f"Пользователь спрашивает: «{last_user_msg}» в контексте архитектуры **[{clean_title}]({url})**.\n"
            f"Задача и профиль модели: `{p_tag or 'deep learning'}`. Теги: {tags_str}.\n\n"
            f"{db_hint}"
            f"ТРЕБОВАНИЯ К ОТВЕТУ:\n"
            f"1. Начинай СРАЗУ по существу, без приветствий («Приветствую» и т.п.)!\n"
            f"2. Приведи фундаментальные научные статьи, препринты ArXiv и технические отчеты исследователей, лежащие в основе архитектуры «{clean_title}».\n"
            f"3. Для каждой статьи укажи:\n"
            f"   - Точное название с кликабельной ссылкой: [Название статьи](https://arxiv.org/abs/...)\n"
            f"   - Авторов / исследовательскую лабораторию\n"
            f"   - Краткую суть и архитектурное значение именно для {clean_title}\n"
            f"4. СТРОЖАЙШЕ ЗАПРЕЩЕНО упоминать, перечислять или обсуждать посторонние сущности, модели или генераторы медиа. Не делай никаких отступлений о том, чего нет в базе. Отвечай ИСКЛЮЧИТЕЛЬНО по научным публикациям для {clean_title}!"
        )
        llm_messages.append({"role": "user", "content": prompt_content})

        qwen_reply = call_qwen_chat(llm_messages, temperature=0.3)
        if qwen_reply:
            cleaned_reply = _clean_qwen_output(qwen_reply)

            # Извлекаем ссылки на ArXiv / научные статьи из ответа Qwen для карточек в UI
            extracted = re.findall(r'\[([^\]]{10,})\]\((https?://(?:arxiv\.org|doi\.org|aclanthology\.org|openreview\.net|liquid\.ai)[^\)]+)\)', cleaned_reply)
            for p_title, p_url in extracted[:effective_limit]:
                clean_p_title = _clean_card_title(p_title)
                if clean_p_title not in [p["title"] for p in paper_cards]:
                    paper_cards.append({
                        "id": f"paper_{abs(hash(p_url)) % 1000000}",
                        "title": clean_p_title,
                        "category": "статья",
                        "url": p_url.strip(),
                        "summary": f"Научная публикация / исследование для понимания архитектуры {clean_title}.",
                        "tags": ["research", "paper", "arxiv"],
                        "metrics": {"stars": 200},
                        "similarity": 0.95,
                    })

            return {
                "role": "assistant",
                "content": cleaned_reply,
                "action": "search",
                "search_query": f"статьи для {clean_title}",
                "cards": paper_cards[:effective_limit],
                "error": None,
            }

        # Резервный ответ при оффлайн LLM
        blocks = []
        for i, pc in enumerate(paper_cards[:effective_limit], start=1):
            blocks.append(
                f"#### {i}. [{pc['title']}]({pc['url']})\n\n"
                f"📂 **НАУЧНАЯ СТАТЬЯ**\n\n"
                f"{pc['summary']}\n"
            )
        resp_text = (
            f"### 📄 Ключевые научные статьи для [{clean_title}]({url})\n\n"
            f"Для детального понимания архитектуры **[{clean_title}]({url})** рекомендуются следующие фундаментальные публикации:\n\n"
            + "\n\n---\n\n".join(blocks)
        )
        return {
            "role": "assistant",
            "content": resp_text,
            "action": "search",
            "search_query": f"статьи для {clean_title}",
            "cards": paper_cards[:effective_limit],
            "error": None,
        }

    # 5.3: Запрос «что еще посоветуешь к этой модели» (экосистема, стек, интеграция)
    if active_subject and followup_intent and followup_intent.get("type") == "ecosystem":
        clean_title = _clean_card_title(active_subject.get("title", "Модель"))
        url = active_subject.get("url") or active_subject.get("source_url") or "#"
        details = active_subject.get("details") or {}
        p_tag = str(details.get("pipeline_tag") or "").lower()

        ecosystem_cards: list[dict[str, Any]] = []
        raw_tools = rag_service.search_cards(query=f"vllm transformers llama.cpp {p_tag}", category="репозиторий", top_k=3)
        for r in raw_tools:
            ecosystem_cards.append(_format_single_card_for_ui(r["card"]))

        llm_messages = [{"role": "system", "content": RADAR_CHAT_SYSTEM_PROMPT}]
        for m in history[-4:-1]:
            llm_messages.append({"role": m["role"], "content": m["content"]})

        llm_messages.append({
            "role": "user",
            "content": (
                f"Вопрос пользователя: «{last_user_msg}» в контексте модели **[{clean_title}]({url})**.\n\n"
                f"ТРЕБОВАНИЯ К ОТВЕТУ:\n"
                f"1. Начинай СРАЗУ по существу, без приветствий («Приветствую» и т.п.)!\n"
                f"2. Предложи комплексную инженерную экосистему для {clean_title}:\n"
                f"   - Оптимальный инференс-сервер (vLLM, llama.cpp, SGLang, Ollama).\n"
                f"   - Инструменты дообучения (unsloth, peft, transformers LoRA/QLoRA).\n"
                f"   - Пайплайн интеграции (как соединить модель с базой данных или векторным поиском).\n"
                f"   - Прямые альтернативы для сравнительного тестирования под эту же задачу.\n"
                f"3. Оформляй четко, профессионально, с кликабельными ссылками."
            ),
        })

        qwen_reply = call_qwen_chat(llm_messages, temperature=0.3)
        if qwen_reply:
            cleaned_reply = _clean_qwen_output(qwen_reply)
            return {
                "role": "assistant",
                "content": cleaned_reply,
                "action": "search",
                "search_query": f"инструменты для {clean_title}",
                "cards": ecosystem_cards,
                "error": None,
            }

    # 5.4: Пользователь спрашивает КОД ЗАПУСКА
    if active_subject and followup_intent and followup_intent.get("type") == "code":
        clean_title = _clean_card_title(active_subject.get("title", "Материал"))
        code_block = _generate_code_snippet(active_subject)
        llm_messages = [
            {"role": "system", "content": RADAR_CHAT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Пользователь просит код запуска/инференса для «{clean_title}»:\n\n"
                    f"Базовый шаблон кода:\n{code_block}\n\n"
                    f"СТРОГО: Начинай ответ сразу с кода и пояснений, без любых приветствий!"
                ),
            },
        ]
        qwen_reply = call_qwen_chat(llm_messages, temperature=0.3)
        if qwen_reply:
            cleaned_reply = _clean_qwen_output(qwen_reply)
            return {
                "role": "assistant",
                "content": cleaned_reply,
                "action": "card_detail",
                "search_query": clean_title,
                "cards": [_format_single_card_for_ui(active_subject)],
                "error": None,
            }
        return {
            "role": "assistant",
            "content": f"### 💻 Запуск «{clean_title}»\n\n{code_block}",
            "action": "card_detail",
            "search_query": clean_title,
            "cards": [_format_single_card_for_ui(active_subject)],
            "error": None,
        }

    # ---------------------------------------------------------------------
    # ШАГ 6: Общий семантический поиск по каталогу Radar Scout
    # ---------------------------------------------------------------------
    search_cat = category_filter
    clean_last = re.sub(r"[^\w\s]", "", last_user_msg.lower()).strip()

    if re.search(r"(датасет\w*|данн\w*|выборк\w*|корпус\w*|разметк\w*|обуч\w*|дообуч\w*)", clean_last):
        search_cat = "датасет"
    elif re.search(r"(стать\w*|paper\w*|исследован\w*|arxiv\b|публикац\w*)", clean_last):
        search_cat = "статья"
    elif re.search(r"(репозитор\w*|репо\b|код\b|библиотек\w*)", clean_last):
        search_cat = "репозиторий"
    elif re.search(r"(модел\w*|вес\w*|нейросет\w*)", clean_last):
        search_cat = "модель"

    # Семантический поиск строго по указанной категории без фоллбека в 'all'
    results = rag_service.search_cards(
        query=last_user_msg,
        category=search_cat,
        top_k=effective_limit,
        min_score=0.25,
    )

    found_cards: list[dict[str, Any]] = []
    cards_context_list = []
    seen_titles_ui: set[str] = set()

    for r in results:
        c = dict(r["card"])
        score_val = float(r.get("score", 0.0))
        c["similarity"] = score_val
        formatted = _format_single_card_for_ui(c)
        t_norm = re.sub(r"[^\w\s]", "", formatted["title"].lower()).strip()
        if t_norm in seen_titles_ui:
            continue
        seen_titles_ui.add(t_norm)
        found_cards.append(formatted)
        cards_context_list.append(
            f"- [{formatted['title']}]({formatted['url']}) | Тип: {formatted['category']} | Описание: {formatted['summary']}"
        )

    # Вызов Qwen с найденными карточками в качестве контекста
    llm_messages = [{"role": "system", "content": RADAR_CHAT_SYSTEM_PROMPT}]
    for m in history[-5:-1]:
        llm_messages.append({"role": m["role"], "content": m["content"]})

    context_str = "\n".join(cards_context_list) if cards_context_list else f"В локальной базе каталога Radar Scout по категории «{search_cat}» прямых совпадений не найдено."
    active_hint = ""
    if active_subject:
        active_hint = f"\n[Активный объект в фокусе: {_clean_card_title(active_subject.get('title', ''))}]\n"

    user_prompt_with_rag = (
        f"{active_hint}"
        f"Вопрос пользователя: «{last_user_msg}»\n\n"
        f"Материалы из базы Radar Scout:\n{context_str}\n\n"
        f"ТРЕБОВАНИЯ К ОТВЕТУ:\n"
        f"1. Начинай СРАЗУ по существу, без приветствий («Приветствую» и т.п.)!\n"
        f"2. Отвечай строго по теме вопроса. Если запрошены {search_cat} — называй ИСКЛЮЧИТЕЛЬНО {search_cat}.\n"
        f"3. Для всех материалов приводи кликабельные Markdown-ссылки [Название](url).\n"
        f"4. Если в локальной базе мало или нет совпадений — сразу назови общепризнанные мировые материалы (ArXiv, Hugging Face, GitHub).\n"
        f"5. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО оправдываться, упоминать или обсуждать посторонние сущности, которых нет в вопросе!"
    )
    llm_messages.append({"role": "user", "content": user_prompt_with_rag})

    qwen_reply = call_qwen_chat(llm_messages, temperature=0.4)
    if qwen_reply:
        cleaned_reply = _clean_qwen_output(qwen_reply)
        return {
            "role": "assistant",
            "content": cleaned_reply,
            "action": "search" if found_cards else "chat",
            "search_query": last_user_msg,
            "cards": found_cards,
            "error": None,
        }

    # Резервный ответ при оффлайн сервере vLLM
    if not found_cards:
        return {
            "role": "assistant",
            "content": f"По запросу **«{last_user_msg}»** в каталоге не найдено прямых совпадений. Попробуйте уточнить формулировку или сбросить фильтры.",
            "action": "search",
            "search_query": last_user_msg,
            "cards": [],
            "error": None,
        }

    card_blocks = []
    for i, c in enumerate(found_cards, start=1):
        c_t = c["title"]
        c_u = c["url"]
        c_type = c.get("category", "материал").upper()
        c_s = c["summary"]
        card_blocks.append(
            f"#### {i}. [{c_t}]({c_u})\n\n"
            f"📂 **{c_type}**\n\n"
            f"{c_s}\n"
        )

    text_resp = (
        f"### Материалы по направлению «{last_user_msg}»\n\n"
        f"В каталоге Radar Scout найдены следующие материалы:\n\n"
        + "\n---\n".join(card_blocks)
        + "\n\nМогу подробнее рассказать о любой из этих карточек или подобрать код запуска!"
    )

    return {
        "role": "assistant",
        "content": text_resp,
        "action": "search",
        "search_query": last_user_msg,
        "cards": found_cards,
        "error": None,
    }
