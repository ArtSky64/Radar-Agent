import asyncio
import json
import logging
import os
import re
import time
from typing import Generator
from dotenv import load_dotenv
import httpx
from pydantic import BaseModel, Field, ValidationError

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

try:
    from pydantic_ai import Agent
    from agent_manager import get_model
except ImportError:
    Agent = None
    def get_model():
        return None

load_dotenv()
logger = logging.getLogger("mcp_fetcher_kaggle")

KAGGLE_BASE_URL = "https://www.kaggle.com"
KAGGLE_API_URL = "https://www.kaggle.com/api/v1"
KAGGLE_TRENDING_URL = "https://www.kaggle.com/datasets?topic=trendingDataset"

CANDIDATES_LIMIT = 20
FINAL_MATERIALS_COUNT = 20
DEFAULT_USER_AGENT = "Kaggle/v1"
TIMEOUT_SECONDS = 20.0


# --- Схема для LLM-селектора ---

class SelectionResult(BaseModel):
    selected_ids: list[str] = Field(
        default_factory=list,
        description=f"Список id (до {FINAL_MATERIALS_COUNT}) наиболее интересных и качественных датасетов"
    )


def _get_selector_agent() -> Agent | None:
    if Agent is None:
        return None
    try:
        model = get_model()
        if not model:
            return None
        return Agent(
            model=model,
            output_type=SelectionResult,
            system_prompt=(
                "Ты — технический аналитик и эксперт по машинному обучению, отбирающий материалы для базы знаний по ИИ.\n\n"
                f"Тебе передан JSON-список актуальных реальных трендовых датасетов с Kaggle (раздел Trending Datasets). "
                "У каждого кандидата есть поля: id, title, description, tags, votes, kernels. "
                "Список уже отсортирован по актуальности Kaggle Trending.\n\n"
                f"Отбери до {FINAL_MATERIALS_COUNT} наиболее качественных, интересных и практически полезных "
                "датасетов для специалистов по AI, ML, Deep Learning и Data Science. Материалы низкого "
                "качества, пустышки или неинформативные карточки без данных игнорируй.\n\n"
                "Твоя ЕДИНСТВЕННАЯ задача — вернуть список id выбранных датасетов. "
                "Текст менять или переводить не нужно.\n\n"
                f"Если подходящих датасетов меньше {FINAL_MATERIALS_COUNT} — верни столько, "
                "сколько нашлось. Если ни один материал не подходит — верни пустой список."
            )
        )
    except Exception as e:
        logger.warning(f"Не удалось инициализировать LLM-агента отбора: {e}")
        return None


# --- HTTP-клиент и доступ к Kaggle API ---

def _get_proxy_url() -> str | None:
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")
    if not proxy_url:
        return None
    proxy_url = proxy_url.strip()
    if not proxy_url.startswith(("http://", "https://")):
        proxy_url = f"http://{proxy_url}"
    return proxy_url


def _get_auth() -> tuple[str, str] | None:
    user = os.getenv("KAGGLE_USERNAME", "").strip()
    key = os.getenv("KAGGLE_KEY", "").strip()
    if user and key:
        return (user, key)
    return None


def _create_http_client() -> httpx.AsyncClient:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }
    proxy = _get_proxy_url()
    client_kwargs = {
        "headers": headers,
        "timeout": TIMEOUT_SECONDS,
        "follow_redirects": True,
        "trust_env": True,
    }
    if proxy:
        client_kwargs["proxy"] = proxy

    auth = _get_auth()
    if auth:
        client_kwargs["auth"] = auth

    return httpx.AsyncClient(**client_kwargs)


# --- Извлечение метаданных ---

def _extract_tags(detail: dict, list_item: dict) -> list[str]:
    """Извлекает нативные теги Kaggle из детальной карточки или списка."""
    raw_tags = detail.get("tags") or list_item.get("tags") or []
    tags: list[str] = []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")

    for t in raw_tags:
        if isinstance(t, dict):
            name = t.get("name") or t.get("title") or t.get("ref") or t.get("nameNullable")
            if name:
                tags.append(str(name).strip())
        elif isinstance(t, str) and t.strip():
            tags.append(t.strip())

    return list(dict.fromkeys(tags))


def _extract_kernel_count(detail: dict, list_item: dict) -> int | None:
    """Извлекает счётчик решений (ноутбуков / kernels) с Kaggle."""
    for source in (detail, list_item):
        if not isinstance(source, dict):
            continue
        for key in ("scriptCount", "kernelCount", "totalKernels", "kernelsCount"):
            val = source.get(key)
            if val is not None and not isinstance(val, bool):
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
    return None


def _extract_vote_count(detail: dict, list_item: dict) -> int:
    """Извлекает количество голосов (votes)."""
    # В веб-выдаче GetTopicalDatasets голоса лежат в voteButton.totalVotes
    if isinstance(list_item, dict):
        vb = list_item.get("voteButton")
        if isinstance(vb, dict) and "totalVotes" in vb:
            try:
                return int(vb["totalVotes"])
            except (TypeError, ValueError):
                pass

    for source in (detail, list_item):
        if not isinstance(source, dict):
            continue
        for key in ("voteCount", "totalVotes", "votes"):
            val = source.get(key)
            if val is not None and not isinstance(val, bool):
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
    return 0


def _extract_full_text(detail: dict, list_item: dict) -> str:
    """Формирует текстовое описание датасета для векторного поиска и анализа."""
    desc = detail.get("description") or list_item.get("description") or ""
    subtitle = detail.get("subtitle") or list_item.get("subtitle") or ""
    title = detail.get("title") or list_item.get("title") or list_item.get("datasetSlug") or ""

    parts = []
    if subtitle and subtitle.strip() and subtitle.strip() not in desc:
        parts.append(subtitle.strip())
    if desc and desc.strip():
        parts.append(desc.strip())

    if parts:
        return "\n\n".join(parts)

    return title.strip() or "Описание датасета отсутствует."


def _build_kaggle_code_link(code_url: str, count: int | None) -> dict:
    """Формирует элемент related_links типа kaggle_code со счётчиком решений."""
    link = {
        "type": "kaggle_code",
        "name": "Решения (Code)",
        "url": code_url,
    }
    if count is not None:
        link["count"] = count
    return link


# --- Сбор кандидатов с Kaggle ---

async def _fetch_dataset_detail(client: httpx.AsyncClient, ref: str) -> dict:
    url = f"{KAGGLE_API_URL}/datasets/view/{ref}"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            return resp.json()
        logger.debug(f"Kaggle detail API для {ref} вернул код {resp.status_code}")
    except Exception as e:
        logger.debug(f"Не удалось получить детали датасета {ref}: {e}")
    return {}


async def _fetch_web_trending_datasets_via_playwright(limit: int = CANDIDATES_LIMIT) -> list[dict]:
    """
    Загружает реальную витрину трендов Kaggle (https://www.kaggle.com/datasets?topic=trendingDataset)
    через Playwright, перехватывая ответ GetTopicalDatasets.
    Именно этот список видит пользователь на сайте в разделе Trending Datasets.
    """
    if async_playwright is None:
        logger.info("Playwright не установлен, используем API v1.")
        return []

    logger.info("Сбор реальных трендов Kaggle через веб-витрину (topic=trendingDataset)...")
    captured: list[dict] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def on_response(response):
                if "GetTopicalDatasets" in response.url:
                    try:
                        data = await response.json()
                        if data and "datasets" in data:
                            captured.append(data)
                    except Exception:
                        pass

            page.on("response", on_response)
            await page.goto(KAGGLE_TRENDING_URL, timeout=30000, wait_until="networkidle")
            await browser.close()
    except Exception as e:
        logger.warning(f"Не удалось получить витрину трендов через Playwright: {e}")
        return []

    if not captured or not captured[0].get("datasets"):
        return []

    raw_datasets = captured[0]["datasets"][:limit]
    logger.info(f"Успешно перехвачено {len(raw_datasets)} реальных трендовых датасетов с витрины Kaggle.")

    normalized = []
    for it in raw_datasets:
        # datasetUrl вида '/datasets/kaggle/the-pokemon-company-...'
        ds_url = it.get("datasetUrl", "")
        ref = ds_url.removeprefix("/datasets/").strip("/")
        if not ref or "/" not in ref:
            slug = it.get("datasetSlug")
            owner = it.get("ownerName") or "kaggle"
            ref = f"{owner}/{slug}" if slug else ""

        if not ref:
            continue

        normalized.append({
            "ref": ref,
            "url": f"{KAGGLE_BASE_URL}/datasets/{ref}",
            "scriptCount": it.get("scriptCount", 0),
            "voteButton": it.get("voteButton", {}),
            "datasetSlug": it.get("datasetSlug", ""),
            "raw_item": it,
        })

    return normalized


async def _collect_trending_dataset_candidates(client: httpx.AsyncClient, limit: int = CANDIDATES_LIMIT) -> list[dict]:
    """
    Собирает трендовые датасеты Kaggle:
    1. Приоритетно: реальная витрина трендов (topic=trendingDataset).
    2. Фолбэк: API v1 datasets/list?sortBy=hottest.
    3. Обогащение детальными карточками (названия, README, теги, точные решения).
    """
    # Шаг 1: попытка взять точную витрину веб-трендов (как на сайте)
    web_candidates = await _fetch_web_trending_datasets_via_playwright(limit=limit)

    items_to_enrich = []
    if web_candidates:
        items_to_enrich = web_candidates
    else:
        # Фолбэк: стандартный API v1
        logger.info("Запрос трендовых датасетов Kaggle через API v1 (sortBy=hottest)...")
        try:
            resp = await client.get(f"{KAGGLE_API_URL}/datasets/list?sortBy=hottest&page=1")
            resp.raise_for_status()
            raw_items = resp.json()
            if isinstance(raw_items, list):
                items_to_enrich = raw_items[:limit]
        except Exception as e:
            logger.error(f"Ошибка при запросе API v1 datasets/list: {e}")
            return []

    if not items_to_enrich:
        logger.warning("Не удалось получить кандидатов трендовых датасетов Kaggle.")
        return []

    logger.info(f"Обогащение подробными карточками {len(items_to_enrich)} датасетов Kaggle...")
    tasks = [_fetch_dataset_detail(client, it.get("ref", "")) for it in items_to_enrich]
    details = await asyncio.gather(*tasks, return_exceptions=True)

    candidates = []
    for it, det in zip(items_to_enrich, details):
        if not isinstance(det, dict):
            det = {}

        ref = it.get("ref") or f"{it.get('ownerRef')}/{it.get('slug')}"
        if not ref or "/" not in str(ref):
            continue

        # Название: из детального API либо slug
        title = det.get("title") or it.get("title") or it.get("datasetSlug") or ref
        url = it.get("url") or f"{KAGGLE_BASE_URL}/datasets/{ref}"
        kernel_count = _extract_kernel_count(det, it)
        vote_count = _extract_vote_count(det, it)
        tags = _extract_tags(det, it)
        full_text = _extract_full_text(det, it)

        code_url = f"{url}/code"
        related_links = [_build_kaggle_code_link(code_url, kernel_count)]

        candidates.append({
            "id": f"dataset:{ref}",
            "ref": ref,
            "title": title,
            "full_text": full_text,
            "url": url,
            "tags": tags,
            "votes": vote_count,
            "kernel_count": kernel_count,
            "related_links": related_links,
        })

    logger.info(f"Сформировано {len(candidates)} кандидатов трендовых датасетов Kaggle.")
    return candidates


# --- Основной публичный асинхронный интерфейс ---

async def fetch_trending_kaggle_datasets(limit: int = FINAL_MATERIALS_COUNT) -> list[dict]:
    """
    Собирает актуальные трендовые датасеты Kaggle:
    1. Запрашивает реальную витрину трендов (topic=trendingDataset).
    2. Обогащает метаданными: счётчик решений (kernels), теги, голоса (votes), полный текст.
    3. Возвращает все трендовые датасеты для сохранения в БД и выдачи на фронтенде.
    """
    async with _create_http_client() as client:
        candidates = await _collect_trending_dataset_candidates(client, limit=limit)

    if not candidates:
        logger.warning("Нет трендовых кандидатов Kaggle для обработки.")
        return []

    articles_payload = []
    for idx, orig in enumerate(candidates[:limit], 1):
        kc = orig.get("kernel_count")
        tags_str = ", ".join(orig.get("tags", []))
        dataset_text = (
            f"Датасет: {orig['title']}\n"
            f"URL: {orig['url']}\n"
            f"Теги сайта: {tags_str}\n\n"
            f"{orig['full_text']}"
        )
        articles_payload.append({
            "title": f"[Kaggle] {orig['title']}",
            "text": dataset_text,
            "source_url": orig["url"],
            "source_type": "датасет",
            "tags": orig["tags"],
            "stars": orig["votes"],
            "upvotes": orig["votes"],
            "has_code": 1 if kc and kc > 0 else 0,
            "has_spaces": 0,
            "rank_global": idx,
            "rank_ru": 0,
            "related_links": orig["related_links"],
        })

    logger.info(f"Финальный результат Kaggle: {len(articles_payload)} материалов готово к сохранению.")
    return articles_payload


# --- Алиасы и синхронный интерфейс для main.py ---

async def fetch_materials_via_mcp(query: str | None = None) -> list[dict]:
    """Алиас для обратной совместимости. Запрашивает реальные трендовые датасеты Kaggle."""
    return await fetch_trending_kaggle_datasets(limit=FINAL_MATERIALS_COUNT)


def stream_kaggle_articles(query: str | None = None, limit: int = FINAL_MATERIALS_COUNT) -> Generator[dict, None, None]:
    """
    Синхронный генератор трендовых датасетов Kaggle (без фильтрации по тегам).
    Аргумент query сохранен для обратной совместимости, но не навязывает теговый поиск.
    """
    articles = asyncio.run(fetch_trending_kaggle_datasets(limit=limit))
    for article in articles:
        yield article


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=== ЗАПУСК: СБОР РЕАЛЬНЫХ ТРЕНДОВЫХ ДАТАСЕТОВ KAGGLE ===")
    try:
        results = list(stream_kaggle_articles())
        print(f"\nУспешно получено датасетов: {len(results)}")
        for i, art in enumerate(results, 1):
            print(f"\n[{i}] {art['title']}")
            print(f"    URL: {art['source_url']}")
            print(f"    Votes: {art['stars']}, Has Code: {art['has_code']}")
            print(f"    Tags: {art['tags']}")
            print(f"    Links: {art['related_links']}")
            print(f"    Text preview: {art['text'][:150]}...")
    except Exception as e:
        print(f"\nКритическая ошибка: {e}")
