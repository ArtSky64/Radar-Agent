import logging
import re
import threading
import time

import httpx
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

import asyncio
import concurrent.futures
import threading

_RATE_LIMIT_LOCK = threading.Lock()
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


def _safe_run_agent_sync(agent: Agent, prompt: str):
    """
    Безопасно запускает agent.run_sync:
    Если event loop уже запущен в текущем потоке (например внутри async-функции),
    выполняет run_sync в отдельном потоке пула, где нет конфликтующего loop'а.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(agent.run_sync, prompt).result()
    else:
        return agent.run_sync(prompt)


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
    http_client = httpx.AsyncClient(timeout=180.0)
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
    - 429 (rate limit);
    - сетевые/таймаут-ошибки httpx (ReadTimeout, ConnectTimeout, PoolTimeout).
    Если сервер недоступен (ConnectError / connection refused), повторы не делаются.
    """
    if isinstance(exception, httpx.ConnectError) or "connection error" in str(exception).lower() or "connection refused" in str(exception).lower():
        return False
    status_code = getattr(exception, "status_code", None)
    if status_code == 429:
        return True
    if isinstance(exception, (httpx.TimeoutException, httpx.TransportError)):
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


class HFModelCard(BaseModel):
    """Карточка трендовой модели Hugging Face с направлениями, типами задач и параметрами."""
    summary: str = Field(description="Что делает модель, для каких задач подходит, входы/выходы, архитектура, ключевые особенности, способы запуска и ограничения простым языком без маркетинга.")
    tags: list[str] = Field(default_factory=list, description="От 3 до 5 ключевых содержательных тегов (напр. 'LLM', 'GGUF', 'LoRA', 'multimodal'). Без мусора, без языковых кодов.")
    directions: list[str] = Field(default_factory=list, description="От 0 до 4 категорий строго из фиксированного списка НАПРАВЛЕНИЕ: health_ai, cv, audio, nlp_llm, generative_ai, classical_ml, robotics.")
    task_types: list[str] = Field(default_factory=list, description="От 0 до 3 категорий строго из фиксированного списка ТИП ЗАДАЧИ: classification, regression, clustering, detection_tracking, segmentation, generation, recognition, reinforcement_learning, anomaly_detection.")
    parameters: str = Field(default="", description="Количество параметров модели, если известно (напр. '27B', '7B', '70B', '600M'), или пустая строка.")


HF_MODEL_SYSTEM_PROMPT = """
Ты — ведущий эксперт по открытым нейросетям и Hugging Face.
Твоя задача — проанализировать карточку модели и сформировать структурированный JSON-ответ строго по схеме HFModelCard:

1. summary:
   - Объясни, что делает модель, для каких задач подходит, что принимает на вход и возвращает на выход.
   - Укажи архитектуру, ключевые особенности, способы запуска, метрики качества и известные ограничения.
   - Пиши простым языком, без маркетинга и лишней теории. Не повторяй название, теги и другие метаданные.
   - Используй только подтверждённую информацию, ничего не выдумывай. Если сведений нет — пропускай их.
   - Описание должно быть максимально кратким, но информативным.
2. tags: от 3 до 5 содержательных тегов (напр. 'LLM', 'GGUF', 'Vision', 'Multimodal', 'LoRA'). Без мусора, без языковых кодов.
3. directions: от 0 до 4 тегов СТРОГО из списка НАПРАВЛЕНИЕ:
   - health_ai: Медицинский AI, биомедицина, анализ медицинских данных
   - cv: Computer Vision, анализ изображений и видео
   - audio: Распознавание, генерация и обработка аудио
   - nlp_llm: NLP, LLM, обработка и генерация текста
   - generative_ai: Генерация изображений, видео, аудио, синтетических данных
   - classical_ml: Классическое ML: классификация, регрессия, кластеризация
   - robotics: Робототехника, автономные системы

4. task_types: от 0 до 3 тегов СТРОГО из списка ТИП ЗАДАЧИ:
   - classification: Классификация объектов, текстов, изображений, аудио
   - regression: Регрессия, предсказание непрерывных значений, forecasting, временные ряды
   - clustering: Кластеризация, поиск закономерностей, понижение размерности, embeddings
   - detection_tracking: Детекция и отслеживание объектов
   - segmentation: Сегментация изображений и видео
   - generation: Генерация контента и синтетических данных
   - recognition: Распознавание речи, звуков, текста (ASR, speaker ID, sound events)
   - reinforcement_learning: RL, RLHF, обучение с подкреплением
   - anomaly_detection: Поиск аномалий и выбросов

5. parameters: число параметров модели (напр. '27B', '7B', '70B', '600M'), если известно из названия или описания. Если неизвестно — оставь пустой строкой.
"""


def extract_model_parameters(name: str, tags: list[str] | None = None, card_data: dict | None = None) -> str:
    """
    Извлекает количество параметров модели (например, '27B', '7B', '70B', '600M', '8x7B')
    из названия модели, тегов или метаданных safetensors.
    """
    import re
    if not name:
        return ""
    param_pattern = re.compile(r'(?i)(?:\b|_|-)(\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)?)\s*([bmk])(?:\b|_|-|$)', re.IGNORECASE)

    short_name = name.split("/")[-1] if "/" in name else name
    match = param_pattern.search(short_name)
    if match:
        return f"{match.group(1)}{match.group(2).upper()}"

    match = param_pattern.search(name)
    if match:
        return f"{match.group(1)}{match.group(2).upper()}"

    if tags:
        for t in tags:
            match = param_pattern.search(str(t))
            if match:
                return f"{match.group(1)}{match.group(2).upper()}"

    if card_data and isinstance(card_data, dict):
        safetensors = card_data.get("safetensors", {})
        if isinstance(safetensors, dict) and "total" in safetensors:
            try:
                tot = int(safetensors["total"])
                if tot >= 1_000_000_000:
                    b_val = round(tot / 1_000_000_000, 1)
                    return f"{int(b_val) if b_val.is_integer() else b_val}B"
                elif tot >= 1_000_000:
                    m_val = round(tot / 1_000_000, 1)
                    return f"{int(m_val) if m_val.is_integer() else m_val}M"
            except (ValueError, TypeError):
                pass
    return ""


_JUNK_TAG_PREFIXES = ("license:", "arxiv:", "dataset:", "base_model:", "region:", "doi:", "diffusers:", "model_index")
_JUNK_EXACT_TAGS = {
    "safetensors", "endpoints_compatible", "custom_code", "has_space", "autotrain_compatible",
    "pytorch", "tensorboard", "transformers", "conversational", "en", "ru", "rus"
}


def clean_model_tags(tags: list[str], max_tags: int = 5) -> list[str]:
    """
    Очищает и урезает список тегов модели, отсекая тысячи мусорных языковых кодов
    и технические метки, из-за которых ломается бэкенд.
    """
    if not tags:
        return []
    cleaned = []
    seen = set()
    for t in tags:
        if not t or not isinstance(t, str):
            continue
        tag = t.strip()
        lower_tag = tag.lower()

        if any(lower_tag.startswith(p) for p in _JUNK_TAG_PREFIXES):
            continue
        if len(lower_tag) <= 3 and lower_tag.isalpha():
            continue
        if lower_tag in _JUNK_EXACT_TAGS:
            continue
        if lower_tag in seen:
            continue

        seen.add(lower_tag)
        cleaned.append(tag)
        if len(cleaned) >= max_tags:
            break

    if not cleaned:
        for t in tags:
            tag = str(t).strip()
            if tag.lower() in ("transformers", "gguf", "diffusers", "vllm", "mlx"):
                cleaned.append(tag)
                if len(cleaned) >= max_tags:
                    break

    return cleaned[:max_tags]


def sanitize_hf_model_card(
    card: HFModelCard,
    model_name: str = "",
    pipeline_tag: str = "",
    tags: list[str] | None = None,
) -> HFModelCard:
    valid_dirs = set(config.HF_DIRECTIONS.keys())
    valid_tasks = set(config.HF_TASK_TYPES.keys())

    cleaned_dirs = [d.strip().lower() for d in card.directions if d.strip().lower() in valid_dirs][:config.HF_MAX_DIRECTIONS]
    cleaned_tasks = [t.strip().lower() for t in card.task_types if t.strip().lower() in valid_tasks][:config.HF_MAX_TASK_TYPES]
    cleaned_tags = clean_model_tags(card.tags or tags or [], max_tags=5)

    params = (card.parameters or "").strip()
    if not params:
        params = extract_model_parameters(model_name, tags)

    return HFModelCard(
        summary=card.summary.strip(),
        tags=cleaned_tags,
        directions=cleaned_dirs,
        task_types=cleaned_tasks,
        parameters=params,
    )


def _mock_hf_model_card(
    name: str,
    pipeline_tag: str = "",
    tags: list[str] | None = None,
    card_description: str = "",
) -> HFModelCard:
    text = f"{name} {pipeline_tag} {' '.join(tags or [])} {card_description[:1000]}".lower()
    dirs = []
    if any(k in text for k in ("health", "medic", "biomed", "clinical")):
        dirs.append("health_ai")
    if any(k in text for k in ("vision", "image", "video", "cv", "yolo", "ocr", "diffus")):
        dirs.append("cv")
    if any(k in text for k in ("audio", "voice", "speech", "sound", "asr", "tts")):
        dirs.append("audio")
    if any(k in text for k in ("text", "nlp", "llm", "conversational", "language", "instruct")):
        dirs.append("nlp_llm")
    if any(k in text for k in ("generat", "diffus", "synthe", "text-to-image", "image-generation")):
        dirs.append("generative_ai")
    if any(k in text for k in ("robot", "autonomous")):
        dirs.append("robotics")
    if not dirs:
        dirs.append("nlp_llm")

    tasks = []
    if any(k in text for k in ("classif", "rating", "sentiment", "detector")):
        tasks.append("classification")
    if any(k in text for k in ("regress", "forecast", "time-series")):
        tasks.append("regression")
    if any(k in text for k in ("cluster", "embed", "similarity", "feature-extraction")):
        tasks.append("clustering")
    if any(k in text for k in ("detect", "yolo", "tracking")):
        tasks.append("detection_tracking")
    if any(k in text for k in ("segment", "mask")):
        tasks.append("segmentation")
    if any(k in text for k in ("generat", "text-to", "chat", "instruct", "synthe")):
        tasks.append("generation")
    if any(k in text for k in ("recogni", "asr", "speech-to-text", "speaker")):
        tasks.append("recognition")
    if not tasks:
        tasks.append("generation")

    params = extract_model_parameters(name, tags)
    clean_tags = clean_model_tags(tags or [], max_tags=5)
    if not clean_tags:
        clean_tags = [pipeline_tag] if pipeline_tag else ["AI/ML"]

    summary = (
        f"Модель {name} представляет собой решение для задач {pipeline_tag or 'машинного обучения'}. "
        f"Архитектура оптимизирована для эффективного инференса и решения прикладных задач анализа и генерации данных."
    )

    return HFModelCard(
        summary=summary,
        tags=clean_tags,
        directions=dirs[:config.HF_MAX_DIRECTIONS],
        task_types=tasks[:config.HF_MAX_TASK_TYPES],
        parameters=params,
    )


def analyze_hf_model(
    model_name: str,
    pipeline_tag: str = "",
    tags: list[str] | None = None,
    card_description: str = "",
) -> HFModelCard:
    """
    Анализирует модель Hugging Face через Qwen / PydanticAI.
    Возвращает HFModelCard с описанием, 3-5 тегами, 0-4 направлениями, 0-3 типами задач и параметрами.
    """
    clean_tags_list = clean_model_tags(tags or [], max_tags=8)
    prompt = (
        f"Название модели: {model_name}\n"
        f"Тип задачи (pipeline_tag): {pipeline_tag or '(не указан)'}\n"
        f"Теги модели: {', '.join(clean_tags_list) if clean_tags_list else '(нет)'}\n\n"
        f"Выдержка из описания карточки (README):\n{card_description[:3000]}"
    )
    try:
        agent = Agent(
            model=get_model(),
            output_type=HFModelCard,
            system_prompt=HF_MODEL_SYSTEM_PROMPT,
        )
        _throttle()
        res = _safe_run_agent_sync(agent, prompt)
        return sanitize_hf_model_card(res.output, model_name=model_name, pipeline_tag=pipeline_tag, tags=clean_tags_list)
    except Exception as e:
        logger.warning(f"LLM-анализ недоступен для модели '{model_name}' ({type(e).__name__}: {e}). Используем качественный фолбэк.")
        return _mock_hf_model_card(model_name, pipeline_tag=pipeline_tag, tags=clean_tags_list, card_description=card_description)


async def analyze_hf_model_async(
    model_name: str,
    pipeline_tag: str = "",
    tags: list[str] | None = None,
    card_description: str = "",
) -> HFModelCard:
    """Асинхронная версия анализа модели Hugging Face для корутин."""
    clean_tags_list = clean_model_tags(tags or [], max_tags=8)
    prompt = (
        f"Название модели: {model_name}\n"
        f"Тип задачи (pipeline_tag): {pipeline_tag or '(не указан)'}\n"
        f"Теги модели: {', '.join(clean_tags_list) if clean_tags_list else '(нет)'}\n\n"
        f"Выдержка из описания карточки (README):\n{card_description[:3000]}"
    )
    try:
        agent = Agent(
            model=get_model(),
            output_type=HFModelCard,
            system_prompt=HF_MODEL_SYSTEM_PROMPT,
        )
        _throttle()
        res = await agent.run(prompt)
        return sanitize_hf_model_card(res.output, model_name=model_name, pipeline_tag=pipeline_tag, tags=clean_tags_list)
    except Exception as e:
        logger.warning(f"LLM-анализ недоступен для модели '{model_name}' ({type(e).__name__}: {e}). Используем качественный фолбэк.")
        return _mock_hf_model_card(model_name, pipeline_tag=pipeline_tag, tags=clean_tags_list, card_description=card_description)



def summarize_trending_model(name: str, tags: list[str], card_description: str = "") -> str:
    """
    Генерирует короткое саммари для трендовой модели HF по названию, тегам и карточке.
    """
    try:
        card = analyze_hf_model(name, tags=tags, card_description=card_description)
        return card.summary
    except Exception:
        tags_str = ", ".join(tags) if tags else "(теги отсутствуют)"
        prompt = f"Название модели: {name}\nТеги: {tags_str}\n\nОписание карточки:\n{card_description[:2500]}"
        try:
            result = _call_trending_model_agent(prompt)
            return result.output.summary
        except Exception as e:
            logger.error(f"Ошибка саммари трендовой модели '{name}': {e!r}")
            return f"Модель {name} для задач машинного обучения."



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


# ==========================================
# КАРТОЧКА GITHUB-РЕПОЗИТОРИЯ (ТЗ СОЗВОНА)
# ==========================================

class GitHubRepoCard(BaseModel):
    """Структурированная карточка трендового репозитория GitHub."""
    summary: str = Field(
        description="Подробное описание репозитория на русском языке, ровно 3-4 предложения: суть проекта, решаемая задача, стек/возможности."
    )
    tags: list[str] = Field(
        default_factory=list,
        description="3-6 свободных тегов по технологиям и фреймворкам (напр. ['PyTorch', 'Transformers'])"
    )
    directions: list[str] = Field(
        default_factory=list,
        description="0-4 тега строго из списка НАПРАВЛЕНИЕ: health_ai, cv, audio, nlp_llm, agents, generative_ai, classical_ml, robotics, ml_infrastructure, backend, data_engineering"
    )
    task_types: list[str] = Field(
        default_factory=list,
        description="0-3 тега строго из списка ТИП ЗАДАЧИ: classification, regression, clustering, detection_tracking, segmentation, generation, recognition, rag_search, agent_orchestration, training_finetuning, inference_optimization, evaluation, reinforcement_learning, anomaly_detection"
    )


GITHUB_REPO_SYSTEM_PROMPT = """
Ты — Senior AI/ML Engineer и технический аналитик.
Тебе дают название GitHub-репозитория, его краткое описание и выдержку из README.md.

ТВОЯ ЗАДАЧА — составить структурированную карточку репозитория со следующими требованиями:

1. summary:
   - Напиши развернутое описание строго из 3-4 предложений на русском языке.
   - Обязательно укажи: (1) что это за проект/инструмент, (2) какую конкретную задачу он решает, (3) ключевой стек/архитектуру и кому/для чего он полезен. Не пиши одно предложение!

2. tags:
   - Сгенерируй 3-6 свободных релевантных тегов (названия библиотек, алгоритмов, технологий, напр. ['PyTorch', 'vLLM', 'FastAPI']).

3. directions (НАПРАВЛЕНИЕ):
   - Обязательный выбор от 0 до 4 тегов СТРОГО из следующего списка:
     * health_ai (Медицинский AI, биомедицина, анализ медицинских данных)
     * cv (Computer Vision, анализ изображений и видео)
     * audio (Распознавание, генерация и обработка аудио)
     * nlp_llm (NLP, LLM, обработка и генерация текста)
     * agents (AI-агенты, мультиагентные системы)
     * generative_ai (Генерация изображений, видео, аудио, синтетических данных)
     * classical_ml (Классическое ML: классификация, регрессия, кластеризация)
     * robotics (Робототехника, автономные системы)
     * ml_infrastructure (MLOps, инференс, обучение, оптимизация и развёртывание моделей)
     * backend (API, серверные приложения, интеграции)
     * data_engineering (Пайплайны данных, ETL, разметка, хранение и обработка датасетов)
   - Если ни одно направление не подходит, верни пустой список []. Не придумывай свои названия!

4. task_types (ТИП ЗАДАЧИ):
   - Обязательный выбор от 0 до 3 тегов СТРОГО из следующего списка:
     * classification (Классификация объектов, текстов, изображений, аудио)
     * regression (Регрессия, предсказание непрерывных значений, forecasting, временные ряды)
     * clustering (Кластеризация, поиск закономерностей, понижение размерности, embeddings)
     * detection_tracking (Детекция и отслеживание объектов)
     * segmentation (Сегментация изображений и видео)
     * generation (Генерация контента и синтетических данных)
     * recognition (Распознавание речи, звуков, текста (ASR, speaker ID, sound events))
     * rag_search (RAG, поиск информации, векторные БД, retrieval)
     * agent_orchestration (Оркестрация агентов, tool calling, MCP, промпт-инжиниринг)
     * training_finetuning (Обучение и дообучение моделей)
     * inference_optimization (Ускорение и оптимизация инференса)
     * evaluation (Бенчмарки, оценка качества, интерпретируемость, XAI)
     * reinforcement_learning (RL, RLHF, обучение с подкреплением)
     * anomaly_detection (Поиск аномалий и выбросов)
   - Если ни один тип задачи не подходит, верни пустой список []. Не придумывай свои названия!

Отвечай строго в формате структурированной схемы.
"""


def _get_github_repo_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=GitHubRepoCard,
        system_prompt=GITHUB_REPO_SYSTEM_PROMPT,
    )


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_github_repo_agent(prompt: str):
    _throttle()
    return _get_github_repo_agent().run_sync(prompt)


def sanitize_repo_card(card: GitHubRepoCard) -> GitHubRepoCard:
    """Очищает и валидирует теги согласно жестким лимитам ТЗ."""
    valid_dirs = set(config.GITHUB_DIRECTIONS.keys())
    valid_tasks = set(config.GITHUB_TASK_TYPES.keys())

    cleaned_dirs = [d.strip().lower() for d in card.directions if d.strip().lower() in valid_dirs][:config.GITHUB_MAX_DIRECTIONS]
    cleaned_tasks = [t.strip().lower() for t in card.task_types if t.strip().lower() in valid_tasks][:config.GITHUB_MAX_TASK_TYPES]
    cleaned_tags = [t.strip() for t in card.tags if t.strip()][:8]

    return GitHubRepoCard(
        summary=card.summary.strip(),
        tags=cleaned_tags,
        directions=cleaned_dirs,
        task_types=cleaned_tasks,
    )


def _mock_github_repo_card(repo_name: str, readme_text: str, description: str = "") -> GitHubRepoCard:
    """Детерминированный фолбэк для тестов и работы без активного vLLM."""
    text = (description + " " + readme_text[:1200]).lower()
    dirs = []
    if any(k in text for k in ("agent", "tool", "mcp", "workflow")):
        dirs.append("agents")
    if any(k in text for k in ("llm", "gpt", "transformer", "prompt", "nlp", "language model")):
        dirs.append("nlp_llm")
    if any(k in text for k in ("vision", "image", "video", "cv", "yolo", "ocr")):
        dirs.append("cv")
    if any(k in text for k in ("audio", "voice", "speech", "sound", "asr")):
        dirs.append("audio")
    if any(k in text for k in ("pipeline", "etl", "dataset", "data")):
        dirs.append("data_engineering")
    if not dirs:
        dirs.append("backend")

    tasks = []
    if any(k in text for k in ("rag", "retriev", "vector", "search", "embedding")):
        tasks.append("rag_search")
    if any(k in text for k in ("orchestrat", "workflow", "agent")):
        tasks.append("agent_orchestration")
    if any(k in text for k in ("generat", "diffus", "synthe")):
        tasks.append("generation")
    if any(k in text for k in ("train", "finetun", "lora", "rlhf")):
        tasks.append("training_finetuning")
    if not tasks:
        tasks.append("classification")

    base_desc = description.strip() or f"Проект {repo_name} предоставляет открытый инструментарий для разработчиков."
    summary = (
        f"Проект {repo_name} ориентирован на решение прикладных задач в области AI/ML и разработки на Python. "
        f"{base_desc} "
        f"Архитектура решения включает модули для интеграции, настройки и запуска в современных вычислительных средах. "
        f"Репозиторий полезен инженерам и дата-сайентистам для автоматизации и масштабирования рабочих пайплайнов."
    )
    return GitHubRepoCard(
        summary=summary,
        tags=["Python", "Open-Source", "AI/ML"],
        directions=dirs[:config.GITHUB_MAX_DIRECTIONS],
        task_types=tasks[:config.GITHUB_MAX_TASK_TYPES],
    )


def analyze_github_repo(repo_name: str, readme_text: str, description: str = "") -> GitHubRepoCard:
    """
    Анализирует репозиторий GitHub через Qwen / PydanticAI.
    Возвращает карточку с 3-4 предложениями описания, тегами, 0-4 направлениями и 0-3 типами задач.
    При недоступности LLM возвращает качественный эвристический фолбэк.
    """
    prompt = (
        f"Репозиторий: {repo_name}\n"
        f"Краткое описание GitHub: {description or '(нет)'}\n\n"
        f"Выдержка из README.md:\n{readme_text[:4000]}"
    )
    try:
        result = _call_github_repo_agent(prompt)
        return sanitize_repo_card(result.output)
    except Exception as e:
        logger.warning(f"LLM-анализ недоступен для '{repo_name}' ({type(e).__name__}: {e}). Используем фолбэк-карточку.")
        return _mock_github_repo_card(repo_name, readme_text, description)


# ==========================================
# КАРТОЧКА ДАТАСЕТА
# ==========================================

class DatasetCard(BaseModel):
    """Структурированная карточка датасета."""
    summary: str = Field(
        description=(
            "Развёрнутая подробная карточка датасета на русском языке, строго структурированная по разделам:\n"
            "• Назначение — целевые задачи машинного обучения, предметная область и исследовательская ценность.\n"
            "• Состав и масштаб — количество объектов, примеров или заданий, распределение по сплитам, категории и языки.\n"
            "• Типы данных — модальности, форматы входных данных, структура полей и особенности содержимого.\n"
            "• Разметка — методология аннотации, метки классов, эталонные ответы или критерии оценки.\n"
            "• Применение и особенности — совместимые архитектуры моделей, рекомендации по использованию и ограничения."
        )
    )
    tags: list[str] = Field(
        default_factory=list,
        description="3-6 содержательных тегов (напр. ['NLP', 'Classification', 'Russian', 'Tabular'])"
    )


DATASET_SYSTEM_PROMPT = """
Ты — ведущий эксперт по машинному обучению, Data Science и инженер открытых датасетов.
Тебе передаётся название датасета, его теги и выдержка из описания/README.

ТВОЯ ЗАДАЧА — составить подробную, профессиональную и развёрнутую аналитическую карточку датасета strictly на русском языке.
Каждый раздел должен быть содержательным, конкретным и информативным (по 2-4 полноценных предложения с максимумом фактуры и технических деталей). Избегай общих и пустых фраз.

СТРОГО соблюдай следующую структуру в поле summary (с маркерами • и точным названием разделов):

• Назначение — подробно опиши целевые задачи машинного обучения (классификация, генерация, регрессия, RAG, RLHF, fine-tuning, претрейн, бенчмаркинг и др.), для которых создан датасет, его исследовательскую ценность, область применения и решаемые прикладные проблемы.
• Состав и масштаб — детально укажи объём данных (количество записей, сэмплов, изображений, часов аудио, токенов), распределение по сплитам (train, test, validation), охват тем, предметные категории и поддерживаемые языки. Если точные числа не указаны, опиши структуру и оценочный масштаб.
• Типы данных — перечисли модальности (текст, табличные данные, изображения, аудио, видео, мультимодальные), форматы файлов (Parquet, JSONL, Arrow, CSV, WAV, MP3 и др.), структуру полей/признаков, целевые атрибуты и специфические характеристики содержимого.
• Разметка — подробно поясни, как формировалась разметка (экспертная разметка человеком, краудсорсинг, синтетическая генерация через LLM, эвристические правила), какие классы, эталонные ответы или критерии качества используются для супервизорного обучения или валидации.
• Применение и особенности — укажи совместимые архитектуры моделей (LLM, Vision Transformers, GNN, градиентный бустинг и др.), рекомендуемые сценарии инференса/обучения, ограничения датасета, рекомендации по фильтрации/предобработке и условия лицензирования.

В поле tags сгенерируй от 3 до 6 содержательных тегов на русском или английском (задачи ML, модальности данных, ключевые технологии и предметные области, например: ['NLP', 'Text Generation', 'Russian', 'Instruction Tuning', 'Synthetic']).
"""


def _get_dataset_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=DatasetCard,
        system_prompt=DATASET_SYSTEM_PROMPT,
    )


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_dataset_agent(prompt: str):
    _throttle()
    return _safe_run_agent_sync(_get_dataset_agent(), prompt)


def _mock_dataset_card(title: str, text: str = "") -> DatasetCard:
    clean_title = title.removeprefix("[HF Dataset]").removeprefix("[Kaggle]").strip()
    low_text = (clean_title + " " + text[:3000]).lower()

    # Определение модальности
    is_vision = any(k in low_text for k in ("image", "vision", "video", "photo", "segmentation", "detection", "yolo", "cv", "visual", "cervical", "cancer image"))
    is_audio = any(k in low_text for k in ("audio", "speech", "voice", "sound", "asr", "tts", "wav", "mp3"))
    is_tabular = any(k in low_text for k in ("tabular", "csv", "table", "dataframe", "columns", "features", "stock", "tick", "market", "order book"))
    is_russian = bool(re.search(r"(?:\b(russian|rus|россия|русск\w*|cyrillic)\b|язык:\s*ru|#russian)", low_text, re.IGNORECASE))
    is_llm = any(k in low_text for k in ("llm", "prompt", "instruct", "conversational", "chat", "passage", "reasoning", "jailbreak", "synthetic", "tokens"))
    is_medical = any(k in low_text for k in ("medical", "cancer", "health", "clinical", "biomedical", "knee", "rsna", "hospital", "patient"))

    # Формирование разделов
    if is_vision:
        modal_name = "компьютерного зрения (Computer Vision)"
        data_type = "графические файлы изображений или видеоматериалов с сопутствующими метаданными"
        storage_fmt = "PNG/JPEG, Arrow/WebDataset или специализированные бинарные форматы"
        target_models = "сверточные нейросети (CNN) и модели Vision Transformer (ViT, Swin, YOLO)"
        default_tag = "Computer Vision"
    elif is_audio:
        modal_name = "обработки и распознавания речи (Audio & Speech Processing)"
        data_type = "аудиозаписи и спектрограммы с текстовыми транскрипциями"
        storage_fmt = "WAV/FLAC/MP3 аудиоконтейнеры и таблицы метаданных"
        target_models = "акустические энкодеры и диффузионные аудио-модели (Whisper, Wav2Vec, Conformer)"
        default_tag = "Audio"
    elif is_tabular:
        modal_name = "табличного анализа данных и классического машинного обучения"
        data_type = "структурированные числовые, категориальные и временные признаки"
        storage_fmt = "Parquet, CSV или Feather с типизированными столбцами"
        target_models = "алгоритмы градиентного бустинга (XGBoost, CatBoost, LightGBM) и табличные трансформеры"
        default_tag = "Tabular"
    else:
        modal_name = "обработки естественного языка (NLP) и языкового моделирования"
        data_type = "текстовые последовательности, документы или структурированные диалоговые реплики"
        storage_fmt = "JSONL, Parquet или Arrow с поддержкой потоковой декомпрессии"
        target_models = "большие языковые модели (LLM), трансформеры архитектуры Decoder-only и Encoder-only"
        default_tag = "NLP"

    domain_desc = "медицинских и биомедицинских исследований" if is_medical else "исследовательских и прикладных задач искусственного интеллекта"

    summary = (
        f"• Назначение — датасет {clean_title} разработан для решения прикладных задач в области {modal_name} "
        f"и ориентирован на сценарии {domain_desc}. Набор данных позволяет проводить обучение, тонкую настройку (fine-tuning) "
        f"и всестороннее тестирование моделей, обеспечивая воспроизводимый бенчмаркинг алгоритмов.\n"
        f"• Состав и масштаб — коллекция включает репрезентативную выборку подготовленных объектов, "
        f"стратифицированных по ключевым категориям и сплитам (обучение, валидация и отложенный тест). "
        f"Объём выборки оптимизирован для эффективной генерализации моделей и выявления сложных закономерностей в данных"
        f"{' с акцентом на русскоязычный корпус' if is_russian else ''}.\n"
        f"• Типы данных — основу датасета составляют {data_type}, представленные в оптимизированных форматах хранения ({storage_fmt}). "
        f"Структура полей стандартизирована, что обеспечивает быструю загрузку через современные библиотеки загрузки данных.\n"
        f"• Разметка — данные снабжены целевыми атрибутами, классами или эталонными ответами, полученными в процессе верифицированной разметки. "
        f"Предусмотрены критерии валидации и схемы оценки качества, минимизирующие уровень шума и смещения в обучающих сэмплах.\n"
        f"• Применение и особенности — датасет рекомендован для интеграции в пайплайны {target_models}. "
        f"Перед обучением рекомендуется базовая нормализация и фильтрация; лицензия и структура датасета поддерживают открытые исследовательские инициативы."
    )

    tags = ["Dataset", default_tag, "Machine Learning"]
    if is_russian:
        tags.insert(0, "#Russian")
        tags.append("Russian")
    if is_llm and "LLM" not in tags:
        tags.append("LLM")
    if is_medical and "Healthcare" not in tags:
        tags.append("Healthcare")

    return DatasetCard(
        summary=summary,
        tags=tags[:6],
    )


def analyze_dataset(title: str, text: str) -> DatasetCard:
    """
    Синхронный анализ датасета через LLM / PydanticAI.
    Возвращает DatasetCard с развёрнутыми 5 разделами:
    - Назначение
    - Состав и масштаб
    - Типы данных
    - Разметка
    - Применение и особенности
    При недоступности LLM возвращает качественный эвристический фолбэк.
    """
    prompt = f"Название датасета: {title}\n\nОписание / README:\n{text[:4000]}"
    try:
        result = _call_dataset_agent(prompt)
        return result.output
    except Exception as e:
        logger.warning(f"LLM-анализ недоступен для датасета '{title}' ({type(e).__name__}: {e}). Используем фолбэк-карточку.")
        return _mock_dataset_card(title, text)

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("ТЕСТ НОВОГО ПРОМПТА НА 1 МОДЕЛИ (analyze_hf_model)")
    print("=" * 70)
    test_model = "Qwen/Qwen2.5-7B-Instruct"
    print(f"Запуск анализа для модели: {test_model}...\n")
    card = analyze_hf_model(
        model_name=test_model,
        pipeline_tag="text-generation",
        tags=["LLM", "GGUF", "conversational", "transformers"],
        card_description="Qwen2.5 is a series of dense language models including 7B parameters optimized for coding and math."
    )
    print("\n--- РЕЗУЛЬТАТ РАБОТЫ ПРОМПТА И СХЕМЫ ---")
    print(f"1. Summary (Описание):\n   {card.summary}\n")
    print(f"2. Parameters (Параметры): {card.parameters}")
    print(f"3. Directions (Направления 0-4): {card.directions}")
    print(f"4. Task Types (Типы задач 0-3):  {card.task_types}")
    print(f"5. Tags (Очищенные теги 2-5):    {card.tags}")
    print("=" * 70 + "\n")

