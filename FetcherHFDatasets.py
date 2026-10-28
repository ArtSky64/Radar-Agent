import asyncio
import json
import logging
import httpx
from datetime import datetime, timezone
import config
from pydantic import BaseModel, Field
import re

try:
    from pydantic_ai import Agent
    from agent_manager import get_model
except ImportError:
    Agent = None
    def get_model(): return None

logger = logging.getLogger("hf_datasets_fetcher")

# Тег карточки датасета вида 'arxiv:2310.12345' (допускаем суффикс версии v2)
ARXIV_TAG_RE = re.compile(r"^arxiv:(\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)
ARXIV_ID_RE = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)


def extract_dataset_papers(tags: list, paperswithcode_id: str | None) -> list[dict]:
    """
    ТЗ 3.1.1: из tags карточки датасета достаём 'arxiv:XXXX.YYYYY', а также проверяем
    поле paperswithcode_id (если там лежит arXiv ID). Возвращает элементы related_links
    типа 'paper' (ТЗ п.5): {"type": "paper", "name": "arXiv:ID", "url": ".../papers/ID"}.
    """
    arxiv_ids: list[str] = []
    for tag in tags or []:
        match = ARXIV_TAG_RE.match(str(tag).strip())
        if match:
            arxiv_ids.append(match.group(1))
    # paperswithcode_id обычно — slug датасета в PwC, а не arXiv ID; такой slug
    # статьёй не является и в related_links не попадает. Берём только значение,
    # которое реально выглядит как arXiv ID.
    if paperswithcode_id:
        match = ARXIV_ID_RE.match(str(paperswithcode_id).strip())
        if match:
            arxiv_ids.append(match.group(1))

    return [
        {
            "type": "paper",
            "name": f"arXiv:{arxiv_id}",
            "url": config.HF_PAPER_URL_TEMPLATE.format(arxiv_id=arxiv_id),
        }
        for arxiv_id in dict.fromkeys(arxiv_ids)  # дедуп с сохранением порядка
    ]


async def fetch_dataset_models_top3(client: httpx.AsyncClient, dataset_id: str) -> list[str] | None:
    """
    ТЗ 3.1.2: топ-3 модели, обученные на датасете, по downloads.
    Возвращает короткие названия моделей (без автора) для top_items.
    None — запрос не удался (неизвестно, есть ли модели); [] — моделей точно нет.
    """
    url = config.HF_DATASET_MODELS_API.format(dataset_id=dataset_id)
    try:
        resp = await client.get(url, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return None
        # API уже отсортирован по downloads, но дополнительно сортируем локально —
        # защита от изменения порядка ответа.
        data.sort(key=lambda model: model.get("downloads", 0) or 0, reverse=True)
        names = []
        for m in data:
            m_id = m.get("id") or m.get("modelId")
            if m_id:
                names.append(m_id.split("/")[-1])
            if len(names) == 3:
                break
        return names
    except Exception as e:
        logger.debug(f"Не удалось получить модели для датасета {dataset_id}: {e}")
        return None


async def check_dataset_has_spaces(client: httpx.AsyncClient, dataset_id: str) -> int:
    """
    Проверяет, есть ли на Hugging Face Spaces (демо), связанные с этим датасетом.
    Возвращает 1 если есть хотя бы один Space, иначе 0.
    """
    try:
        resp = await client.get(
            f"https://huggingface.co/api/spaces?search={dataset_id}&limit=1",
            timeout=8.0
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return 1
    except Exception as e:
        logger.debug(f"Не удалось проверить спейсы для {dataset_id}: {e}")
    return 0


def build_related_links(dataset_id: str, papers: list[dict],
                        top_models: list[str] | None, has_spaces: int = 0) -> list[dict]:
    """
    ТЗ 3.2 «Каталог + Топ-3» и п.5: собирает поле related_links.
    Кнопку каталога моделей не показываем только если API ответил и моделей точно нет;
    если запрос упал (None) — каталог всё равно валиден, ссылку оставляем.
    Если у датасета есть Spaces (демо) на HF — добавляем ссылку на Spaces.
    """
    links: list[dict] = list(papers)
    if top_models is None or top_models:
        entry = {
            "type": "models_catalog",
            "name": "Обученные модели",
            "url": config.HF_DATASET_MODELS_CATALOG_URL.format(dataset_id=dataset_id),
        }
        if top_models:
            entry["top_items"] = top_models
        links.append(entry)
    if has_spaces:
        links.append({
            "type": "spaces_catalog",
            "name": "Spaces (Демо)",
            "url": f"https://huggingface.co/spaces?search={dataset_id}",
        })
    return links


class SelectedDataset(BaseModel):
    id: str = Field(description="ID")
    russian_translation: str = Field(
        description=(
            "Подробная карточка датасета на русском языке со следующими разделами:\n"
            "• Назначение — для каких задач машинного обучения предназначен датасет и что позволяет исследовать или оценивать.\n"
            "• Состав и масштаб — количество объектов, примеров или заданий, основные категории данных.\n"
            "• Типы данных — модальности, форматы входных данных и особенности их содержимого.\n"
            "• Разметка — какие аннотации, метки классов, эталонные ответы или критерии оценки предусмотрены.\n"
            "• Применение и особенности — для каких моделей и сценариев подходит датасет, его ключевые отличия или ограничения."
        )
    )

class SelectionResult(BaseModel):
    selected_datasets: list[SelectedDataset] = Field(description="Selected datasets")

def _get_hf_dataset_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=SelectionResult,
        system_prompt=(
            "Ты — Senior ML Engineer. Тебе дают список новых или популярных датасетов (id, title, full_text).\n"
            "Отбери самые ценные датасеты.\n"
            "Для каждого выбранного датасета сформируй подробную карточку (russian_translation) строго на русском языке со следующими обязательными разделами:\n"
            "• Назначение — для каких задач машинного обучения предназначен датасет и что позволяет исследовать или оценивать.\n"
            "• Состав и масштаб — количество объектов, примеров или заданий, основные категории данных.\n"
            "• Типы данных — модальности, форматы входных данных и особенности их содержимого.\n"
            "• Разметка — какие аннотации, метки классов, эталонные ответы или критерии оценки предусмотрены.\n"
            "• Применение и особенности — для каких моделей и сценариев подходит датасет, его ключевые отличия или ограничения."
        )
    )

def clean_hf_readme(text: str) -> str:
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"^[#]+\s+", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "").replace("*", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

async def _fetch_readme_fast(client: httpx.AsyncClient, dataset_id: str) -> str:
    url = f"https://huggingface.co/datasets/{dataset_id.strip()}/raw/main/README.md"
    try:
        response = await client.get(url, follow_redirects=True)
        if response.status_code == 200:
            return response.text
    except Exception as e:
        logger.debug(f"Failed to fetch readme for {dataset_id}: {e}")
    return ""


async def fetch_dataset_readme_directly(dataset_id: str) -> str:
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        return await _fetch_readme_fast(client, dataset_id)

async def _fetch_dataset_ids(url: str) -> list[dict]:
    """Один запрос к HF API datasets, возвращает сырой список объектов."""
    async with httpx.AsyncClient(trust_env=False) as client:
        resp = await client.get(url, timeout=15.0)
        resp.raise_for_status()
        return resp.json()


async def fetch_hf_datasets_by_mode(mode: str) -> list[dict]:
    articles_payload = []
    base_url = "https://huggingface.co/api/datasets"

    if mode == "trending":
        # Полная витрина мировых трендов (соответствует https://huggingface.co/datasets)
        urls = [f"{base_url}?sort=trendingScore&direction=-1&limit=30"]
    elif mode == "trending_ru":
        # Российские трендовые датасеты:
        # 1) https://huggingface.co/datasets?language=language:ru&sort=trending
        # 2) https://huggingface.co/datasets?language=language:ru,language:rus&sort=trending
        # 3) https://huggingface.co/datasets?language=language:rus&sort=trending
        urls = [
            f"{base_url}?sort=trendingScore&direction=-1&filter=language:ru&limit=30",
            f"{base_url}?sort=trendingScore&direction=-1&filter=language:rus&limit=30",
            f"{base_url}?sort=trendingScore&direction=-1&filter=language:ru,language:rus&limit=30",
        ]
    else:
        logger.warning(f"Unknown mode: {mode}")
        return []

    logger.info(f"Fetching HF Datasets (mode={mode})...")

    try:
        results = await asyncio.gather(
            *[_fetch_dataset_ids(u) for u in urls], return_exceptions=True
        )

        # Дедуп по id датасета (author/dataset_name)
        merged: dict[str, dict] = {}
        for data in results:
            if isinstance(data, Exception):
                logger.error(f"Error fetching HF datasets ({mode}): {data}")
                continue
            for item in data:
                d_id = item.get("id")
                if not d_id:
                    continue

                if d_id not in merged:
                    merged[d_id] = item.copy()
                    merged[d_id]["tags"] = list(item.get("tags", []))
                else:
                    existing_tags = merged[d_id].get("tags", [])
                    incoming_tags = item.get("tags", [])
                    merged[d_id]["tags"] = list(dict.fromkeys(
                        existing_tags + incoming_tags
                    ))

        logger.info(f"Найдено {len(merged)} уникальных датасетов HF в режиме {mode}")

        merged_items = list(merged.items())
        async with httpx.AsyncClient(timeout=12.0, trust_env=False) as client:
            readmes = await asyncio.gather(*[_fetch_readme_fast(client, d_id) for d_id, _ in merged_items])

        all_candidates = []
        for idx, ((d_id, item), raw_readme) in enumerate(zip(merged_items, readmes), 1):
            rank_global = idx if mode == "trending" else 0
            rank_ru = idx if mode == "trending_ru" else 0
            clean_text = clean_hf_readme(raw_readme) if raw_readme else ""
            if len(clean_text) < 50:
                # Если README отсутствует или слишком короткий, формируем информативный фолбэк,
                # чтобы датасет НЕ пропадал из выборки и обязательно попал в итоговую выдачу
                api_desc = item.get("description") or ""
                clean_text = f"Датасет {d_id}. {api_desc}".strip()
                if len(clean_text) < 30:
                    clean_text = (
                        f"Датасет {d_id} — актуальный открытый датасет на платформе Hugging Face. "
                        f"Предназначен для задач обучения, тестирования и валидации моделей машинного обучения."
                    )

            raw_tags = item.get("tags", [])
            langs = [t.replace("language:", "") for t in raw_tags if t.startswith("language:")]

            # Найден через ru-фильтр ИЛИ содержит в тегах language:ru/rus -> ru
            is_russian = mode == "trending_ru" or "ru" in langs or "rus" in langs
            language = "ru" if is_russian else ", ".join(langs)

            # Очистка и извлечение содержательных тегов с сайта
            clean_tags = []
            for t in raw_tags:
                if not isinstance(t, str):
                    continue
                if t.startswith("task_categories:"):
                    tc = t.replace("task_categories:", "").strip()
                    if tc and tc not in clean_tags:
                        clean_tags.append(tc)
                elif not any(t.startswith(prefix) for prefix in (
                    "language:", "license:", "size_categories:",
                    "region:", "arxiv:", "format:", "modality:", "annotations_creators:",
                    "language_creators:", "source_datasets:", "multilinguality:"
                )):
                    if t not in clean_tags:
                        clean_tags.append(t)
            clean_tags = clean_tags[:6]
            if is_russian and "#Russian" not in clean_tags:
                clean_tags.insert(0, "#Russian")

            papers = extract_dataset_papers(raw_tags, item.get("paperswithcode_id"))

            all_candidates.append({
                "id": f"hf_dataset:{d_id}",
                "d_id": d_id,
                "title": d_id,
                "full_text": clean_text,
                "url": f"https://huggingface.co/datasets/{d_id}",
                "language": language,
                "tags": clean_tags,
                "papers": papers,
                "likes": int(item.get("likes", 0) or 0),
                "rank_global": rank_global,
                "rank_ru": rank_ru,
            })

        logger.info(f"Сформировано {len(all_candidates)} кандидатов HF datasets (mode={mode})")

        if not all_candidates:
            return []

        # Запрашиваем модели и спейсы для ВСЕХ кандидатов (все кандидаты попадают в выдачу)
        async with httpx.AsyncClient(trust_env=False) as client:
            models_coros = [fetch_dataset_models_top3(client, c["d_id"]) for c in all_candidates]
            spaces_coros = [check_dataset_has_spaces(client, c["d_id"]) for c in all_candidates]
            models_lists, spaces_flags = await asyncio.gather(
                asyncio.gather(*models_coros),
                asyncio.gather(*spaces_coros),
            )

        for candidate, top_models, has_spaces in zip(
            all_candidates, models_lists, spaces_flags
        ):
            d_id = candidate["d_id"]
            tags_str = ", ".join(candidate["tags"])
            dataset_text = (
                f"Датасет: {d_id}\n"
                f"URL: {candidate['url']}\n"
                f"Теги сайта: {tags_str}\n"
                f"Язык: {candidate['language']}\n\n"
                f"{candidate['full_text']}"
            )

            articles_payload.append({
                "title": f"[HF Dataset] {d_id}",
                "text": dataset_text,
                "source_url": candidate["url"],
                "source_type": "датасет",
                "language": candidate.get("language", ""),
                "tags": candidate.get("tags", []),
                "stars": candidate.get("likes", 0),
                "has_spaces": has_spaces,
                "rank_global": candidate.get("rank_global", 0),
                "rank_ru": candidate.get("rank_ru", 0),
                "related_links": build_related_links(
                    d_id, candidate.get("papers", []), top_models, has_spaces
                ),
            })

        logger.info(f"HF Datasets (mode={mode}): готово к сохранению {len(articles_payload)} датасетов.")

    except Exception as e:
        logger.error(f"Error in mode {mode}: {e}")

    return articles_payload

def stream_hf_datasets_by_mode(mode: str):
    articles = asyncio.run(fetch_hf_datasets_by_mode(mode))
    for article in articles:
        yield article


#закоментирована за отсутствием необходимости + работает от старого режима query
# def stream_hf_datasets(query: str = "machine learning"):
#     """Алиас для обратной совместимости со старыми тестами и вызовами."""
#     yield from stream_hf_datasets_by_mode("query")
