from __future__ import annotations

import asyncio
import ast
import json
import logging
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

try:
    import httpx
except ImportError:
    httpx = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import config
from database import upsert_related_material

logger = logging.getLogger("papers_fetcher")


def _make_ssl_context(unverified: bool = False):
    import ssl
    if unverified:
        try:
            return ssl._create_unverified_context()
        except Exception:
            return None
    try:
        ctx = ssl.create_default_context()
        return ctx
    except Exception:
        try:
            return ssl._create_unverified_context()
        except Exception:
            return None


def _sync_http_get_json(url: str, timeout: float = 15.0):
    """Fallback-запрос через стандартную библиотеку urllib, если httpx не установлен."""
    req = urllib.request.Request(url, headers={"User-Agent": "AIML-Radar-Agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_make_ssl_context()) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate verify failed" in str(e):
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=_make_ssl_context(unverified=True)) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
            except Exception as e2:
                logger.debug(f"urllib unverified retry failed for {url}: {e2}")
        logger.debug(f"urllib request failed for {url}: {e}")
    return None


_PIPEWORX_BLOCKED = False


def _sync_http_post_json(url: str, payload: dict, timeout: float = 8.0):
    """Fallback POST-запрос через urllib (JSON-RPC 2.0 к Pipeworx gateway)."""
    global _PIPEWORX_BLOCKED
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AIML-Radar-Agent/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_make_ssl_context()) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 429):
            logger.warning(f"Pipeworx gateway вернул статус {e.code} (лимит запросов исчерпан). Переключаемся на локальные fallback.")
            _PIPEWORX_BLOCKED = True
        return None
    except Exception as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate verify failed" in str(e):
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=_make_ssl_context(unverified=True)) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e2:
                if e2.code in (401, 429):
                    _PIPEWORX_BLOCKED = True
                return None
            except Exception as e2:
                logger.debug(f"urllib POST unverified retry failed for {url}: {e2}")
        logger.debug(f"urllib POST failed for {url}: {e}")
    return None


async def _call_pipeworx_http(tool_name: str, arguments: dict, timeout: float = 6.0) -> str:
    """Прямой вызов инструмента через JSON-RPC 2.0 к Pipeworx gateway (fallback при сбоях MCP-библиотеки)."""
    global _PIPEWORX_BLOCKED
    if _PIPEWORX_BLOCKED:
        return ""
    url = config.PWC_MCP_URL
    if not url:
        return ""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    data = None
    if httpx is not None:
        try:
            async with httpx.AsyncClient(verify=False, timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                elif resp.status_code in (401, 429):
                    logger.warning(
                        f"Pipeworx gateway вернул статус {resp.status_code} (исчерпан лимит запросов). Отключаем запросы к шлюзу."
                    )
                    _PIPEWORX_BLOCKED = True
                    return ""
        except Exception as e:
            logger.debug(f"httpx JSON-RPC failed for {tool_name}: {e}")

    if data is None and not _PIPEWORX_BLOCKED:
        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, _sync_http_post_json, url, payload, timeout)
        except Exception as e:
            logger.debug(f"run_in_executor JSON-RPC failed for {tool_name}: {e}")

    if isinstance(data, dict):
        result = data.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list):
            return "\n".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("text"))
    return ""


# --- Попытка импорта MCP клиентов (Streamable HTTP и SSE) ---
try:
    from mcp import ClientSession
except ImportError:
    ClientSession = None

try:
    from mcp.client.streamable_http import streamable_http_client
except ImportError:
    try:
        from mcp.client.streamablehttp import streamablehttp_client as streamable_http_client
    except ImportError:
        streamable_http_client = None

try:
    from mcp.client.sse import sse_client
except ImportError:
    sse_client = None


def normalize_arxiv_id(raw_id: str) -> str:
    """
    Нормализует arXiv ID: удаляет URL-префиксы, версии v1, v2 и лишние символы.
    Примеры:
      'https://arxiv.org/abs/2407.12345v2' -> '2407.12345'
      'arxiv:2407.12345' -> '2407.12345'
      '2407.12345.pdf' -> '2407.12345'
    """
    if not raw_id:
        return ""
    text = str(raw_id).strip()
    text = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", text)
    text = re.sub(r"^https?://huggingface\.co/papers/", "", text)
    text = re.sub(r"^arxiv:", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\.pdf$", "", text, flags=re.IGNORECASE)
    # Удаляем версию v1, v2 в конце числового id
    text = re.sub(r"v\d+$", "", text, flags=re.IGNORECASE)
    return text.strip("/")



async def fetch_hf_daily_papers_for_date(client: httpx.AsyncClient | None, date_str: str) -> list[dict]:
    """
    Запрос GET /api/daily_papers?date=YYYY-MM-DD
    """
    url = f"https://huggingface.co/api/daily_papers?date={date_str}"
    try:
        data = None
        if client is not None and httpx is not None:
            response = await client.get(url, timeout=15.0)
            if response.status_code == 200:
                data = response.json()
            else:
                logger.warning(f"HF Papers для {date_str} вернул статус {response.status_code}")
                return []
        else:
            data = _sync_http_get_json(url, timeout=15.0)

        if not isinstance(data, list):
            logger.warning(f"Неожиданный формат ответа HF Papers для {date_str}: {type(data)}")
            return []

        today = datetime.now(timezone.utc).date()
        papers = []
        for item in data:
            paper_info = item.get("paper") if isinstance(item.get("paper"), dict) else item
            raw_id = paper_info.get("id") or item.get("id") or ""
            arxiv_id = normalize_arxiv_id(raw_id)
            if not arxiv_id:
                continue

            title = (paper_info.get("title") or item.get("title") or "").strip()
            summary = (paper_info.get("summary") or paper_info.get("abstract") or item.get("summary") or "").strip()
            upvotes = int(paper_info.get("upvotes") or item.get("upvotes") or 0)
            published_at = paper_info.get("publishedAt") or item.get("publishedAt") or date_str

            try:
                pub_date = datetime.fromisoformat(str(published_at)[:10]).date()
                period = "weekly" if (today - pub_date).days <= 7 else "monthly"
            except Exception:
                period = "weekly"

            github_repo = paper_info.get("githubRepo") or item.get("githubRepo") or ""
            project_page = paper_info.get("projectPage") or item.get("projectPage") or ""
            rel_links = []
            has_code = 0
            if github_repo:
                has_code = 1
                rel_links.append({"type": "github", "name": github_repo.split("/")[-1] if "/" in github_repo else "GitHub", "url": github_repo})
            if project_page:
                rel_links.append({"type": "project", "name": "Project Page", "url": project_page})

            rel_links.append({"type": "arxiv", "name": f"arXiv: {arxiv_id}", "url": f"https://arxiv.org/abs/{arxiv_id}"})

            papers.append({
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": summary,
                "upvotes": upvotes,
                "url": f"https://huggingface.co/papers/{arxiv_id}",
                "source": "hf",
                "published_at": published_at,
                "period": period,
                "has_code": has_code,
                "related_links": rel_links,
            })
        return papers
    except Exception as e:
        logger.warning(f"Ошибка при запросе HF Papers за {date_str}: {e}")
        return []


async def fetch_hf_official_trending(client: httpx.AsyncClient | None = None, limit: int = 100) -> list[dict]:
    """
    Запрос GET /api/daily_papers?sort=trending&limit=100
    Возвращает официальный живой топ трендов Hugging Face с веб-страницы huggingface.co/papers/trending.
    """
    url = f"https://huggingface.co/api/daily_papers?sort=trending&limit={limit}"
    try:
        data = None
        if client is not None and httpx is not None:
            response = await client.get(url, timeout=15.0)
            if response.status_code == 200:
                data = response.json()
        if data is None:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, _sync_http_get_json, url, 15.0)

        if not isinstance(data, list):
            return []

        today = datetime.now(timezone.utc).date()
        papers = []
        for item in data:
            paper_info = item.get("paper") if isinstance(item.get("paper"), dict) else item
            raw_id = paper_info.get("id") or item.get("id") or ""
            arxiv_id = normalize_arxiv_id(raw_id)
            if not arxiv_id:
                continue

            title = (paper_info.get("title") or item.get("title") or "").strip()
            summary = (paper_info.get("summary") or paper_info.get("abstract") or item.get("summary") or "").strip()
            upvotes = int(paper_info.get("upvotes") or item.get("upvotes") or 0)
            published_at = paper_info.get("publishedAt") or item.get("publishedAt") or ""

            try:
                pub_date = datetime.fromisoformat(str(published_at)[:10]).date()
                period = "weekly" if (today - pub_date).days <= 7 else "monthly"
            except Exception:
                period = "weekly"

            github_repo = paper_info.get("githubRepo") or item.get("githubRepo") or ""
            project_page = paper_info.get("projectPage") or item.get("projectPage") or ""
            rel_links = []
            has_code = 0
            if github_repo:
                has_code = 1
                rel_links.append({"type": "github", "name": github_repo.split("/")[-1] if "/" in github_repo else "GitHub", "url": github_repo})
            if project_page:
                rel_links.append({"type": "project", "name": "Project Page", "url": project_page})

            rel_links.append({"type": "arxiv", "name": f"arXiv: {arxiv_id}", "url": f"https://arxiv.org/abs/{arxiv_id}"})

            papers.append({
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": summary,
                "upvotes": upvotes,
                "url": f"https://huggingface.co/papers/{arxiv_id}",
                "source": "hf",
                "published_at": published_at,
                "period": period,
                "has_code": has_code,
                "related_links": rel_links,
            })
        logger.info(f"HF Official Trending: получено {len(papers)} трендовых статей")
        return papers
    except Exception as e:
        logger.warning(f"Ошибка при запросе официального HF Trending: {e}")
        return []


async def fetch_hf_trending(days: int = config.PAPERS_WINDOW_DAYS) -> list[dict]:
    """
    Тренды Hugging Face:
    1. Официальный мировой топ трендов через GET /api/daily_papers?sort=trending
    2. Агрегация архивов по дням (PAPERS_WINDOW_DAYS) для полного охвата за неделю и месяц
    """
    logger.info(f"Сбор HF Papers (официальный Trending + архив за {days} дней)...")
    all_papers: list[dict] = []
    today = datetime.now(timezone.utc).date()

    if httpx is not None:
        async with httpx.AsyncClient(headers={"User-Agent": "AIML-Radar-Agent/1.0"}) as client:
            trending_task = fetch_hf_official_trending(client, limit=100)
            tasks = [trending_task]
            for i in range(days):
                target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                tasks.append(fetch_hf_daily_papers_for_date(client, target_date))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    all_papers.extend(r)
                elif isinstance(r, Exception):
                    logger.warning(f"Исключение при получении данных HF: {r}")
    else:
        all_papers.extend(await fetch_hf_official_trending(None, limit=100))
        for i in range(days):
            target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            papers = await fetch_hf_daily_papers_for_date(None, target_date)
            all_papers.extend(papers)

    logger.info(f"HF Papers: получено {len(all_papers)} записей (до дедупликации)")
    return all_papers


async def fetch_hf_paper_details(arxiv_id: str, client: httpx.AsyncClient | None = None) -> dict:
    """
    GET /api/papers/{arxiv_id} для получения полного описания и связанных моделей/датасетов.
    """
    url = f"https://huggingface.co/api/papers/{arxiv_id}"
    if client is not None and httpx is not None:
        try:
            resp = await client.get(url, timeout=12.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"HF paper details не получены для {arxiv_id}: {e}")
    else:
        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, _sync_http_get_json, url, 12.0)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.debug(f"HF paper details urllib fallback не удался для {arxiv_id}: {e}")
    return {}



def _safe_parse_mcp_output(raw: str):
    """Парсинг JSON/Python-литерала из ответа тула MCP."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        return ast.literal_eval(raw)
    except Exception:
        return None


async def _call_mcp_tool(session: ClientSession | None, tool_name: str, arguments: dict) -> str:
    """
    Вызов тула PwC.
    Использует прямой HTTP JSON-RPC к gateway.pipeworx.io,
    так как он отвечает мгновенно (0.3-0.9 сек), в то время как SSE-стрим MCP-сессии
    зависает на 5-минутном таймауте Pipeworx.
    """
    global _PIPEWORX_BLOCKED
    if _PIPEWORX_BLOCKED:
        return ""

    # 1. Быстрый прямой JSON-RPC POST к шлюзу Pipeworx (0.3-1 сек)
    if config.PWC_MCP_URL:
        try:
            res = await _call_pipeworx_http(tool_name, arguments, timeout=6.0)
            if res:
                return res
        except Exception as e:
            logger.debug(f"Прямой HTTP к PwC не сработал: {e}")

    # 2. Fallback через сессию только если шлюз не заблокирован и session есть
    if session is not None and not _PIPEWORX_BLOCKED:
        try:
            response = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=3.0
            )
            if response and response.content:
                return "\n".join(
                    part.text for part in response.content if hasattr(part, "text") and part.text
                )
        except Exception as e:
            logger.debug(f"Вызов через MCP-сессию не удался для {tool_name}: {e}")

    return ""


async def _inspect_and_call_trending(session: ClientSession | None, days: int) -> list[dict]:
    """
    Проверяет inputSchema тула trending_papers и вызывает его с корректными параметрами.
    Работает как через сессию MCP, так и через прямой JSON-RPC.
    """
    trending_tool_name = config.PWC_TRENDING_TOOL
    call_args = {"days": days, "limit": 50}

    if session is not None:
        try:
            tools_response = await session.list_tools()
            tool_map = {t.name: t for t in tools_response.tools}

            if trending_tool_name not in tool_map:
                for name in tool_map:
                    if "trending" in name or "paper" in name:
                        trending_tool_name = name
                        break

                target_tool = tool_map[trending_tool_name]
                raw_schema = getattr(target_tool, "input_schema", None) or getattr(target_tool, "inputSchema", None) or {}
                schema_props = raw_schema.get("properties", {}) if isinstance(raw_schema, dict) else {}

                call_args = {}
                if "days" in schema_props:
                    call_args["days"] = days
                elif "window" in schema_props:
                    call_args["window"] = days
                elif "period" in schema_props:
                    call_args["period"] = "weekly" if days >= 7 else "daily"

                if "limit" in schema_props:
                    call_args["limit"] = 50
        except Exception as e:
            logger.debug(f"list_tools не сработал через MCP: {e}")

    raw_result = await _call_mcp_tool(session, trending_tool_name, call_args)
    parsed = _safe_parse_mcp_output(raw_result)

    raw_papers = []
    if isinstance(parsed, list):
        raw_papers = parsed
    elif isinstance(parsed, dict):
        for key in ("papers", "results", "items", "data"):
            if isinstance(parsed.get(key), list):
                raw_papers = parsed[key]
                break

    papers = []
    for item in raw_papers:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("arxiv_id") or item.get("id") or item.get("paper_id") or ""
        arxiv_id = normalize_arxiv_id(raw_id)
        if not arxiv_id and "url" in item:
            arxiv_id = normalize_arxiv_id(item["url"])

        if not arxiv_id:
            continue

        title = (item.get("title") or "").strip()
        abstract = (item.get("abstract") or item.get("summary") or "").strip()
        upvotes = int(item.get("upvotes") or item.get("stars") or item.get("favorites") or 0)
        # Канонический URL конкретной статьи: huggingface.co/papers/{arxiv_id}.
        # Ссылки paperswithcode.com/paper/{arxiv_id} сервер PwC редиректит на общий /papers/trending.
        url = f"https://huggingface.co/papers/{arxiv_id}"

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "upvotes": upvotes,
            "url": url,
            "source": "pwc",
            "period": "weekly" if days <= 7 else "monthly",
        })
    return papers


@asynccontextmanager
async def pwc_mcp_session():
    """
    Асинхронный контекстный менеджер для безопасного подключения к PwC.
    Использует прямой HTTP JSON-RPC к Pipeworx gateway (0.3 сек) без блокирующего
    SSE-стрима, что устраняет 5-минутные зависания и ошибки anyio TaskGroup.
    """
    yield None


async def fetch_pwc_trending(days: int = config.PAPERS_WINDOW_DAYS) -> list[dict]:
    """
    Получает трендовые статьи с PwC через быстрый прямой JSON-RPC (0.3-0.5 сек).
    """
    async with pwc_mcp_session() as session:
        return await _inspect_and_call_trending(session, days)



def _is_valid_topic_paper(slug: str, title: str, abstract: str) -> bool:
    """Проверяет релевантность статьи выбранной медицинской/биологической теме и отсекает стоп-слова."""
    text_check = f"{title} {abstract}".lower()
    if any(stop in text_check for stop in ("minecraft", "video game", "game play", "argon-", "argon ")):
        return False

    if slug == "healthcare":
        keywords = (
            "health", "medic", "clinic", "patient", "biomed", "doctor",
            "disease", "hospital", "pharma", "radiolog", "patholog", "ehr",
            "clinical", "biomedical", "drug", "genomic", "therapy"
        )
        return any(kw in text_check for kw in keywords)
    elif slug == "medical-imaging":
        keywords = (
            "imag", "mri", "ct", "x-ray", "radiolog", "ultrasound", "segmentation",
            "lesion", "tumor", "scan", "histopatholog", "vision", "biomed"
        )
        return any(kw in text_check for kw in keywords)
    elif slug == "biology":
        keywords = (
            "biolog", "protein", "dna", "rna", "genom", "molecular", "cell",
            "bioinformatic", "organism", "gene", "biomed", "evolution"
        )
        return any(kw in text_check for kw in keywords)
    return True


async def _fetch_hf_papers_by_query(query: str, limit: int = 50) -> list[dict]:
    """
    Быстрый поиск статей по тематике через Hugging Face Papers API.
    Поддерживает: healthcare, medical-imaging, biology.
    Работает мгновенно (0.2 сек) без суточных лимитов.
    """
    queries = [query]
    if query == "healthcare":
        queries.append("medical")
    elif query == "medical-imaging":
        queries = ["medical imaging", "radiology"]
    elif query == "biology":
        queries = ["biology", "bioinformatics"]

    raw_candidates = []
    seen = set()

    client = httpx.AsyncClient(headers={"User-Agent": "AIML-Radar-Agent/1.0"}) if httpx is not None else None
    try:
        for q in queries:
            url = f"https://huggingface.co/api/papers/search?q={urllib.parse.quote(q)}"
            data = None
            if client is not None:
                try:
                    resp = await client.get(url, timeout=10.0)
                    if resp.status_code == 200:
                        data = resp.json()
                except Exception as e:
                    logger.debug(f"HF search '{q}' failed: {e}")
            if data is None:
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(None, _sync_http_get_json, url, 10.0)

            if isinstance(data, list):
                for item in data:
                    paper = item.get("paper") if isinstance(item, dict) and "paper" in item else item
                    raw_id = paper.get("id") or paper.get("arxiv_id") or item.get("id") or ""
                    aid = normalize_arxiv_id(raw_id)
                    if not aid or aid in seen:
                        continue

                    title = (paper.get("title") or item.get("title") or "").strip()
                    abstract = (paper.get("summary") or paper.get("abstract") or item.get("summary") or "").strip()
                    upvotes = int(paper.get("upvotes") or item.get("upvotes") or 0)

                    # Семантическая валидация
                    if not _is_valid_topic_paper(query, title, abstract):
                        continue

                    seen.add(aid)
                    raw_candidates.append({
                        "arxiv_id": aid,
                        "title": title,
                        "abstract": abstract,
                        "upvotes": upvotes,
                        "url": f"https://huggingface.co/papers/{aid}",
                        "source": "pwc_topic",
                        "topic_tag": query,
                        "period": "weekly",
                    })
    finally:
        if client is not None:
            await client.aclose()

    # Сортируем статьи по числу upvotes, чтобы в топ попали самые влиятельные исследования
    raw_candidates.sort(key=lambda x: x.get("upvotes", 0), reverse=True)
    results = raw_candidates[:limit]

    logger.info(f"HF search fallback для темы '{query}': получено {len(results)} валидированных статей")
    return results


async def fetch_papers_by_topic(slug: str, session: ClientSession | None = None) -> list[dict]:
    """
    ТЗ 1.4: Тематические срезы (healthcare, medical-imaging, biology).
    Pipeworx PwC MCP принимает аргумент 'query', а результаты лежат в ключе 'results'.
    Если PwC возвращает 0 статей или лимит исчерпан (401), мгновенно подключается HF fallback.
    """
    topic_papers = []
    if not _PIPEWORX_BLOCKED:
        try:
            raw = await _call_mcp_tool(session, "search_papers", {"query": slug, "limit": 50})
            parsed = _safe_parse_mcp_output(raw)

            items = []
            if isinstance(parsed, list):
                items = parsed
            elif isinstance(parsed, dict):
                for k in ("results", "papers", "items", "data"):
                    if isinstance(parsed.get(k), list):
                        items = parsed[k]
                        break

            if not items:
                raw = await _call_mcp_tool(session, "search_papers", {"task": slug, "limit": 50})
                parsed = _safe_parse_mcp_output(raw)
                if isinstance(parsed, list):
                    items = parsed
                elif isinstance(parsed, dict):
                    for k in ("results", "papers", "items", "data"):
                        if isinstance(parsed.get(k), list):
                            items = parsed[k]
                            break

            for item in items:
                if not isinstance(item, dict):
                    continue
                raw_id = item.get("arxiv_id") or item.get("id") or item.get("paper_id") or ""
                arxiv_id = normalize_arxiv_id(raw_id)
                if not arxiv_id and "url" in item:
                    arxiv_id = normalize_arxiv_id(item["url"])
                if not arxiv_id:
                    continue

                title = (item.get("title") or "").strip()
                abstract = (item.get("abstract") or item.get("summary") or "").strip()
                upvotes = int(item.get("upvotes") or item.get("stars") or 0)
                # Канонический прямой URL конкретной статьи в HF Papers
                url = f"https://huggingface.co/papers/{arxiv_id}"

                if not _is_valid_topic_paper(slug, title, abstract):
                    continue

                topic_papers.append({
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "abstract": abstract,
                    "upvotes": upvotes,
                    "url": url,
                    "source": "pwc_topic",
                    "topic_tag": slug,
                    "period": "weekly",
                })
        except Exception as e:
            logger.warning(f"Ошибка при поиске тематического среза '{slug}' через PwC: {e}")

    if topic_papers:
        logger.info(f"Тематика PwC '{slug}': получено {len(topic_papers)} статей")
        return topic_papers

    # Мгновенный fallback на HF Papers (0.2 сек)
    logger.info(f"PwC вернул 0 статей по теме '{slug}'. Используем мгновенный fallback HF Papers...")
    return await _fetch_hf_papers_by_query(slug, limit=50)



def merge_papers(*lists_of_papers) -> list[dict]:
    """
    ТЗ 1.2: Склейка по arxiv_id, upvotes = max(upvotes).
    Корректно сохраняет и объединяет источники (hf, pwc, pwc_topic) даже при вложенных вызовах merge_papers.
    """
    merged: dict[str, dict] = {}

    for paper_list in lists_of_papers:
        for p in paper_list:
            if not isinstance(p, dict):
                continue
            arxiv_id = normalize_arxiv_id(p.get("arxiv_id") or p.get("id") or "")
            if not arxiv_id:
                continue

            upvotes = int(p.get("upvotes") or 0)
            title = p.get("title", "").strip()
            abstract = p.get("abstract", "").strip()
            topic_tag = p.get("topic_tag", "")

            # Извлекаем список источников: поддерживаем и одиночный source, и уже сформированный список sources
            raw_sources = p.get("sources")
            if isinstance(raw_sources, list) and raw_sources:
                incoming_sources = [s for s in raw_sources if s and s != "unknown"]
            elif p.get("source") and p.get("source") != "unknown":
                incoming_sources = [p["source"]]
            else:
                incoming_sources = ["unknown"]

            # Первоисточник статьи: прямой URL конкретной статьи в Hugging Face Papers.
            # PwC переехал в HF, а ссылки paperswithcode.com/paper/... редиректят на общий /papers/trending.
            raw_url = p.get("url") or ""
            if not raw_url or "arxiv.org" in raw_url or "paperswithcode.com/paper/" in raw_url:
                url = f"https://huggingface.co/papers/{arxiv_id}"
            else:
                url = raw_url

            period = p.get("period", "")
            has_code = p.get("has_code", 0)

            if arxiv_id not in merged:
                merged[arxiv_id] = {
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "abstract": abstract,
                    "upvotes": upvotes,
                    "url": url,
                    "sources": list(incoming_sources),
                    "topic_tag": topic_tag,
                    "period": period,
                    "has_code": has_code,
                    "related_links": list(p.get("related_links") or []),
                    "related_materials": list(p.get("related_materials") or []),
                }
            else:
                existing = merged[arxiv_id]
                existing["upvotes"] = max(existing["upvotes"], upvotes)
                if not existing["title"] and title:
                    existing["title"] = title
                if not existing["abstract"] and abstract:
                    existing["abstract"] = abstract
                if not existing["url"] or "arxiv.org" in existing["url"] or "paperswithcode.com/paper/" in existing["url"]:
                    existing["url"] = f"https://huggingface.co/papers/{arxiv_id}"
                elif url and "arxiv.org" not in url and "paperswithcode.com/paper/" not in url:
                    existing["url"] = url
                for s in incoming_sources:
                    if s not in existing["sources"] and s != "unknown":
                        existing["sources"].append(s)
                if "unknown" in existing["sources"] and len(existing["sources"]) > 1:
                    existing["sources"].remove("unknown")
                if not existing["topic_tag"] and topic_tag:
                    existing["topic_tag"] = topic_tag
                if p.get("period") == "weekly" or not existing.get("period"):
                    existing["period"] = p.get("period", "")
                if p.get("has_code"):
                    existing["has_code"] = 1
                if not existing.get("related_links") and p.get("related_links"):
                    existing["related_links"] = list(p["related_links"])
                if not existing.get("related_materials") and p.get("related_materials"):
                    existing["related_materials"] = list(p["related_materials"])

    return list(merged.values())


def _rank_balanced(
    all_candidates: list[dict],
    limit_hf: int = 30,
    limit_pwc: int = 30,
) -> list[dict]:
    # 1. Кандидаты за неделю и за месяц
    weekly_pool = [p for p in all_candidates if p.get("period") == "weekly"]
    monthly_pool = [p for p in all_candidates if p.get("period") != "weekly"]

    def _balance_subpool(pool: list[dict], period_tag: str) -> list[dict]:
        hf_list = sorted([p for p in pool if "hf" in p.get("sources", [])], key=lambda x: x.get("upvotes", 0), reverse=True)[:limit_hf]
        pwc_list = sorted([p for p in pool if any("pwc" in s for s in p.get("sources", []))], key=lambda x: x.get("upvotes", 0), reverse=True)[:limit_pwc]
        
        seen_local = set()
        out = []
        for p in hf_list + pwc_list:
            aid = p.get("arxiv_id")
            if aid and aid not in seen_local:
                seen_local.add(aid)
                item = dict(p)
                item["period"] = period_tag
                out.append(item)
        return out

    # Недельный срез (до 30 HF + до 30 PwC)
    weekly_selected = _balance_subpool(weekly_pool, "weekly")
    weekly_ids = {p["arxiv_id"] for p in weekly_selected}

    # Месячный срез (до 30 HF + до 30 PwC из месячного пула)
    monthly_selected = _balance_subpool(monthly_pool + weekly_pool, "monthly")

    # Тематические срезы (healthcare, medical-imaging, biology — до 10 лучших статей на каждую тему)
    topic_pool = []
    for slug in ("healthcare", "medical-imaging", "biology"):
        sub_list = sorted(
            [p for p in all_candidates if p.get("topic_tag") == slug],
            key=lambda x: x.get("upvotes", 0),
            reverse=True
        )[:10]
        topic_pool.extend(sub_list)

    # Склейка итогового пула: если статья вошла в недельный топ, фиксируем period='weekly'
    final_dict = {}
    for p in weekly_selected:
        final_dict[p["arxiv_id"]] = p

    for p in monthly_selected:
        aid = p["arxiv_id"]
        if aid not in final_dict:
            final_dict[aid] = p

    for p in topic_pool:
        aid = p["arxiv_id"]
        if aid not in final_dict:
            final_dict[aid] = p
        else:
            final_dict[aid]["topic_tag"] = p["topic_tag"]

    logger.info(
        f"Балансировка статей (неделя/месяц/топики): "
        f"weekly={len(weekly_selected)}, monthly={len(monthly_selected)}, topics={len(topic_pool)}. "
        f"Итого отобрано уникальных: {len(final_dict)}"
    )
    return list(final_dict.values())


async def _fill_missing_abstracts(papers: list[dict], session: ClientSession | None = None) -> list[dict]:
    """
    ТЗ 1.2: Точечное докачивание абстрактов для топ-N кандидатов (параллельно через Semaphore).
    """
    client = httpx.AsyncClient(headers={"User-Agent": "AIML-Radar-Agent/1.0"}) if httpx is not None else None
    sem = asyncio.Semaphore(10)

    async def _fill_one(p: dict):
        if p.get("abstract") and len(p["abstract"].strip()) >= 50:
            return

        async with sem:
            arxiv_id = p["arxiv_id"]
            details = await fetch_hf_paper_details(arxiv_id, client=client)
            if details and isinstance(details, dict):
                candidate_abstract = details.get("summary") or details.get("abstract") or details.get("ai_summary") or ""
                if candidate_abstract and len(candidate_abstract.strip()) >= 50:
                    p["abstract"] = candidate_abstract.strip()
                    if not p["title"] and details.get("title"):
                        p["title"] = details.get("title").strip()
                    return

            if not p.get("abstract"):
                p["abstract"] = p.get("title") or f"Статья arXiv:{arxiv_id}"

    try:
        await asyncio.gather(*[_fill_one(p) for p in papers], return_exceptions=True)
    finally:
        if client is not None:
            await client.aclose()

    return papers


async def _enrich_related_links(papers: list[dict], session: ClientSession | None = None) -> list[dict]:
    """
    ТЗ 1.3: Связанные датасеты/модели из карточки статьи (параллельно через Semaphore).
    Использует быстрый HF Paper details API (100 мс, без лимитов в 50 req/day).
    -> article.related_links = JSON[{type, url, name}]
    -> article.related_materials = [{type, name, url}] для последующего upsert в articles
    """
    client = httpx.AsyncClient(headers={"User-Agent": "AIML-Radar-Agent/1.0"}) if httpx is not None else None
    sem = asyncio.Semaphore(10)

    async def _enrich_one(p: dict):
        async with sem:
            arxiv_id = p["arxiv_id"]
            related_links = list(p.get("related_links") or [])
            related_materials = list(p.get("related_materials") or [])

            # Обогащение из HF Paper details (быстро, надежно)
            details = await fetch_hf_paper_details(arxiv_id, client=client)
            if isinstance(details, dict):
                gh = details.get("githubRepo") or details.get("github_repo")
                if gh and not any(l.get("type") == "github" for l in related_links):
                    gh_str = str(gh).rstrip("/")
                    related_links.append({"type": "github", "url": gh_str, "name": gh_str.split("/")[-1]})

                models_raw = details.get("linkedModels") or details.get("models") or []
                for m in models_raw:
                    m_name = m.get("id", "") if isinstance(m, dict) else str(m)
                    if m_name and not any(mat.get("name") == m_name for mat in related_materials):
                        m_url = f"https://huggingface.co/{m_name}"
                        related_links.append({"type": "модель", "url": m_url, "name": m_name})
                        related_materials.append({"type": "модель", "name": m_name, "url": m_url})

                datasets_raw = details.get("linkedDatasets") or details.get("datasets") or []
                for d in datasets_raw:
                    d_name = d.get("id", "") if isinstance(d, dict) else str(d)
                    if d_name and not any(mat.get("name") == d_name for mat in related_materials):
                        d_url = f"https://huggingface.co/datasets/{d_name}"
                        related_links.append({"type": "датасет", "url": d_url, "name": d_name})
                        related_materials.append({"type": "датасет", "name": d_name, "url": d_url})

                spaces_raw = details.get("linkedSpaces") or details.get("spaces") or []
                for sp in spaces_raw:
                    sp_name = sp.get("id", "") if isinstance(sp, dict) else str(sp)
                    if sp_name and not any(l.get("url") == f"https://huggingface.co/spaces/{sp_name}" for l in related_links):
                        related_links.append({"type": "space", "url": f"https://huggingface.co/spaces/{sp_name}", "name": sp_name})

                proj = details.get("projectPage")
                if proj and not any(l.get("url") == proj for l in related_links):
                    related_links.append({"type": "project", "url": str(proj), "name": "Project Page"})

            # Резервный поиск GitHub репозитория в тексте абстракта
            if not any(l.get("type") in ("github", "code") for l in related_links):
                abstract_text = p.get("abstract") or p.get("text") or ""
                gh_matches = re.findall(r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", abstract_text)
                if gh_matches:
                    clean_repo = gh_matches[0].rstrip(".git").rstrip(")")
                    gh_url = f"https://github.com/{clean_repo}"
                    related_links.append({"type": "github", "url": gh_url, "name": clean_repo.split("/")[-1]})

            has_code = 1 if any(l.get("type") in ("github", "code") for l in related_links) else 0
            # Сохраняем ссылку на arXiv как дополнительный материал, если пользователь захочет скачать PDF
            if aid and not any(l.get("type") == "arxiv" or "arxiv.org" in (l.get("url") or "") for l in related_links):
                related_links.append({"type": "arxiv", "url": f"https://arxiv.org/abs/{aid}", "name": f"arXiv: {aid}"})

            p["has_code"] = has_code
            p["related_links"] = related_links
            p["related_materials"] = related_materials

    try:
        await asyncio.gather(*[_enrich_one(p) for p in papers], return_exceptions=True)
    finally:
        if client is not None:
            await client.aclose()

    return papers



async def fetch_papers_pipeline(
    days: int = config.PAPERS_WINDOW_DAYS,
    limit_hf: int = getattr(config, "PAPERS_LIMIT_HF", 30),
    limit_pwc: int = getattr(config, "PAPERS_LIMIT_PWC", 30),
    topics: list[str] | None = None,
) -> list[dict]:
    """
    Полный пайплайн сбора:
    1. HF Papers за неделю и месяц (30 дней)
    2. PwC trending за неделю (7 дней) и месяц (30 дней) через MCP
    3. Тематические срезы (healthcare - https://paperswithcode.com/task/healthcare, medical-imaging, biology)
    4. merge_papers() по arxiv_id (upvotes = max, объединение источников)
    5. _rank_balanced(): 30 лучших HF + 30 лучших PwC
    6. _fill_missing_abstracts()
    7. _enrich_related_links()
    """
    # 1. Сбор HF Papers (30 дней охватывает и неделю, и месяц)
    hf_days = max(days, 30)
    hf_papers = await fetch_hf_trending(days=hf_days)

    # 2. Сбор PwC trending за неделю (7 дней) и за месяц (30 дней)
    pwc_papers: list[dict] = []
    topic_lists: list[list[dict]] = []

    async with pwc_mcp_session() as session:
        # Недельные тренды PwC
        try:
            pwc_weekly = await _inspect_and_call_trending(session, days=7)
            logger.info(f"PwC (тренды за неделю): получено {len(pwc_weekly)} статей")
        except Exception as e:
            logger.warning(f"Ошибка получения недельных трендов PwC: {e}")
            pwc_weekly = []

        # Месячные тренды PwC
        try:
            pwc_monthly = await _inspect_and_call_trending(session, days=30)
            logger.info(f"PwC (тренды за месяц): получено {len(pwc_monthly)} статей")
        except Exception as e:
            logger.warning(f"Ошибка получения месячных трендов PwC: {e}")
            pwc_monthly = []

        pwc_papers = merge_papers(pwc_weekly, pwc_monthly)
        logger.info(f"PwC (тренды уникальных неделя+месяц): получено {len(pwc_papers)} статей")

        # Тематический срез healthcare и другие топики
        active_topics = list(topics or config.PWC_TOPIC_SLUGS or ["healthcare", "medical-imaging", "biology"])

        for slug in active_topics:
            try:
                t_papers = await fetch_papers_by_topic(slug, session=session)
                if t_papers:
                    topic_lists.append(t_papers)
                    logger.info(f"Тематика PwC '{slug}': получено {len(t_papers)} статей")
            except Exception as e:
                logger.debug(f"Ошибка получения темы '{slug}' из PwC: {e}")

        # Склейка всех потоков
        all_candidates = merge_papers(hf_papers, pwc_papers, *topic_lists)
        logger.info(f"Всего уникальных статей после объединения источников: {len(all_candidates)}")

        # Балансированный отбор: 30 лучших HF + 30 лучших PwC (включая healthcare)
        ranked = _rank_balanced(all_candidates, limit_hf=limit_hf, limit_pwc=limit_pwc)
        logger.info(f"Отобрано в итоговый пул: {len(ranked)} статей")

        # Дозаполнение абстрактов и связанных ссылок для отобранного топа
        filled = await _fill_missing_abstracts(ranked, session=session)
        enriched = await _enrich_related_links(filled, session=session)

    # Формируем объекты по контракту системы
    articles_payload = []
    for item in enriched:
        title = item["title"] or f"Paper {item['arxiv_id']}"
        has_hf = "hf" in item.get("sources", [])
        has_pwc = any("pwc" in s for s in item.get("sources", []))

        if has_hf and has_pwc:
            source_prefix = "HF/PwC"
        elif has_hf:
            source_prefix = "HF"
        else:
            source_prefix = "PwC"

        articles_payload.append({
            "title": f"[{source_prefix}] {title}",
            "text": item["abstract"],
            "source_url": item["url"],
            "arxiv_id": item["arxiv_id"],
            "upvotes": item["upvotes"],
            "stars": item["upvotes"],
            "topic_tag": item.get("topic_tag", ""),
            "related_links": item.get("related_links", []),
            "related_materials": item.get("related_materials", []),
            "has_code": item.get("has_code", 0),
            "period": item.get("period", "weekly"),
            "source_type": "статья",
        })

    return articles_payload


def stream_papers_articles(
    days: int = config.PAPERS_WINDOW_DAYS,
    limit_hf: int = getattr(config, "PAPERS_LIMIT_HF", 30),
    limit_pwc: int = getattr(config, "PAPERS_LIMIT_PWC", 30),
):
    """
    Синхронный генератор под контракт stream_all_new_articles() в main.py.
    Собирает 30 лучших HF и 30 лучших PwC за неделю и за месяц, включая healthcare.
    """
    articles = asyncio.run(fetch_papers_pipeline(days=days, limit_hf=limit_hf, limit_pwc=limit_pwc))
    for article in articles:
        yield article


def ingest_papers(
    days: int = config.PAPERS_WINDOW_DAYS,
    limit_hf: int = getattr(config, "PAPERS_LIMIT_HF", 30),
    limit_pwc: int = getattr(config, "PAPERS_LIMIT_PWC", 30),
):
    """
    Автономный сбор и сохранение только статей в базу данных (с дедупликацией и LLM-анализом).
    Не запускает тяжелые скраперы арены (Playwright), GitHub и Kaggle.
    Позволяет обновить раздел 'Papers (Статьи)' за 1-2 минуты.
    """
    from database import (
        init_db,
        get_all_vectors,
        save_vector,
        save_article,
        upsert_related_material,
        get_existing_article_urls,
        is_vector_duplicate_db,
    )
    from dedup import text_to_vector, is_duplicate, flush_embeddings_cache
    from agent_manager import analyze_article, AnalysisError

    init_db()
    logger.info("=== Запуск автономного обновления раздела 'Papers (Статьи)' ===")
    memory_vectors: list[list[float]] = list(get_all_vectors())
    existing_urls: set[str] = get_existing_article_urls()
    logger.info(f"Загружено векторов из БД: {len(memory_vectors)}, известных URL: {len(existing_urls)}")

    processed, skipped, failed = 0, 0, 0
    for article in stream_papers_articles(days=days, limit_hf=limit_hf, limit_pwc=limit_pwc):
        title = article["title"]
        text = article["text"]
        source_url = str(article.get("source_url") or "").strip()
        clean_url = source_url.rstrip("/")

        # Мгновенная проверка на уже имеющуюся статью
        if clean_url and (clean_url in existing_urls or f"{clean_url}/" in existing_urls):
            logger.info(f"[EXISTS] Статья уже в базе: {title}")
            skipped += 1
            continue

        new_vector = text_to_vector(text)

        if is_vector_duplicate_db(new_vector) or is_duplicate(new_vector, memory_vectors):
            logger.info(f"[SKIP] Дубликат статьи: {title}")
            skipped += 1
            continue

        try:
            analysis = analyze_article(title, text)
        except AnalysisError as e:
            logger.error(f"[FAIL] Ошибка анализа {title}: {e}")
            failed += 1
            continue

        save_vector(new_vector)
        memory_vectors.append(new_vector)

        payload = {
            "title": title,
            "summary": analysis.summary,
            "source_url": source_url,
            "tags": analysis.tags,
            "directions": article.get("directions", []),
            "task_types": article.get("task_types", []),
            "stars": int(article.get("stars") or article.get("upvotes") or 0),
            "upvotes": int(article.get("upvotes") or article.get("stars") or 0),
            "source_type": "статья",
            "language": article.get("language", ""),
            "topic_tag": article.get("topic_tag", ""),
            "related_links": article.get("related_links", []),
            "source_article_url": article.get("source_article_url", ""),
            "period": article.get("period", ""),
            "has_code": article.get("has_code", 0),
        }

        save_article(payload)
        processed += 1

        for material in article.get("related_materials", []):
            try:
                upsert_related_material(material, source_article_url=source_url)
            except Exception as upsert_err:
                logger.warning(f"Не удалось сохранить связанный материал {material}: {upsert_err}")

        memory_vectors.append(new_vector)
        existing_urls.add(clean_url)
        existing_urls.add(f"{clean_url}/")

    flush_embeddings_cache()
    logger.info(f"=== Готово! Обработано новых статей: {processed}, дублей: {skipped}, ошибок: {failed} ===")
    return {"processed": processed, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if "--save" in sys.argv or "--ingest" in sys.argv or "--run" in sys.argv:
        print("ЗАПУСК АВТОНОМНОГО СБОРА И СОХРАНЕНИЯ СТАТЕЙ В БД...")
        res = ingest_papers()
        print(f"\nРезультат: {res}")
    else:
        print("ТЕСТОВЫЙ ЗАПУСК: HF Papers + PwC Trending (mcp_fetcher_papers.py)")
        print("(Для сохранения в БД запустите: python mcp_fetcher_papers.py --save)\n")
        try:
            results = asyncio.run(fetch_papers_pipeline(days=7, limit_hf=5, limit_pwc=5))
            print(f"\nМодуль отработал успешно. Получено статей: {len(results)}")
            for i, res in enumerate(results, 1):
                print(f"\n--- {i}. {res['title']} (Upvotes: {res.get('upvotes')}) ---")
                print(f"URL: {res['source_url']}")
                print(f"Topic: {res.get('topic_tag')}")
                print(f"Related links: {len(res.get('related_links', []))}")
                print(f"Abstract snippet: {res['text'][:150]}...")
        except Exception as e:
            print(f"\nОшибка при выполнении: {e}")
