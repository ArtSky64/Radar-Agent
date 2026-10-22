import asyncio
import ast
import json
import os
import re
import time
import logging
from itertools import chain, zip_longest
from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import Agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

from agent_manager import get_model

load_dotenv()
logger = logging.getLogger("mcp_fetcher")

KAGGLE_BASE_URL = "https://www.kaggle.com"

CANDIDATES_PER_TYPE = 20
FINAL_MATERIALS_COUNT = 5
TRENDING_TOP_N = 6  # сколько самых популярных кандидатов отдаём на тематический отбор LLM


# --- Схема данных: LLM отвечает ТОЛЬКО за тематический отбор id ---

class SelectionResult(BaseModel):
    selected_ids: list[str] = Field(
        description=f"Список id (до {FINAL_MATERIALS_COUNT}) отобранных материалов"
    )


# selector_agent НЕ кэшируется как синглтон (см. тот же фикс в
# agent_manager.get_model()) — этот фетчер гоняется через свой отдельный
# asyncio.run(), и каждый такой вызов создаёт и закрывает свой event loop.
# Если закэшировать Agent (внутри которого httpx.AsyncClient) один раз,
# он останется привязан к ПЕРВОМУ loop'у — при следующем вызове (например,
# из main.py в рамках того же процесса) сработает "Event loop is closed",
# потому что тот loop уже закрыт. Пересоздаём агента при каждом вызове —
# небольшой оверхед, зато без риска использовать мёртвый event loop.
def _get_selector_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=SelectionResult,
        system_prompt=(
            "Ты — технический аналитик, который отбирает материалы для базы знаний по ИИ.\n\n"
            f"Тебе дадут JSON-список кандидатов (датасеты и модели с Kaggle), у каждого "
            "есть поля id, type, title, full_text. Список уже предварительно отсортирован "
            "в порядке выдачи Kaggle — порядок и свежесть учитывать не нужно. "
            f"Отбери до {FINAL_MATERIALS_COUNT} материалов, наиболее релевантных строго "
            "тематикам AI, ML, DL и DS (искусственный интеллект, машинное обучение, "
            "глубокое обучение, наука о данных). Материалы вне этих тематик игнорируй.\n\n"
            "Твоя ЕДИНСТВЕННАЯ задача — вернуть список id выбранных материалов. "
            "Текст менять, переводить или пересказывать не нужно — он останется "
            "в оригинальном виде без твоего участия.\n\n"
            f"Если подходящих материалов меньше {FINAL_MATERIALS_COUNT} — верни столько, "
            "сколько нашлось. Если ни один материал не подходит — верни пустой список. "
            "Не выдумывай факты, если данных недостаточно."
        )
    )


KAGGLE_SERVER_PARAMS = StdioServerParameters(
    command="uvx",
    args=["--with","mcp<2","kaggle-mcp-server"],
    env={
        "KAGGLE_USERNAME": os.getenv("KAGGLE_USERNAME", ""),
        "KAGGLE_KEY": os.getenv("KAGGLE_KEY", ""),
        "PATH": os.getenv("PATH", "")
    }
)


# --- Низкоуровневый вызов тула ---

async def _call_tool(session: ClientSession, tool_name: str, arguments: dict) -> str:
    logger.info(f"Вызов MCP-тула '{tool_name}' с аргументами {arguments}")
    response = await session.call_tool(tool_name, arguments=arguments)
    if not response.content:
        return ""
    return "\n".join(
        part.text for part in response.content if hasattr(part, "text") and part.text
    )


def _safe_json_loads(raw: str):
    """Пытается распарсить как JSON, а если не вышло — как Python-литерал
    (сервер иногда отдаёт repr словаря с одинарными кавычками вместо JSON)."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError, TypeError):
        return None


# --- Парсинг markdown-списков вида "- **Title** (`owner/slug`)" ---
# ВАЖНО: это осознанно хрупкая точка входа — datasets_list/models_list отдают
# Markdown, а не JSON. Если kaggle-mcp-server сменит формат вывода, эта функция
# молча вернёт [] (см. warning в _collect_*_candidates) без явного краша —
# при отладке "почему база не пополняется" начинать проверку отсюда.

_LIST_ENTRY_RE = re.compile(r"^-\s+\*\*(?P<title>.+?)\*\*\s+\(`(?P<ref>[^`]+)`\)", re.MULTILINE)

def _parse_markdown_list(raw_text: str) -> list[dict]:
    items = []
    for m in _LIST_ENTRY_RE.finditer(raw_text):
        items.append({"title": m.group("title").strip(), "ref": m.group("ref").strip()})
    return items


def _extract_ref_parts(item: dict) -> tuple[str, str] | None:
    ref = item.get("ref") or item.get("id")
    if ref and "/" in str(ref):
        owner, slug = str(ref).split("/", 1)
        return owner, slug

    owner = item.get("owner") or item.get("ownerSlug") or item.get("owner_slug")
    slug = item.get("slug") or item.get("datasetSlug") or item.get("dataset_slug") or item.get("modelSlug")
    if owner and slug:
        return owner, slug

    logger.warning(f"Не удалось извлечь owner/slug из объекта: {item}")
    return None


def _extract_full_text(detail: dict) -> str:
    for key in ("description", "subtitle", "overview", "summary"):
        value = detail.get(key)
        if value and isinstance(value, str) and value.strip():
            return value.strip()
    logger.warning(f"Не найдено текстовое поле в JSON-ответе, использую весь объект: {list(detail.keys())}")
    return json.dumps(detail, ensure_ascii=False)


# Поля метаданных Kaggle, где могут лежать собственные теги датасета (ТЗ 4.1)
_TAG_KEYS = ("tags", "keywords", "categories")
# Поля со счётчиком решений/ноутбуков (ТЗ 4.2)
# kernelCount — реальное поле ответа dataset_get (проверено на uciml/iris); остальные — запасные из ТЗ
_KERNEL_COUNT_KEYS = ("kernelCount", "totalKernels", "kernelsCount", "scriptCount")
_VOTE_KEYS = ("voteCount", "totalVotes", "votes")


def _extract_tags(detail: dict) -> list[str]:
    """Собственные теги Kaggle: tags / keywords / categories. Элементы бывают строками или
    объектами ({"name": ..} / {"title": ..} / {"slug": ..}); строку через запятую разбиваем."""
    tags: list[str] = []
    for key in _TAG_KEYS:
        value = detail.get(key)
        if not value:
            continue
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, (list, tuple)):
            continue
        for item in value:
            if isinstance(item, dict):
                item = item.get("name") or item.get("title") or item.get("slug") or item.get("ref")
            if isinstance(item, str) and item.strip():
                tags.append(item.strip())
    return list(dict.fromkeys(tags))  # дедуп с сохранением порядка


def _first_int(detail: dict, keys: tuple) -> int | None:
    for key in keys:
        value = detail.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _build_kaggle_code_link(code_url: str, count: int | None) -> dict:
    """ТЗ п.5: элемент related_links типа kaggle_code; count — только если число известно."""
    link = {"type": "kaggle_code", "name": "Решения (Code)", "url": code_url}
    if count is not None:
        link["count"] = count
    return link


# --- Сбор кандидатов (list + get) для датасетов и моделей ---

async def _collect_dataset_candidates(session: ClientSession, query: str, limit: int) -> list[dict]:
    raw_list = await _call_tool(session, "datasets_list", {"search": query, "page": 1})
    items = _parse_markdown_list(raw_list)
    if not items:
        logger.warning(f"Не удалось распарсить список датасетов, сырой ответ: {raw_list[:500]}")
        return []

    candidates = []
    for item in items[:limit]:
        parts = _extract_ref_parts(item)
        if not parts:
            continue
        owner, slug = parts

        raw_get = await _call_tool(session, "dataset_get", {"owner": owner, "dataset_slug": slug})
        detail = _safe_json_loads(raw_get)

        if not isinstance(detail, dict):
            logger.warning(f"Не удалось распарсить dataset_get для {owner}/{slug}, пропущен.")
            continue

        full_text = _extract_full_text(detail)
        if not full_text:
            logger.warning(f"Пустой full_text для датасета {owner}/{slug}, пропущен.")
            continue

        candidates.append({
            "id": f"dataset:{owner}/{slug}",
            "type": "dataset",
            "title": item["title"],
            "full_text": full_text,
            "url": f"{KAGGLE_BASE_URL}/datasets/{owner}/{slug}",
            "tags": _extract_tags(detail),
            "votes": _first_int(detail, _VOTE_KEYS) or 0,
            "related_links": [
                _build_kaggle_code_link(
                    f"{KAGGLE_BASE_URL}/datasets/{owner}/{slug}/code",
                    _first_int(detail, _KERNEL_COUNT_KEYS),
                )
            ],
        })
    return candidates


async def _collect_model_candidates(session: ClientSession, query: str, limit: int) -> list[dict]:
    raw_list = await _call_tool(session, "models_list", {"search": query, "page_size": limit})
    items = _parse_markdown_list(raw_list)
    if not items:
        logger.warning(f"Не удалось распарсить список моделей, сырой ответ: {raw_list[:500]}")
        return []

    candidates = []
    for item in items[:limit]:
        parts = _extract_ref_parts(item)
        if not parts:
            continue
        owner, slug = parts

        raw_get = await _call_tool(session, "model_get", {"owner": owner, "model_slug": slug})
        detail = _safe_json_loads(raw_get)

        if not isinstance(detail, dict):
            logger.warning(f"Не удалось распарсить model_get для {owner}/{slug}, пропущена.")
            continue

        full_text = _extract_full_text(detail)
        if not full_text:
            logger.warning(f"Пустой full_text для модели {owner}/{slug}, пропущена.")
            continue

        candidates.append({
            "id": f"model:{owner}/{slug}",
            "type": "model",
            "title": item["title"],
            "full_text": full_text,
            "url": f"{KAGGLE_BASE_URL}/models/{owner}/{slug}",
            "tags": _extract_tags(detail),
            "votes": _first_int(detail, _VOTE_KEYS) or 0,
            "related_links": [],
        })
    return candidates


# --- Публичный интерфейс модуля (асинхронный) ---

def _suppress_benign_proactor_errors(loop, context):
    if "Cancelling an overlapped future failed" in context.get("message", ""):
        return
    loop.default_exception_handler(context)


async def fetch_materials_via_mcp(query: str = "machine learning") -> list[dict]:
    asyncio.get_running_loop().set_exception_handler(_suppress_benign_proactor_errors)

    if not os.getenv("KAGGLE_USERNAME") or not os.getenv("KAGGLE_KEY"):
        logger.warning("KAGGLE_USERNAME/KAGGLE_KEY не заданы — запросы к Kaggle, скорее всего, завершатся ошибкой")

    articles_payload = []

    logger.info("Запуск подпроцесса Kaggle MCP сервера...")
    try:
        async with stdio_client(KAGGLE_SERVER_PARAMS) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                dataset_candidates = await _collect_dataset_candidates(session, query, CANDIDATES_PER_TYPE)
                model_candidates = await _collect_model_candidates(session, query, CANDIDATES_PER_TYPE)
                all_candidates = dataset_candidates + model_candidates

                if not all_candidates:
                    logger.info("Нет кандидатов для анализа. Завершение работы модуля.")
                    return articles_payload

                # Порядок задаёт Kaggle — локально по дате НЕ пересортировываем. Чтобы в выборку попали и датасеты, и модели, берём кандидатов
                # попеременно, сохраняя исходный ранг внутри каждого типа.
                trending_candidates = [
                    c for c in chain.from_iterable(zip_longest(dataset_candidates, model_candidates))
                    if c is not None
                ][:TRENDING_TOP_N]
                candidates_by_id = {c["id"]: c for c in trending_candidates}

                llm_input = [
                    {"id": c["id"], "type": c["type"], "title": c["title"], "full_text": c["full_text"]}
                    for c in trending_candidates
                ]

                logger.info(f"Отправка {len(llm_input)} трендовых кандидатов в LLM API на тематический отбор...")
                start_time = time.perf_counter()

                try:
                    prompt = (
                        "Вот список кандидатов в формате JSON. Отбери подходящие по теме:\n\n"
                        f"{json.dumps(llm_input, ensure_ascii=False)}"
                    )
                    result = await _get_selector_agent().run(prompt)

                    # dict.fromkeys сохраняет порядок и убирает возможные дубликаты id,
                    # которые LLM ничем не гарантирует не повторить
                    for sid in dict.fromkeys(result.output.selected_ids):
                        original = candidates_by_id.get(sid)
                        if not original:
                            logger.warning(f"LLM вернула неизвестный id, пропущено: {sid}")
                            continue

                        articles_payload.append({
                            "title": f"[Kaggle] {original['title']}",
                            "text": original["full_text"],
                            "source_url": original["url"],
                            # Kaggle отдаёт и датасеты, и модели вперемешку —
                            # используем реальный тип кандидата, а не общий "датасет".
                            "source_type": "модель" if original["type"] == "model" else "датасет",
                            # ТЗ 4.1: нативные теги Kaggle -> поле tags таблицы articles
                            "tags": original["tags"],
                            "stars": original["votes"],
                            # ТЗ 4.2 / п.5: ссылка на вкладку /code со счётчиком решений
                            "related_links": original["related_links"],
                        })
                except ValidationError as val_err:
                    logger.error(f"LLM нарушил контракт Pydantic-схемы: {val_err}")
                except Exception as llm_err:
                    logger.error(f"Ошибка при вызове LLM API: {llm_err}")
                finally:
                    logger.info("LLM Finished in %.2fs", time.perf_counter() - start_time)

    except Exception as mcp_err:
        logger.error(f"Критический сбой транспорта Kaggle MCP: {mcp_err}")
        raise

    return articles_payload


# --- Синхронная обёртка под контракт stream_all_new_articles() ---

def stream_kaggle_articles(query: str = "machine learning"):
    articles = asyncio.run(fetch_materials_via_mcp(query))
    for article in articles:
        yield article


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("ЗАПУСК НАДЕЖНОГО ТЕСТА: LOCAL LLM + KAGGLE MCP")
    try:
        res = asyncio.run(fetch_materials_via_mcp("LLM"))
        print(f"\nМодуль отработал успешно. Получено объектов для БД: {len(res)}")
        print(json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as main_e:
        print(f"\nТест завершился критической ошибкой: {main_e}")