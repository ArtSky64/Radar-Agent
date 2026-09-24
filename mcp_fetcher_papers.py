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


def _sync_http_post_json(url: str, payload: dict, timeout: float = 15.0):
    """Fallback POST-запрос через urllib (JSON-RPC 2.0 к Pipeworx gateway)."""
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
    except Exception as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate verify failed" in str(e):
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=_make_ssl_context(unverified=True)) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
            except Exception as e2:
                logger.debug(f"urllib POST unverified retry failed for {url}: {e2}")
        logger.debug(f"urllib POST failed for {url}: {e}")
    return None


async def _call_pipeworx_http(tool_name: str, arguments: dict, timeout: float = 15.0) -> str:
    """Прямой вызов инструмента через JSON-RPC 2.0 к Pipeworx gateway (fallback при сбоях MCP-библиотеки)."""
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
        except Exception as e:
            logger.debug(f"httpx JSON-RPC failed for {tool_name}: {e}")

    if data is None:
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


# ==========================================
# 1. HUGGING FACE PAPERS (REST API)
# ==========================================

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

            papers.append({
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": summary,
                "upvotes": upvotes,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "source": "hf",
                "published_at": paper_info.get("publishedAt") or item.get("publishedAt") or date_str,
            })
        return papers
    except Exception as e:
        logger.warning(f"Ошибка при запросе HF Papers за {date_str}: {e}")
        return []


async def fetch_hf_trending(days: int = config.PAPERS_WINDOW_DAYS) -> list[dict]:
    """
    Недельный тренд = агрегация N вызовов daily_papers по дням (PAPERS_WINDOW_DAYS).
    """
    logger.info(f"Сбор HF Papers за последние {days} дней...")
    all_papers: list[dict] = []
    today = datetime.now(timezone.utc).date()

    if httpx is not None:
        async with httpx.AsyncClient(headers={"User-Agent": "AIML-Radar-Agent/1.0"}) as client:
            tasks = []
            for i in range(days):
                target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                tasks.append(fetch_hf_daily_papers_for_date(client, target_date))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    all_papers.extend(r)
                elif isinstance(r, Exception):
                    logger.warning(f"Исключение при получении дня HF: {r}")
    else:
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
        data = _sync_http_get_json(url, timeout=12.0)
        if isinstance(data, dict):
            return data
    return {}


# ==========================================
# 2. PAPERS WITH CODE (MCP STREAMABLE HTTP)
# ==========================================

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
    """Вызов тула с извлечением текста из ответа (через MCP-сессию или прямой JSON-RPC fallback)."""
    if session is not None:
        try:
            logger.debug(f"Вызов PwC MCP tool '{tool_name}' через активную сессию с аргументами {arguments}")
            response = await session.call_tool(tool_name, arguments=arguments)
            if response.content:
                return "\n".join(
                    part.text for part in response.content if hasattr(part, "text") and part.text
                )
        except Exception as e:
            logger.warning(f"Ошибка вызова MCP tool '{tool_name}' через сессию: {e}. Переключение на прямой JSON-RPC...")

    # Fallback на прямой HTTP JSON-RPC к Pipeworx gateway
    return await _call_pipeworx_http(tool_name, arguments)


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

            if trending_tool_name in tool_map:
                target_tool = tool_map[trending_tool_name]
                schema_props = target_tool.inputSchema.get("properties", {}) if hasattr(target_tool, "inputSchema") and target_tool.inputSchema else {}

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
        url = item.get("url") or f"https://arxiv.org/abs/{arxiv_id}"

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "upvotes": upvotes,
            "url": url,
            "source": "pwc",
        })
    return papers


@asynccontextmanager
async def pwc_mcp_session():
    """
    Асинхронный контекстный менеджер для безопасного подключения к PwC MCP.
    Гарантирует корректный вход и выход из AnyIO cancel scope в рамках одного таска.
    Поддерживает как 2-tuple (read, write), так и 3-tuple (read, write, get_session_id)
    в зависимости от версии библиотеки mcp.
    """
    if not config.PWC_MCP_URL:
        yield None
        return

    cm = None
    if streamable_http_client is not None:
        try:
            cm = streamable_http_client(config.PWC_MCP_URL)
        except Exception as e:
            logger.debug(f"Не удалось инициализировать streamable_http_client: {e}")
    elif sse_client is not None:
        try:
            cm = sse_client(config.PWC_MCP_URL)
        except Exception as e:
            logger.debug(f"Не удалось инициализировать sse_client: {e}")

    if cm is None:
        yield None
        return

    logger.info(f"Подключение к PwC MCP gateway: {config.PWC_MCP_URL}...")
    try:
        async with cm as streams:
            # streamable_http_client в mcp >= 1.2 возвращает (read, write, get_session_id)
            if isinstance(streams, (list, tuple)):
                read_stream, write_stream = streams[0], streams[1]
            else:
                read_stream = getattr(streams, "read", streams)
                write_stream = getattr(streams, "write", streams)

            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                logger.info("Сессия PwC MCP успешно инициализирована.")
                yield session
    except Exception as e:
        logger.warning(
            f"Не удалось подключиться к PwC MCP шлюзу ({config.PWC_MCP_URL}): {e}. "
            "Пайплайн продолжит работу на HF Papers."
        )
        yield None


async def fetch_pwc_trending(days: int = config.PAPERS_WINDOW_DAYS) -> list[dict]:
    """
    Получает трендовые статьи с PwC через MCP шлюз (или прямой JSON-RPC fallback).
    """
    async with pwc_mcp_session() as session:
        return await _inspect_and_call_trending(session, days)


# ==========================================
# 3. ТЕМАТИЧЕСКИЕ СРЕЗЫ (ТЗ 1.4)
# ==========================================

async def fetch_papers_by_topic(slug: str, session: ClientSession | None = None) -> list[dict]:
    """
    ТЗ 1.4: Тематические срезы (healthcare, medical-imaging, biology).
    Приоритет: search_papers(task=slug) через MCP или прямой JSON-RPC к шлюзу.
    """
    try:
        raw = await _call_mcp_tool(session, "search_papers", {"task": slug, "limit": 20})
        parsed = _safe_parse_mcp_output(raw)
        items = parsed if isinstance(parsed, list) else (parsed.get("papers", []) if isinstance(parsed, dict) else [])

        topic_papers = []
        for item in items:
            raw_id = item.get("arxiv_id") or item.get("id") or ""
            arxiv_id = normalize_arxiv_id(raw_id)
            if not arxiv_id:
                continue
            topic_papers.append({
                "arxiv_id": arxiv_id,
                "title": (item.get("title") or "").strip(),
                "abstract": (item.get("abstract") or item.get("summary") or "").strip(),
                "upvotes": int(item.get("upvotes") or item.get("stars") or 0),
                "url": item.get("url") or f"https://arxiv.org/abs/{arxiv_id}",
                "source": "pwc_topic",
                "topic_tag": slug,
            })
        return topic_papers
    except Exception as e:
        logger.debug(f"Ошибка при поиске тематического среза '{slug}': {e}")
        return []


# ==========================================
# 4. СЛИЯНИЕ, РАНЖИРОВАНИЕ, ДООБОГАЩЕНИЕ
# ==========================================

def merge_papers(*lists_of_papers) -> list[dict]:
    """
    ТЗ 1.2: Склейка по arxiv_id, upvotes = max(upvotes).
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
            url = p.get("url") or f"https://arxiv.org/abs/{arxiv_id}"
            source = p.get("source", "unknown")
            topic_tag = p.get("topic_tag", "")

            if arxiv_id not in merged:
                merged[arxiv_id] = {
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "abstract": abstract,
                    "upvotes": upvotes,
                    "url": url,
                    "sources": [source],
                    "topic_tag": topic_tag,
                    "related_links": [],
                    "related_materials": [],
                }
            else:
                existing = merged[arxiv_id]
                existing["upvotes"] = max(existing["upvotes"], upvotes)
                if not existing["title"] and title:
                    existing["title"] = title
                if not existing["abstract"] and abstract:
                    existing["abstract"] = abstract
                if source not in existing["sources"]:
                    existing["sources"].append(source)
                if not existing["topic_tag"] and topic_tag:
                    existing["topic_tag"] = topic_tag

    return list(merged.values())


def _rank(papers: list[dict], limit: int = config.PAPERS_LIMIT) -> list[dict]:
    """
    Ранжирование по upvotes (чистый детерминированный отбор топ-N сообщества, без LLM).
    """
    return sorted(papers, key=lambda x: x.get("upvotes", 0), reverse=True)[:limit]


async def _fill_missing_abstracts(papers: list[dict], session: ClientSession | None = None) -> list[dict]:
    """
    ТЗ 1.2: Точечное докачивание абстрактов для топ-N, не для всей недели.
    """
    client = httpx.AsyncClient(headers={"User-Agent": "AIML-Radar-Agent/1.0"}) if httpx is not None else None
    try:
        for p in papers:
            if p.get("abstract") and len(p["abstract"].strip()) >= 50:
                continue

            arxiv_id = p["arxiv_id"]
            # 1. Пробуем HF Paper details
            details = await fetch_hf_paper_details(arxiv_id, client=client)
            if details and isinstance(details, dict):
                candidate_abstract = details.get("summary") or details.get("abstract") or ""
                if candidate_abstract and len(candidate_abstract.strip()) >= 50:
                    p["abstract"] = candidate_abstract.strip()
                    if not p["title"] and details.get("title"):
                        p["title"] = details.get("title").strip()
                    continue

            # 2. Если указан detail tool, запрашиваем через MCP или прямой JSON-RPC
            if config.PWC_DETAIL_TOOL:
                try:
                    raw_detail = await _call_mcp_tool(session, config.PWC_DETAIL_TOOL, {"arxiv_id": arxiv_id})
                    parsed_d = _safe_parse_mcp_output(raw_detail)
                    if isinstance(parsed_d, dict):
                        cand_abs = parsed_d.get("abstract") or parsed_d.get("summary") or ""
                        if cand_abs:
                            p["abstract"] = cand_abs.strip()
                            continue
                except Exception as e:
                    logger.debug(f"PwC detail tool error для {arxiv_id}: {e}")

            # 3. Fallback: если абстракт всё ещё пуст, используем заголовок в качестве описания
            if not p.get("abstract"):
                p["abstract"] = p.get("title") or f"Статья arXiv:{arxiv_id}"
    finally:
        if client is not None:
            await client.aclose()

    return papers


async def _enrich_related_links(papers: list[dict], session: ClientSession | None = None) -> list[dict]:
    """
    ТЗ 1.3: Связанные датасеты/модели из карточки статьи.
    get_repositories(arxiv_id) -> {github_repo, hf_models[], hf_datasets[], spaces[]}
    -> article.related_links = JSON[{type, url, name}]
    -> article.related_materials = [{type, name, url}] для последующего upsert в articles
    """
    client = httpx.AsyncClient(headers={"User-Agent": "AIML-Radar-Agent/1.0"}) if httpx is not None else None
    try:
        for p in papers:
            arxiv_id = p["arxiv_id"]
            related_links = []
            related_materials = []

            # 1. Запрос get_repositories через PwC MCP или прямой JSON-RPC
            pwc_repo_data = None
            try:
                raw_repos = await _call_mcp_tool(session, "get_repositories", {"arxiv_id": arxiv_id})
                pwc_repo_data = _safe_parse_mcp_output(raw_repos)
            except Exception as e:
                logger.debug(f"get_repositories для {arxiv_id} не сработал: {e}")

            if isinstance(pwc_repo_data, dict):
                github_repo = pwc_repo_data.get("github_repo") or pwc_repo_data.get("url")
                if github_repo:
                    related_links.append({"type": "github", "url": github_repo, "name": github_repo.split("/")[-1]})

                for model in pwc_repo_data.get("hf_models", []):
                    model_name = model if isinstance(model, str) else model.get("name", "")
                    model_url = f"https://huggingface.co/{model_name}"
                    related_links.append({"type": "модель", "url": model_url, "name": model_name})
                    related_materials.append({"type": "модель", "name": model_name, "url": model_url})

                for ds in pwc_repo_data.get("hf_datasets", []):
                    ds_name = ds if isinstance(ds, str) else ds.get("name", "")
                    ds_url = f"https://huggingface.co/datasets/{ds_name}"
                    related_links.append({"type": "датасет", "url": ds_url, "name": ds_name})
                    related_materials.append({"type": "датасет", "name": ds_name, "url": ds_url})

                for sp in pwc_repo_data.get("spaces", []):
                    sp_name = sp if isinstance(sp, str) else sp.get("name", "")
                    related_links.append({"type": "space", "url": f"https://huggingface.co/spaces/{sp_name}", "name": sp_name})

            # 2. Обогащение из HF Paper details (если get_repositories не вернул модели/датасеты)
            if not related_materials:
                details = await fetch_hf_paper_details(arxiv_id, client=client)
                if isinstance(details, dict):
                    gh = details.get("githubRepo") or details.get("github_repo")
                    if gh and not any(l["type"] == "github" for l in related_links):
                        related_links.append({"type": "github", "url": gh, "name": str(gh).split("/")[-1]})

                    for m in details.get("models", []):
                        m_name = m if isinstance(m, str) else m.get("id", "")
                        if m_name:
                            m_url = f"https://huggingface.co/{m_name}"
                            related_links.append({"type": "модель", "url": m_url, "name": m_name})
                            related_materials.append({"type": "модель", "name": m_name, "url": m_url})

                    for d in details.get("datasets", []):
                        d_name = d if isinstance(d, str) else d.get("id", "")
                        if d_name:
                            d_url = f"https://huggingface.co/datasets/{d_name}"
                            related_links.append({"type": "датасет", "url": d_url, "name": d_name})
                            related_materials.append({"type": "датасет", "name": d_name, "url": d_url})

            p["related_links"] = related_links
            p["related_materials"] = related_materials
    finally:
        if client is not None:
            await client.aclose()

    return papers


# ==========================================
# 5. ГЛАВНЫЙ АСИНХРОННЫЙ ПАЙПЛАЙН И ГЕНЕРАТОР
# ==========================================

async def fetch_papers_pipeline(
    days: int = config.PAPERS_WINDOW_DAYS,
    limit: int = config.PAPERS_LIMIT,
    topics: list[str] | None = None,
) -> list[dict]:
    """
    Полный пайплайн сбора:
    1. HF Papers за неделю
    2. PwC trending через MCP
    3. Тематические срезы (1.4)
    4. merge_papers() по arxiv_id (upvotes = max)
    5. _rank() топ-N по голосам
    6. _fill_missing_abstracts()
    7. _enrich_related_links()
    """
    # 1. Сбор HF Papers (REST API) — полностью изолирован
    hf_papers = await fetch_hf_trending(days=days)

    # 2. Сбор PwC trending и тематических срезов в изолированном контексте
    pwc_papers: list[dict] = []
    topic_lists: list[list[dict]] = []

    async with pwc_mcp_session() as session:
        try:
            pwc_papers = await _inspect_and_call_trending(session, days)
            logger.info(f"PwC: получено {len(pwc_papers)} трендовых статей")
        except Exception as e:
            logger.warning(f"Ошибка получения трендов PwC: {e}")

        active_topics = topics or config.PWC_TOPIC_SLUGS or []
        for slug in active_topics:
            try:
                t_papers = await fetch_papers_by_topic(slug, session=session)
                if t_papers:
                    topic_lists.append(t_papers)
            except Exception as e:
                logger.debug(f"Ошибка получения темы '{slug}' из PwC: {e}")

        # Склейка всех потоков
        all_candidates = merge_papers(hf_papers, pwc_papers, *topic_lists)
        logger.info(f"Всего уникальных статей после объединения источников: {len(all_candidates)}")

        # Детерминированный отбор топ-N
        ranked = _rank(all_candidates, limit=limit)
        logger.info(f"Отобрано в топ-{limit} по голосам: {len(ranked)} статей")

        # Дозаполнение абстрактов и связанных ссылок для отобранного топа
        filled = await _fill_missing_abstracts(ranked, session=session)
        enriched = await _enrich_related_links(filled, session=session)

    # Формируем объекты по контракту системы
    articles_payload = []
    for item in enriched:
        title = item["title"] or f"Paper {item['arxiv_id']}"
        source_prefix = "HF" if "hf" in item.get("sources", []) else "PwC"
        if "hf" in item.get("sources", []) and "pwc" in item.get("sources", []):
            source_prefix = "HF/PwC"

        articles_payload.append({
            "title": f"[{source_prefix}] {title}",
            "text": item["abstract"],
            "source_url": item["url"],
            "arxiv_id": item["arxiv_id"],
            "upvotes": item["upvotes"],
            "topic_tag": item.get("topic_tag", ""),
            "related_links": item.get("related_links", []),
            "related_materials": item.get("related_materials", []),
            "source_type": "статья",
        })

    return articles_payload


def stream_papers_articles(
    days: int = config.PAPERS_WINDOW_DAYS,
    limit: int = config.PAPERS_LIMIT,
):
    """
    Синхронный генератор под контракт stream_all_new_articles() в main.py.
    """
    articles = asyncio.run(fetch_papers_pipeline(days=days, limit=limit))
    for article in articles:
        yield article


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("ТЕСТОВЫЙ ЗАПУСК: HF Papers + PwC Trending (mcp_fetcher_papers.py)")
    try:
        results = asyncio.run(fetch_papers_pipeline(days=3, limit=5))
        print(f"\nМодуль отработал успешно. Получено статей: {len(results)}")
        for i, res in enumerate(results, 1):
            print(f"\n--- {i}. {res['title']} (Upvotes: {res.get('upvotes')}) ---")
            print(f"URL: {res['source_url']}")
            print(f"Topic: {res.get('topic_tag')}")
            print(f"Related links: {len(res.get('related_links', []))}")
            print(f"Abstract snippet: {res['text'][:150]}...")
    except Exception as e:
        print(f"\nОшибка при выполнении: {e}")
