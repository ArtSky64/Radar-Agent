import asyncio
import json
import os
import sys
import time
import httpx
import logging
import re
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Изолированный импорт для работы с реальным LLM-агентом
try:
    from pydantic_ai import Agent
    from agent_manager import get_model
except ImportError:
    Agent = None
    def get_model(): return None

load_dotenv()
logger = logging.getLogger("github_fetcher")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# === ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМА ===
IS_TEST_MODE = False

# трендовые периоды для trending-страницы
TRENDING_PERIODS = ("daily", "weekly", "monthly")


# === 1. СХЕМА ДЛЯ ИИ-ОТБОРЩИКА ===
#
# ВАЖНО: агент отвечает ТОЛЬКО за отбор id, без перевода/пересказа.
# Для дедупликации и векторизации нужен оригинальный английский текст
# описания репозитория как есть — если пропустить его через LLM (даже
# просто для перевода), в текст неизбежно попадут перефразировки модели,
# и сравнение векторов станет менее точным (мы сравниваем разные статьи
# об одном репо, а не то, что каждый раз по-своему написала нейронка).
# Тот же принцип уже применён в kaggle_fetcher.py и mcp_fetcher_arxiv.py.
class SelectionResult(BaseModel):
    selected_ids: list[str] = Field(
        description="Список id (до 5) отобранных репозиториев вида author/repo"
    )


# === 1.1 МОК ДЛЯ ТЕСТИРОВАНИЯ ===
class MockRunResult:
    def __init__(self, output_data: SelectionResult):
        self.output = output_data

class MockAgent:
    async def run(self, prompt: str) -> MockRunResult:
        logger.info("[MOCK] Агент получил промпт. Имитация генерации ответа (1 сек)...")
        await asyncio.sleep(1)

        test_id = "test-author/test-repo"
        try:
            json_str = prompt.split("Кандидаты для анализа:\n")[-1]
            candidates = json.loads(json_str)
            if candidates:
                test_id = candidates[0]["id"]
        except Exception:
            pass

        mock_data = SelectionResult(selected_ids=[test_id])
        return MockRunResult(mock_data)

def _get_github_agent():
    if IS_TEST_MODE:
        return MockAgent()

    return Agent(
        model=get_model(),
        output_type=SelectionResult,
        system_prompt=(
            "Ты — Senior Developer. Тебе дают JSON со списком набирающих "
            "популярность репозиториев на GitHub (id, title, full_text).\n"
            "ТВОЯ ЗАДАЧА: отбери до 5 самых перспективных и релевантных "
            "тематике AI/ML проектов. Верни только список их id. Текст "
            "описания менять, переводить или пересказывать не нужно — "
            "он используется как есть, в оригинале."
        )
    )

#search api функция
async def fetch_github_trending(days_back: int = 10, limit: int = 50, language: str = "Python") -> list[dict]:

    articles_payload = []
    
    # Считаем дату отсечки (например, 7 дней назад)
    date_cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime('%Y-%m-%d')
    query = f"created:>{date_cutoff}"
    if language:
        query += f" language:{language}"
    
    url = "https://api.github.com/search/repositories"
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": limit
    }
    
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }
    
    # GitHub ограничивает поиск без токена (10 запросов в минуту). С токеном - 30.
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    else:
        logger.warning("GITHUB_TOKEN не задан. Используется анонимный доступ (жесткие лимиты API).")

    # Прокси (если нужен)
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")
    if proxy_url:
        proxy_url = proxy_url.strip()
        if not proxy_url.startswith(("http://", "https://")):
            proxy_url = f"http://{proxy_url}"

    logger.info(f"Запрос к GitHub API: поиск трендов с {date_cutoff} (query='{query}')...")
    
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False, proxy=proxy_url) as client:
            response = await client.get(url, params=params, headers=headers, follow_redirects=True)
            
            if response.status_code == 403:
                logger.error("Лимит запросов GitHub API исчерпан. Добавьте GITHUB_TOKEN в .env.")
                return articles_payload
                
            response.raise_for_status()
            data = response.json()
            
            items = data.get("items", [])
            if not items:
                logger.info("Ничего не найдено.")
                return articles_payload
                
            all_candidates = []
            for item in items:
                repo_name = item.get("full_name")
                description = item.get("description") or "Нет описания."
                html_url = item.get("html_url")
                stars = item.get("stargazers_count", 0)
                language = item.get("language") or "Не указан"
                
                # Фильтруем пустые/нерелевантные
                if len(description) < 10:
                    continue
                    
                all_candidates.append({
                    "id": repo_name,
                    "title": repo_name,
                    "full_text": f"Language: {language} | Stars: {stars}\nDescription: {description}",
                    "url": html_url
                })

            if not all_candidates:
                return articles_payload

            return all_candidates

    except httpx.RequestError as e:
        logger.error(f"Ошибка сети при запросе к GitHub: {type(e).__name__}: {e}")
    except Exception as e:
        logger.error(f"Сбой в пайплайне GitHub: {e}")

    return articles_payload


async def select_via_llm(candidates: list[dict], limit: int = 30) -> list[dict]:
    """
    Отбирает топ-5 репозиториев через LLM.
    Если vLLM недоступен — фолбэк: берём топ-5 по порядку (они уже отсортированы
    по звёздам из GitHub Search API).
    """
    if not candidates:
        return []

    fresh_candidates = candidates[:limit]
    candidates_by_id = {c["id"]: c for c in fresh_candidates}

    def _build_payload(ids: list[str]) -> list[dict]:
        result = []
        for sid in ids:
            original = candidates_by_id.get(sid)
            if not original:
                logger.warning(f"Агент вернул неизвестный id, пропущено: {sid}")
                continue
            item = {
                "title": f"[GitHub] {original['title']}",
                "text": original["full_text"],
                "source_url": original["url"],
            }
            if original.get("stars_this_period") is not None:
                item["stars_this_period"] = original["stars_this_period"]
            result.append(item)
        return result

    llm_input = [
        {"id": c["id"], "title": c["title"], "full_text": c["full_text"]}
        for c in fresh_candidates
    ]
    prompt = "Кандидаты для анализа:\n" + json.dumps(llm_input, ensure_ascii=False)

    start_time = time.perf_counter()
    try:
        agent = _get_github_agent()
        result = await agent.run(prompt)
        selected_ids = list(dict.fromkeys(result.output.selected_ids))[:5]
        logger.info("Агент завершил работу за %.2fs", time.perf_counter() - start_time)
        return _build_payload(selected_ids)
    except Exception as e:
        # vLLM не запущен или недоступен — не роняем пайплайн,
        # возвращаем топ-5 кандидатов по рейтингу звёзд (порядок из API).
        logger.warning(
            f"LLM-отбор недоступен ({type(e).__name__}: {e}). "
            "Фолбэк: берём топ-5 по звёздам без LLM-фильтрации."
        )
        return _build_payload(list(candidates_by_id.keys())[:5])

def _get_proxy_url() -> str | None:
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")
    if not proxy_url:
        return None
    proxy_url = proxy_url.strip()
    if not proxy_url.startswith(("http://", "https://")):
        proxy_url = f"http://{proxy_url}"
    return proxy_url


def _parse_trending_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    for row in soup.select("article.Box-row"):
        link = row.select_one("h2 a")
        if not link or not link.get("href"):
            continue
        full_name = link["href"].strip("/")          # "/owner/repo" -> "owner/repo"

        desc_tag = row.select_one("p")
        description = desc_tag.get_text(strip=True) if desc_tag else ""
        if len(description) < 10:                    # тот же фильтр, что в старой функции
            continue

        lang_tag = row.select_one('[itemprop="programmingLanguage"]')
        repo_language = lang_tag.get_text(strip=True) if lang_tag else "Не указан"

        stars_tag = row.select_one('a[href$="/stargazers"]')
        stars_total = 0
        if stars_tag:
            digits = re.sub(r"\D", "", stars_tag.get_text())
            stars_total = int(digits) if digits else 0

        # "1,234 stars today" / "5,600 stars this week" / "... this month"
        match = re.search(r"([\d,]+)\s+stars?\s+(?:today|this week|this month)",
                          row.get_text(" ", strip=True))
        stars_period = int(match.group(1).replace(",", "")) if match else 0

        candidates.append({
            "id": full_name,
            "title": full_name,
            "full_text": f"Language: {repo_language} | Stars: {stars_total}\nDescription: {description}",
            "url": f"https://github.com/{full_name}",
            "stars_this_period": stars_period,
        })
    return candidates


async def fetch_github_trending_page(period: str, language: str = "python") -> list[dict]:
    if period not in TRENDING_PERIODS:
        raise ValueError(f"period должен быть одним из {TRENDING_PERIODS}, получено: {period!r}")

    url = f"https://github.com/trending/{language.lower()}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; radar-agent/1.0)"}

    logger.info(f"Парсинг GitHub Trending: {url}?since={period}")
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False,
                                     proxy=_get_proxy_url()) as client:
            response = await client.get(url, params={"since": period},
                                        headers=headers, follow_redirects=True)
            response.raise_for_status()
            candidates = _parse_trending_html(response.text)

        if not candidates:
            # 200 OK, но карточек нет: скорее всего, сменилась вёрстка
            logger.warning("Trending вернул страницу без карточек: возможно, изменилась вёрстка.")
        return candidates

    except httpx.RequestError as e:
        logger.error(f"Ошибка сети при запросе Trending ({period}): {type(e).__name__}: {e}")
    except Exception as e:
        logger.error(f"Сбой парсинга Trending ({period}): {e}")
    return []


def filter_seen(candidates: list[dict], seen_ids: set[str]) -> list[dict]:
    """Убирает кандидатов, которые уже были ВЫБРАНЫ раньше в этом прогоне."""
    return [c for c in candidates if c["id"] not in seen_ids]


def _repo_id_from_url(url: str) -> str:
    return url.removeprefix("https://github.com/")



async def _get_articles_via_llm(fetch_coro):
    candidates = await fetch_coro
    return await select_via_llm(candidates)

#старая функция на случай если с новой что то будет не так 
def stream_github_articles(days_back: int = 10, limit: int = 50, language: str = "Python"):
    """Синхронный генератор-адаптер: GitHub trending → LLM-отбор → статьи."""
    articles = asyncio.run(_get_articles_via_llm(
        fetch_github_trending(days_back, limit, language)
    ))
    for article in articles:
        yield article

def stream_github_articles_v2(days_back: int = 10, limit: int = 50, language: str = "Python",
                              seen_ids: set[str] | None = None):
    """Search API -> фильтр уже выбранных -> LLM -> запоминаем выбранные."""
    async def _run():
        candidates = await fetch_github_trending(days_back, limit, language)
        if seen_ids is not None:
            candidates = filter_seen(candidates, seen_ids)
        selected = await select_via_llm(candidates)
        if seen_ids is not None:
            seen_ids.update(_repo_id_from_url(a["source_url"]) for a in selected)
        return selected

    for article in asyncio.run(_run()):
        yield article


def stream_github_trending_page_articles(period: str, language: str = "python",
                                         seen_ids: set[str] | None = None):
    """Trending-страница -> фильтр уже выбранных -> LLM -> запоминаем выбранные."""
    async def _run():
        candidates = await fetch_github_trending_page(period, language)
        if seen_ids is not None:
            candidates = filter_seen(candidates, seen_ids)
        selected = await select_via_llm(candidates)
        if seen_ids is not None:
            seen_ids.update(_repo_id_from_url(a["source_url"]) for a in selected)
        return selected

    for article in asyncio.run(_run()):
        yield article

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    print("ТЕСТОВЫЙ ЗАПУСК GITHUB FETCHER")
    res = asyncio.run(_get_articles_via_llm(fetch_github_trending()))
    print(f"\nПолучено репозиториев: {len(res)}\n")
    print(json.dumps(res, indent=2, ensure_ascii=False))
