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
    analyze_github_repo_async,
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

        # Проверяем, является ли текущее описание заглушкой от упавшего LLM:
        is_mock_summary = bool(
            existing and (
                "ориентирован на решение прикладных задач в области AI/ML и разработки на Python" in (existing.get("summary") or "")
                or "Репозиторий полезен инженерам и дата-сайентистам" in (existing.get("summary") or "")
            )
        )

        # Репозиторий считается новым, если он только что добавлен или добавлен недавно (< 72 ч)
        is_recently_added = False
        if existing and existing.get("created_at"):
            try:
                created_str = str(existing["created_at"]).strip()
                if "T" in created_str:
                    c_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                else:
                    c_dt = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                is_recently_added = (datetime.now(timezone.utc) - c_dt).total_seconds() < 72 * 3600
            except Exception:
                is_recently_added = False

        if existing and not is_mock_summary:
            # Репозиторий уже есть в базе с качественным LLM-описанием — повторно в LLM не отправляем!
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
                "is_new": is_recently_added,
            }
            trending_results.append(item)
        else:
            # Новый репозиторий или репозиторий со старой заглушкой:
            new_count += 1
            action_label = "[ОБНОВЛЕНИЕ LLM-КАРТОЧКИ]" if (existing and is_mock_summary) else "[НОВЫЙ]"
            logger.info(f"[{idx}/{len(trending_candidates)}] {action_label} {repo_id} — парсинг README.md...")

            # Шаг 3: Спарсить информацию из readme.md
            readme_text = await fetch_repo_readme(repo_id)

            # Шаг 4 и 5: Отправить запрос в Qwen и получить карточку
            logger.info(f"Отправка запроса в Qwen для карточки '{repo_id}'...")
            card: GitHubRepoCard = await analyze_github_repo_async(
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
        stars_info = f"Stars: {r.get('stars', 0)}"
        if r.get("stars_this_period"):
            stars_info += f" (+{r['stars_this_period']} {r.get('period', '')})"

        print(f"\n#{idx:02d} {r['repo_name']} {status} — {stars_info}")
        print(f"    URL:         {r['source_url']}")
        print(f"    Описание:    {r['summary']}")
        print(f"    Направление: [{dirs}]")
        print(f"    Тип задачи:  [{tasks}]")
        print(f"    Теги:        [{tags}]")
    print("\n" + "=" * 90 + "\n")




if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    print("ЗАПУСК ОБНОВЛЕННОГО ПАЙПЛАЙНА GITHUB TRENDING (30 репозиториев weekly + monthly)")
    res = run_github_trending_pipeline(limit=30)
    print(f"Обработано репозиториев: {len(res)}")