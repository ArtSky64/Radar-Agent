import asyncio
import json
import logging
import os
import re
import ssl
import urllib.request
import urllib.parse

logger = logging.getLogger("hf_trending_fetcher")

# ==========================================
# ЧАСТЬ 1: MCP stdio (локальный сервер)
# ==========================================

_MODEL_LINE_RE = re.compile(
    r"^(?P<name>\S+)\s+\(Downloads:\s*(?P<downloads>[\d,]+),\s*Likes:\s*(?P<likes>[\d,]+)\)\s*$"
)
_TAGS_LINE_RE = re.compile(r"^Tags:\s*(?P<tags>.*)$")


def _parse_trending_text(raw_text: str) -> list[dict]:
    models = []
    current = None

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue

        model_match = _MODEL_LINE_RE.match(line)
        if model_match:
            if current:
                models.append(current)
            current = {
                "name": model_match.group("name"),
                "downloads": int(model_match.group("downloads").replace(",", "")),
                "likes": int(model_match.group("likes").replace(",", "")),
                "tags": [],
                "url": f"https://huggingface.co/{model_match.group('name')}",
            }
            continue

        tags_match = _TAGS_LINE_RE.match(line)
        if tags_match and current is not None:
            tags_str = tags_match.group("tags").strip()
            current["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]

    if current:
        models.append(current)

    return models


async def _call_mcp_stdio(limit: int) -> str:
    """Пробуем локальный MCP stdio-сервер (hf-trending-mcp через uv)."""
    from dotenv import load_dotenv
    load_dotenv()

    HF_TRENDING_MCP_PATH = os.getenv("HF_TRENDING_MCP_PATH", "")
    if not HF_TRENDING_MCP_PATH:
        raise RuntimeError("HF_TRENDING_MCP_PATH не задан в .env")

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command="uv",
        args=["--directory", HF_TRENDING_MCP_PATH, "run", "main.py"],
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.call_tool("get_trending_models", arguments={"limit": limit})
            if not response.content:
                return ""
            raw = "\n".join(
                part.text for part in response.content if hasattr(part, "text") and part.text
            )
            if response.isError:
                raise RuntimeError(f"MCP-тул get_trending_models вернул ошибку: {raw}")
            return raw


# ==========================================
# ЧАСТЬ 2: Прямой HTTP fallback через HF API
# ==========================================

def _http_get_json(url: str, timeout: int = 20) -> dict | list | None:
    """Простой GET-запрос с SSL-фолбэком."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; agent-pipeline/1.0)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    last_exc = None
    for verify_ssl in (True, False):
        try:
            ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            last_exc = e
            continue  # пробуем без верификации
    logger.debug(f"_http_get_json({url}) failed: {last_exc!r}")
    raise last_exc



def _fetch_hf_api_trending(limit: int) -> list[dict]:
    """
    Фолбэк: получаем трендовые модели напрямую через HF Hub REST API.
    https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=N
    """
    url = (
        "https://huggingface.co/api/models?"
        + urllib.parse.urlencode({
            "sort": "trendingScore",
            "direction": "-1",
            "limit": str(limit),
        })
    )
    try:
        data = _http_get_json(url)
    except Exception as e:
        logger.error(f"HF API /api/models trending запрос провалился: {e!r}")
        return []

    if not data or not isinstance(data, list):
        return []

    result = []
    for item in data:
        name = item.get("id") or item.get("modelId") or ""
        if not name:
            continue
        downloads = item.get("downloads") or 0
        likes = item.get("likes") or 0
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        result.append({
            "name": name,
            "downloads": int(downloads),
            "likes": int(likes),
            "tags": tags[:10],  # обрезаем длинные списки тегов
            "url": f"https://huggingface.co/{name}",
        })

    return result



# ==========================================
# ЧАСТЬ 3: Обогащение LLM-саммари
# ==========================================

def _enrich_with_summaries(models: list[dict]) -> list[dict]:
    """
    Дописывает каждой модели короткое LLM-саммари (по имени + тегам).
    Отдельная ошибка/рейт-лимит на одной модели не должна ронять всю
    витрину — если саммари не получилось, оставляем пустую строку.
    """
    from agent_manager import summarize_trending_model, AnalysisError

    for model in models:
        try:
            model["summary"] = summarize_trending_model(model["name"], model.get("tags", []))
        except AnalysisError as e:
            logger.warning(f"Саммари для модели '{model['name']}' не получено: {e}")
            model["summary"] = ""
    return models


# ==========================================
# ЧАСТЬ 4: Публичный entry-point
# ==========================================

def fetch_trending_models(limit: int = 30) -> list[dict]:
    """
    1. Пробуем локальный MCP stdio-сервер (если HF_TRENDING_MCP_PATH задан).
    2. При любой ошибке MCP — фолбэк через HF Hub REST API напрямую.
    3. Обогащаем оба результата LLM-саммари.
    """
    models = []
    mcp_ok = False

    try:
        raw_text = asyncio.run(_call_mcp_stdio(limit))
        if raw_text:
            models = _parse_trending_text(raw_text)
            mcp_ok = True
    except Exception as e:
        logger.warning(
            f"Не удалось получить трендовые модели HF через MCP: {e!r}. "
            "Переключаемся на прямой HF API."
        )

    if not mcp_ok or not models:
        logger.info("Сбор трендовых моделей HF через прямой REST API...")
        models = _fetch_hf_api_trending(limit)
        if not models:
            logger.info("Трендовые модели HF не получены (пусто или HF API недоступен).")
            return []
        logger.info(f"HF API вернул {len(models)} трендовых моделей.")

    return _enrich_with_summaries(models)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("ТЕСТОВЫЙ ЗАПУСК: трендовые модели HF")
    result = fetch_trending_models(5)
    print(f"Получено: {len(result)}\n")
    for m in result:
        print(m)