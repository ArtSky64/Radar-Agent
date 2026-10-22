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


async def fetch_dataset_has_spaces(client: httpx.AsyncClient, dataset_id: str) -> bool | None:
    """
    ТЗ 3.1.3: есть ли спейсы, использующие датасет (запрос limit=3).
    В related_links хранится только ссылка на каталог, поэтому имена спейсов не нужны.
    None — запрос не удался.
    """
    url = config.HF_DATASET_SPACES_API.format(dataset_id=dataset_id)
    try:
        resp = await client.get(url, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return None
        return len(data) > 0
    except Exception as e:
        logger.debug(f"Не удалось получить спейсы для датасета {dataset_id}: {e}")
        return None


def build_related_links(dataset_id: str, papers: list[dict],
                        top_models: list[str] | None, has_spaces: bool | None) -> list[dict]:
    """
    ТЗ 3.2 «Каталог + Топ-3» и п.5: собирает поле related_links.
    Кнопку каталога не показываем только если API ответил и сущностей точно нет;
    если запрос упал (None) — каталог всё равно валиден, ссылку оставляем.
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
    if has_spaces is None or has_spaces:
        links.append({
            "type": "spaces_catalog",
            "name": "Spaces",
            "url": config.HF_DATASET_SPACES_CATALOG_URL.format(dataset_id=dataset_id),
        })
    return links


class SelectedDataset(BaseModel):
    id: str = Field(description="ID")
    russian_translation: str = Field(description="Summary in Russian")

class SelectionResult(BaseModel):
    selected_datasets: list[SelectedDataset] = Field(description="Selected datasets")

def _get_hf_dataset_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=SelectionResult,
        system_prompt=(
            "Ты — Senior ML Engineer. Тебе дают список новых или популярных "
            "датасетов (id, title, full_text). Отбери самые ценные. "
            "Напиши russian_translation: краткое описание на русском."
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

async def fetch_dataset_readme_directly(dataset_id: str) -> str:
    url = f"https://huggingface.co/datasets/{dataset_id.strip()}/raw/main/README.md"
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            response = await client.get(url, follow_redirects=True)
            if response.status_code == 200:
                return response.text
    except Exception as e:
        logger.debug(f"Failed to fetch readme for {dataset_id}: {e}")
    return ""

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
        urls = [f"{base_url}?sort=trendingScore&direction=-1&limit=50"]
    elif mode == "trending_ru":
        urls = [
            f"{base_url}?sort=trendingScore&direction=-1&filter=language:ru&limit=30",
            f"{base_url}?sort=trendingScore&direction=-1&filter=language:rus&limit=30",
        ]
    else:
        logger.warning(f"Unknown mode: {mode}")
        return []

    logger.info(f"Fetching HF Datasets (mode={mode})...")

    try:
        # Параллельные запросы (для trending_ru их два, для trending один)
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
                    # При совпадении ID объединяем теги из обоих ответов API.
                    existing_tags = merged[d_id].get("tags", [])
                    incoming_tags = item.get("tags", [])
                    merged[d_id]["tags"] = list(dict.fromkeys(
                        existing_tags + incoming_tags
                    ))

        all_candidates = []
        for d_id, item in merged.items():
            raw_readme = await fetch_dataset_readme_directly(d_id)
            if not raw_readme:
                continue
            clean_text = clean_hf_readme(raw_readme)
            if len(clean_text) < 50:
                continue

            tags = item.get("tags", [])
            langs = [t.replace("language:", "") for t in tags if t.startswith("language:")]

            # Найден через ru-фильтр ИЛИ содержит в тегах language:ru/rus -> ru
            is_russian = mode == "trending_ru" or "ru" in langs or "rus" in langs
            language = "ru" if is_russian else ", ".join(langs)

            # ТЗ 3.1.1: связанные статьи достаются из тех же сырых тегов, что и язык —
            # делаем это для всех кандидатов сразу, запрос к сети для этого не нужен.
            papers = extract_dataset_papers(tags, item.get("paperswithcode_id"))

            all_candidates.append({
                "id": f"hf_dataset:{d_id}",
                "title": d_id,
                "full_text": clean_text,
                "url": f"https://huggingface.co/datasets/{d_id}",
                "language": language,
                "tags": ["#Russian"] if is_russian else [],  # только исключение из ТЗ, без сырых HF-тегов
                "papers": papers,
                "likes": int(item.get("likes", 0) or 0),
            })

        print("Кандидатов после обработки README:", len(all_candidates))

        if not all_candidates:
            return []

        llm_input = [
            {"id": c["id"], "title": c["title"], "full_text": c["full_text"][:2500]}
            for c in all_candidates[:10]
        ]

        prompt = "Кандидаты:\n" + json.dumps(llm_input, ensure_ascii=False)
        agent = _get_hf_dataset_agent()
        if not agent:
            return []
        result = await agent.run(prompt)
        print("Модель выбрала:", result.output.selected_datasets)

        candidates_by_id = {c["id"]: c for c in all_candidates}

        # Собираем пары (результат LLM, оригинальный кандидат) только для реально
        # найденных датасетов — моделей/спейсов запрашиваем именно по этому
        # небольшому списку (а не по всем ~50 кандидатам), чтобы не перегружать API.
        selected: list[tuple] = []
        for res_item in result.output.selected_datasets:
            dataset_id = res_item.id.removeprefix("hf_dataset:")
            original = candidates_by_id.get(f"hf_dataset:{dataset_id}")
            if not original:
                logger.warning(
                    f"Выбранный датасет не найден среди кандидатов: {res_item.id}"
                )
                continue
            selected.append((dataset_id, res_item, original))

        if selected:
            async with httpx.AsyncClient(trust_env=False) as client:
                models_lists, spaces_flags = await asyncio.gather(
                    asyncio.gather(*[
                        fetch_dataset_models_top3(client, dataset_id) for dataset_id, _, _ in selected
                    ]),
                    asyncio.gather(*[
                        fetch_dataset_has_spaces(client, dataset_id) for dataset_id, _, _ in selected
                    ]),
                )

            for (dataset_id, res_item, original), top_models, has_spaces in zip(
                selected, models_lists, spaces_flags
            ):
                articles_payload.append({
                    "title": f"[HF Dataset] {original['title']}",
                    "text": f"Датасет: {original['title']}\n\nОписание:\n{res_item.russian_translation}",
                    "source_url": original["url"],
                    "language": original.get("language", ""),
                    "tags": original.get("tags", []),
                    "stars": original.get("likes", 0),
                    "related_links": build_related_links(
                        dataset_id, original.get("papers", []), top_models, has_spaces
                    ),
                })

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