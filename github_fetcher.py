import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel, Field

import config
from agent_manager import (
    GitHubRepoCard,
    analyze_github_repo,
    get_model,
)

load_dotenv()
logger = logging.getLogger("github_fetcher")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# === ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМА ===
IS_TEST_MODE = False

# Трендовые периоды для trending-страницы
TRENDING_PERIODS = ("daily", "weekly", "monthly")

# Московский часовой пояс (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))


def _get_proxy_url() -> str | None:
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")
    if not proxy_url:
        return None
    proxy_url = proxy_url.strip()
    if not proxy_url.startswith(("http://", "https://")):
        proxy_url = f"http://{proxy_url}"
    return proxy_url


# === 1. СХЕМА ДЛЯ ИИ-ОТБОРЩИКА (для обратной совместимости) ===
class SelectionResult(BaseModel):
    selected_ids: list[str] = Field(
        description="Список id (до 5) отобранных репозиториев вида author/repo"
    )


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

    try:
        from pydantic_ai import Agent
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
            ),
        )
    except Exception:
        return MockAgent()


# ==============================================================
# ПАРСИНГ HTML TRENDING И README
# ==============================================================

def _parse_trending_html(html: str) -> list[dict]:
    """Парсит HTML-страницу трендов GitHub (article.Box-row)."""
    import httpx
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    for row in soup.select("article.Box-row"):
        link = row.select_one("h2 a")
        if not link or not link.get("href"):
            continue
        full_name = link["href"].strip("/")

        desc_tag = row.select_one("p")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        lang_tag = row.select_one('[itemprop="programmingLanguage"]')
        repo_language = lang_tag.get_text(strip=True) if lang_tag else "Python"

        stars_tag = row.select_one('a[href$="/stargazers"]')
        stars_total = 0
        if stars_tag:
            digits = re.sub(r"\D", "", stars_tag.get_text())
            stars_total = int(digits) if digits else 0

        match = re.search(
            r"([\d,]+)\s+stars?\s+(?:today|this week|this month)",
            row.get_text(" ", strip=True),
        )
        stars_period = int(match.group(1).replace(",", "")) if match else 0

        candidates.append({
            "id": full_name,
            "title": full_name,
            "description": description,
            "full_text": f"Language: {repo_language} | Stars: {stars_total}\nDescription: {description}",
            "url": f"https://github.com/{full_name}",
            "stars_total": stars_total,
            "stars_this_period": stars_period,
        })
    return candidates


async def fetch_github_trending_page(period: str, language: str = "python") -> list[dict]:
    """Загружает страницу трендов GitHub для периода (weekly, monthly, daily)."""
    import httpx
    if period not in TRENDING_PERIODS:
        raise ValueError(f"period должен быть одним из {TRENDING_PERIODS}, получено: {period!r}")

    url = f"https://github.com/trending/{language.lower()}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    logger.info(f"Парсинг GitHub Trending: {url}?since={period}")
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False, proxy=_get_proxy_url()) as client:
            response = await client.get(url, params={"since": period}, headers=headers, follow_redirects=True)
            response.raise_for_status()
            candidates = _parse_trending_html(response.text)

        if not candidates:
            logger.warning(f"Trending ({period}) вернул страницу без карточек: возможно, изменилась вёрстка.")
        return candidates

    except Exception as e:
        logger.error(f"Сбой парсинга Trending ({period}): {e}")
        # Фолбэк на локальный trending.html, если есть в корне
        local_trending = os.path.join(config.BASE_DIR, "trending.html")
        if os.path.exists(local_trending):
            try:
                with open(local_trending, "r", encoding="utf-8") as f:
                    return _parse_trending_html(f.read())
            except Exception:
                pass
        return []


async def fetch_repo_readme(repo_name: str) -> str:
    """
    (Шаг 3 ТЗ) Парсит README.md для каждого нового репозитория.
    Трёхуровневый надежный сборщик:
      1) GitHub REST API с токеном / без токена (Accept: application/vnd.github.v3.raw);
      2) raw.githubusercontent.com (ветки main, master, HEAD);
      3) BeautifulSoup парсинг страницы репозитория github.com/owner/repo (#readme / article.markdown-body).
    """
    import httpx
    repo_name = repo_name.strip().strip("/")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    github_token = os.getenv("GITHUB_TOKEN")
    api_headers = {**headers, "Accept": "application/vnd.github.v3.raw"}
    if github_token:
        api_headers["Authorization"] = f"token {github_token}"

    proxy = _get_proxy_url()

    async with httpx.AsyncClient(timeout=15.0, trust_env=False, proxy=proxy) as client:
        # 1. Попытка через GitHub REST API
        try:
            api_url = f"https://api.github.com/repos/{repo_name}/readme"
            resp = await client.get(api_url, headers=api_headers, follow_redirects=True)
            if resp.status_code == 200 and len(resp.text.strip()) > 20:
                logger.info(f"README для {repo_name} успешно получен через GitHub API.")
                return resp.text.strip()
        except Exception as e:
            logger.debug(f"API readme не получен для {repo_name}: {e}")

        # 2. Попытка через raw.githubusercontent.com
        for branch in ("main", "master", "HEAD"):
            for filename in ("README.md", "readme.md", "README.rst", "README"):
                try:
                    raw_url = f"https://raw.githubusercontent.com/{repo_name}/{branch}/{filename}"
                    resp = await client.get(raw_url, headers=headers, follow_redirects=True)
                    if resp.status_code == 200 and len(resp.text.strip()) > 20:
                        logger.info(f"README для {repo_name} получен через raw ({branch}/{filename}).")
                        return resp.text.strip()
                except Exception:
                    pass

        # 3. Попытка через скрапинг HTML страницы репозитория
        try:
            html_url = f"https://github.com/{repo_name}"
            resp = await client.get(html_url, headers=headers, follow_redirects=True)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                readme_tag = soup.select_one("article.markdown-body") or soup.select_one("#readme")
                if readme_tag:
                    text = readme_tag.get_text(separator="\n", strip=True)
                    if len(text) > 30:
                        logger.info(f"README для {repo_name} получен через HTML-парсинг страницы.")
                        return text
        except Exception as e:
            logger.debug(f"HTML fallback не удался для {repo_name}: {e}")

    logger.warning(f"Не удалось извлечь README для {repo_name}. Будет использовано базовое описание.")
    return ""


# ==============================================================
# ПОЛНЫЙ ПАЙПЛАЙН ТРЕНДОВ GITHUB (ТЗ СОЗВОНА)
# ==============================================================

async def fetch_top_trending_repos(limit: int = 30) -> list[dict]:
    """
    (1) Получить ссылки на 30 трендовых репозиториев, удалить дубли.
    Источники:
      https://github.com/trending/python?since=weekly
      https://github.com/trending/python?since=monthly
    """
    candidates = []
    seen_ids = set()

    for period in ("weekly", "monthly"):
        try:
            items = await fetch_github_trending_page(period, language="python")
            for item in items:
                repo_id = item["id"].lower()
                if repo_id not in seen_ids:
                    seen_ids.add(repo_id)
                    item["trending_period"] = period
                    candidates.append(item)
                    if len(candidates) >= limit:
                        break
        except Exception as e:
            logger.error(f"Ошибка сбора трендов ({period}): {e}")
        if len(candidates) >= limit:
            break

    # Если вдруг weekly + monthly дали меньше 30, добираем из daily
    if len(candidates) < limit:
        try:
            items = await fetch_github_trending_page("daily", language="python")
            for item in items:
                repo_id = item["id"].lower()
                if repo_id not in seen_ids:
                    seen_ids.add(repo_id)
                    item["trending_period"] = "daily"
                    candidates.append(item)
                    if len(candidates) >= limit:
                        break
        except Exception as e:
            logger.debug(f"Добор из daily не удался: {e}")

    return candidates[:limit]


async def run_github_trending_pipeline_async(limit: int = 30) -> list[dict]:
    """
    РЕАЛИЗАЦИЯ ВСЕХ 7 ШАГОВ ТЗ:
    (1) Получить ссылки на 30 трендовых репозиториев, удалить дубли.
    (2) Проверить есть ли в базе каждый репозиторий.
    (3) Спарсить информацию из readme.md для каждого нового репозитория.
    (4) Отправить запрос для каждого нового репозитория в qwen.
    (5) Получить карточку для каждого нового репозитория (краткое описание 3-4 предложения + теги + направления 0-4 + типы задач 0-3).
    (6) Записать в базу итоговый результат (новые в articles, полный список в github_trending).
    (7) Выводить актуальный трендовый список (новые репозитории и старые репозитории, которые все еще в тренде).
    """
    from database import (
        init_db,
        get_article_by_url,
        save_article,
        save_github_trending,
    )

    init_db()

    # Шаг 1: Получение 30 трендовых репозиториев без дублей
    logger.info(f"=== ШАГ 1: Сбор топ-{limit} трендовых Python-репозиториев (weekly + monthly) ===")
    trending_candidates = await fetch_top_trending_repos(limit=limit)

    if not trending_candidates:
        logger.warning("Не удалось собрать трендовые репозитории.")
        return []

    logger.info(f"Собрано {len(trending_candidates)} уникальных трендовых репозиториев.")

    trending_results = []
    new_count = 0
    existing_count = 0

    for idx, repo in enumerate(trending_candidates, start=1):
        repo_id = repo["id"]
        repo_url = repo["url"]
        stars_total = repo.get("stars_total") or 0
        stars_period = repo.get("stars_this_period") or 0
        period = repo.get("trending_period") or "weekly"

        # Шаг 2: Проверить, есть ли в базе каждый репозиторий
        existing = get_article_by_url(repo_url)

        if existing:
            # Репозиторий уже есть в базе — повторно в LLM не отправляем!
            existing_count += 1
            logger.info(f"[{idx}/{len(trending_candidates)}] [УЖЕ В БАЗЕ (В ТРЕНДЕ)] {repo_id}")
            item = {
                "repo_name": repo_id,
                "title": existing.get("title") or f"[GitHub] {repo_id}",
                "source_url": repo_url,
                "url": repo_url,
                "summary": existing.get("summary") or repo.get("description", ""),
                "tags": existing.get("tags") or [],
                "directions": existing.get("directions") or [],
                "task_types": existing.get("task_types") or [],
                "stars": stars_total or existing.get("stars", 0),
                "stars_this_period": stars_period,
                "period": period,
                "is_new": False,
            }
            trending_results.append(item)
        else:
            # Новый репозиторий:
            new_count += 1
            logger.info(f"[{idx}/{len(trending_candidates)}] [НОВЫЙ] {repo_id} — парсинг README.md...")

            # Шаг 3: Спарсить информацию из readme.md
            readme_text = await fetch_repo_readme(repo_id)

            # Шаг 4 и 5: Отправить запрос в Qwen и получить карточку
            logger.info(f"Отправка запроса в Qwen для карточки '{repo_id}'...")
            card: GitHubRepoCard = analyze_github_repo(
                repo_name=repo_id,
                readme_text=readme_text or repo.get("description", ""),
                description=repo.get("description", ""),
            )

            item = {
                "repo_name": repo_id,
                "title": f"[GitHub] {repo_id}",
                "source_url": repo_url,
                "url": repo_url,
                "summary": card.summary,
                "tags": card.tags,
                "directions": card.directions,
                "task_types": card.task_types,
                "stars": stars_total,
                "stars_this_period": stars_period,
                "period": period,
                "is_new": True,
            }

            # Шаг 6: Записать в базу итоговый результат (новые в articles)
            save_article({
                "title": item["title"],
                "summary": item["summary"],
                "source_url": repo_url,
                "tags": item["tags"],
                "directions": item["directions"],
                "task_types": item["task_types"],
                "source_type": "репозиторий",
                "stars": stars_total,
                "period": period,
                "is_trending": 1,
            })
            trending_results.append(item)

    fetched_at = datetime.now(MSK_TZ).isoformat()
    for r in trending_results:
        r["fetched_at"] = fetched_at

    # Шаг 6 (финал): Сохранить полный актуальный слепок трендов (30 репозиториев)
    save_github_trending(trending_results)
    logger.info(
        f"Шаг 6 завершен: обновлена таблица трендов в БД "
        f"(Всего: {len(trending_results)}, Новых: {new_count}, Уже было: {existing_count}, Время: {fetched_at})."
    )

    # Шаг 7: Выводить актуальный трендовый список
    print_trending_summary(trending_results, fetched_at=fetched_at)

    return trending_results


def run_github_trending_pipeline(limit: int = 30) -> list[dict]:
    """Синхронная точка входа для пайплайна GitHub Trending."""
    return asyncio.run(run_github_trending_pipeline_async(limit=limit))


def print_trending_summary(trending_results: list[dict], fetched_at: str | None = None) -> None:
    """Шаг 7: Форматированный вывод актуального трендового списка."""
    ts_str = ""
    if fetched_at:
        try:
            ts = str(fetched_at).strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc).astimezone(MSK_TZ)
            else:
                dt = dt.astimezone(MSK_TZ)
            ts_str = f" (Время сбора: {dt.strftime('%d.%m.%Y %H:%M:%S')} МСК)"
        except Exception:
            ts_str = f" (Время сбора: {fetched_at})"

    print("\n" + "=" * 90)
    print(f"АКТУАЛЬНЫЙ ТРЕНДОВЫЙ СПИСОК GITHUB (ТОП-30: НОВЫЕ И ОСТАВШИЕСЯ В ТРЕНДЕ){ts_str}")
    print("=" * 90)
    for idx, r in enumerate(trending_results, start=1):
        status = "[НОВЫЙ В ТРЕНДЕ]" if r.get("is_new") else "[УЖЕ В БАЗЕ (В ТРЕНДЕ)]"
        dirs = ", ".join(r.get("directions") or []) or "нет"
        tasks = ", ".join(r.get("task_types") or []) or "нет"
        tags = ", ".join(r.get("tags") or []) or "нет"
        stars_info = f"⭐ {r.get('stars', 0)}"
        if r.get("stars_this_period"):
            stars_info += f" (+{r['stars_this_period']} {r.get('period', '')})"

        print(f"\n#{idx:02d} {r['repo_name']} {status} — {stars_info}")
        print(f"    URL:         {r['source_url']}")
        print(f"    Описание:    {r['summary']}")
        print(f"    Направление: [{dirs}]")
        print(f"    Тип задачи:  [{tasks}]")
        print(f"    Теги:        [{tags}]")
    print("\n" + "=" * 90 + "\n")



# ==============================================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ ДЛЯ СТАРЫХ ВЫЗОВОВ И ТЕСТОВ
# ==============================================================

async def select_via_llm(candidates: list[dict], limit: int = 30) -> list[dict]:
    """Отбирает топ репозиториев через LLM (для обратной совместимости)."""
    if not candidates:
        return []

    fresh_candidates = candidates[:limit]
    candidates_by_id = {c["id"]: c for c in fresh_candidates}

    def _build_payload(ids: list[str]) -> list[dict]:
        result = []
        for sid in ids:
            original = candidates_by_id.get(sid)
            if not original:
                continue
            item = {
                "title": f"[GitHub] {original['title']}",
                "text": original.get("full_text", ""),
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

    try:
        agent = _get_github_agent()
        res = await agent.run(prompt)
        selected_ids = list(dict.fromkeys(res.output.selected_ids))[:5]
        return _build_payload(selected_ids)
    except Exception:
        return _build_payload(list(candidates_by_id.keys())[:5])


async def fetch_github_trending(days_back: int = 10, limit: int = 50, language: str = "Python") -> list[dict]:
    """Search API метод (для обратной совместимости)."""
    import httpx
    date_cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime('%Y-%m-%d')
    query = f"created:>{date_cutoff}"
    if language:
        query += f" language:{language}"

    url = "https://api.github.com/search/repositories"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": limit}
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False, proxy=_get_proxy_url()) as client:
            response = await client.get(url, params=params, headers=headers, follow_redirects=True)
            if response.status_code == 200:
                items = response.json().get("items", [])
                candidates = []
                for item in items:
                    name = item.get("full_name")
                    desc = item.get("description") or "Нет описания."
                    stars = item.get("stargazers_count", 0)
                    lang = item.get("language") or "Не указан"
                    candidates.append({
                        "id": name,
                        "title": name,
                        "full_text": f"Language: {lang} | Stars: {stars}\nDescription: {desc}",
                        "url": item.get("html_url"),
                    })
                return candidates
    except Exception as e:
        logger.error(f"Search API error: {e}")
    return []


def filter_seen(candidates: list[dict], seen_ids: set[str]) -> list[dict]:
    return [c for c in candidates if c["id"] not in seen_ids]


def _repo_id_from_url(url: str) -> str:
    return url.removeprefix("https://github.com/")


def stream_github_articles(days_back: int = 10, limit: int = 50, language: str = "Python"):
    async def _run():
        cands = await fetch_github_trending(days_back, limit, language)
        return await select_via_llm(cands)
    for a in asyncio.run(_run()):
        yield a


def stream_github_articles_v2(days_back: int = 10, limit: int = 50, language: str = "Python",
                              seen_ids: set[str] | None = None):
    async def _run():
        cands = await fetch_github_trending(days_back, limit, language)
        if seen_ids is not None:
            cands = filter_seen(cands, seen_ids)
        selected = await select_via_llm(cands)
        if seen_ids is not None:
            seen_ids.update(_repo_id_from_url(a["source_url"]) for a in selected)
        return selected
    for a in asyncio.run(_run()):
        yield a


def stream_github_trending_page_articles(period: str, language: str = "python",
                                         seen_ids: set[str] | None = None):
    async def _run():
        cands = await fetch_github_trending_page(period, language)
        if seen_ids is not None:
            cands = filter_seen(cands, seen_ids)
        selected = await select_via_llm(cands)
        if seen_ids is not None:
            seen_ids.update(_repo_id_from_url(a["source_url"]) for a in selected)
        return selected
    for a in asyncio.run(_run()):
        yield a


def stream_github_trending_pipeline_articles(limit: int = 30):
    """Генератор карточек актуального трендового списка для пайплайна."""
    results = run_github_trending_pipeline(limit=limit)
    for r in results:
        yield {
            "title": r.get("title") or f"[GitHub] {r['repo_name']}",
            "summary": r["summary"],
            "text": r["summary"],
            "source_url": r["source_url"],
            "tags": r.get("tags", []),
            "directions": r.get("directions", []),
            "task_types": r.get("task_types", []),
            "source_type": "репозиторий",
            "stars": r.get("stars", 0),
            "period": r.get("period", ""),
            "is_new": r.get("is_new", False),
        }


if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    print("ЗАПУСК ОБНОВЛЕННОГО ПАЙПЛАЙНА GITHUB TRENDING (30 репозиториев weekly + monthly)")
    res = run_github_trending_pipeline(limit=30)
    print(f"Обработано репозиториев: {len(res)}")