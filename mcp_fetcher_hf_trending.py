import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
import httpx

import config
from agent_manager import (
    HFModelCard,
    analyze_hf_model,
    analyze_hf_model_async,
    clean_model_tags,
    extract_model_parameters,
)
from database import save_trending_models, init_db

logger = logging.getLogger("hf_trending_fetcher")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

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


async def _fetch_models(client: httpx.AsyncClient, url: str) -> list[dict]:
    """Делает GET-запрос к API моделей Hugging Face с обработкой ошибок."""
    try:
        resp = await client.get(url, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Ошибка запроса к {url}: {e}")
        return []


async def _fetch_model_card(client: httpx.AsyncClient, model_id: str) -> dict:
    """Загружает расширенную карточку модели с Hugging Face."""
    url = f"https://huggingface.co/api/models/{model_id}"
    try:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug(f"Не удалось загрузить карточку для {model_id}: {e}")
        return {}


async def fetch_trending_models_async(limit: int = 50) -> list[dict]:
    """
    Основной пайплайн сбора трендовых моделей Hugging Face:
    1. Параллельный сбор:
       - Мировые тренды: https://huggingface.co/models?sort=trending (API: sort=trendingScore)
       - Русскоязычные тренды (ссылка 1): https://huggingface.co/models?language=ru&sort=trending (API: filter=ru)
       - Русскоязычные тренды (ссылка 2): https://huggingface.co/models?language=rus&sort=trending (API: filter=rus)
    2. Объединение двух русскоязычных ссылок с дедупликацией и расчетом сквозного RU-рейтинга.
    3. Связка с общим (мировым) рейтингом трендов.
    4. Порезка и фильтрация мусорных тегов (отсечение тысяч языковых кодов и технических меток).
    5. Извлечение количества параметров (например '27B', '7B', '70B') и типа модели (pipeline_tag).
    6. ИИ-анализ через Qwen: саммари 1-3 предложения, 0-4 направления (HF_DIRECTIONS), 0-3 типа задачи (HF_TASK_TYPES).
    7. Сохранение в базу данных и консольный отчет по МСК.
    """
    logger.info("Запуск сбора трендовых моделей Hugging Face (Общий + RU ru/rus)...")
    init_db()

    base_api = "https://huggingface.co/api/models?sort=trendingScore&direction=-1"
    url_general = f"{base_api}&limit={limit}"
    url_ru = f"{base_api}&filter=ru&limit={limit}"
    url_rus = f"{base_api}&filter=rus&limit={limit}"

    proxy = _get_proxy_url()
    client_kwargs = {"trust_env": True, "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        # Шаг 1: Параллельный опрос 3 источников
        logger.info("Опрос API Hugging Face: General, filter=ru, filter=rus...")
        general_task = _fetch_models(client, url_general)
        ru_task = _fetch_models(client, url_ru)
        rus_task = _fetch_models(client, url_rus)

        general_list, ru_list, rus_list = await asyncio.gather(
            general_task, ru_task, rus_task
        )

        logger.info(
            f"Получено моделей от HF: General={len(general_list)}, RU(ru)={len(ru_list)}, RU(rus)={len(rus_list)}"
        )

        # Шаг 2: Объединение ссылок 1 и 2 (ru + rus) с дедупликацией
        ru_merged_map = {}

        def _process_ru_entry(item: dict, src_tag: str):
            m_id = item.get("id") or item.get("modelId")
            if not m_id:
                return
            score = float(item.get("trendingScore", 0.0) or 0.0)
            if m_id not in ru_merged_map:
                ru_merged_map[m_id] = {
                    "raw": item,
                    "sources": {src_tag},
                    "max_trending_score": score,
                    "downloads": int(item.get("downloads", 0) or 0),
                    "likes": int(item.get("likes", 0) or 0),
                }
            else:
                ru_merged_map[m_id]["sources"].add(src_tag)
                if score > ru_merged_map[m_id]["max_trending_score"]:
                    ru_merged_map[m_id]["max_trending_score"] = score
                    ru_merged_map[m_id]["raw"] = item

        for it in ru_list:
            _process_ru_entry(it, "ru")
        for it in rus_list:
            _process_ru_entry(it, "rus")

        # Сортируем объединённый русский список по trendingScore, затем по likes/downloads
        sorted_ru_models = sorted(
            ru_merged_map.values(),
            key=lambda x: (x["max_trending_score"], x["likes"], x["downloads"]),
            reverse=True,
        )

        # Проставляем рейтинг RU: 1, 2, 3...
        ru_ranks = {}
        for rank_idx, ru_entry in enumerate(sorted_ru_models, start=1):
            m_id = ru_entry["raw"].get("id") or ru_entry["raw"].get("modelId")
            ru_ranks[m_id] = rank_idx

        # Шаг 3: Обработка мирового топа и простановка глобального рейтинга
        global_ranks = {}
        for rank_idx, it in enumerate(general_list, start=1):
            m_id = it.get("id") or it.get("modelId")
            if m_id and m_id not in global_ranks:
                global_ranks[m_id] = rank_idx

        # Шаг 4: Формируем единый словарь всех отобранных моделей
        all_selected_map = {}

        # Добавляем мировые модели
        for it in general_list:
            m_id = it.get("id") or it.get("modelId")
            if not m_id or m_id in all_selected_map:
                continue
            all_selected_map[m_id] = {
                "raw": it,
                "is_global": True,
                "is_ru": m_id in ru_ranks,
            }

        # Добавляем все русскоязычные модели из объединённого списка (даже если их нет в мировом топе)
        for ru_entry in sorted_ru_models:
            m_id = ru_entry["raw"].get("id") or ru_entry["raw"].get("modelId")
            if not m_id:
                continue
            if m_id in all_selected_map:
                all_selected_map[m_id]["is_ru"] = True
            else:
                all_selected_map[m_id] = {
                    "raw": ru_entry["raw"],
                    "is_global": False,
                    "is_ru": True,
                }

        # Полный список моделей для обогащения (мировые + объединённый русский топ ru+rus)
        candidates = list(all_selected_map.values())
        logger.info(
            f"Всего уникальных моделей для анализа: {len(candidates)} "
            f"(мировые: {len(global_ranks)}, русскоязычные: {len(ru_ranks)})."
        )

        final_models = []
        fetched_at = datetime.now(MSK_TZ).isoformat()

        # Шаг 5: Загрузка карточек, порезка тегов, извлечение параметров и ИИ-анализ
        for idx, entry in enumerate(candidates, start=1):
            item = entry["raw"]
            m_id = item.get("id") or item.get("modelId")
            if not m_id:
                continue

            rank_g = global_ranks.get(m_id, 0)
            rank_r = ru_ranks.get(m_id, 0)

            trending_score = float(item.get("trendingScore", 0.0) or 0.0)
            downloads = int(item.get("downloads", 0) or 0)
            likes = int(item.get("likes", 0) or 0)
            raw_tags = item.get("tags", [])

            # Порезка тегов: вырезаем мусорные языковые коды и тех. метки (макс 5)
            cleaned_tags = clean_model_tags(raw_tags, max_tags=5)

            # Определяем вариант и язык
            variant_parts = []
            if entry["is_global"]:
                variant_parts.append("global")
            if entry["is_ru"]:
                variant_parts.append("ru")
            variant = ",".join(variant_parts)
            lang = "ru" if entry["is_ru"] else ""

            try:
                # Получаем карточку модели с HF
                card_data = await _fetch_model_card(client, m_id)
                pipeline_tag = card_data.get("pipeline_tag") or item.get("pipeline_tag", "")

                # Извлечение лицензии
                license_tag = next(
                    (t.replace("license:", "") for t in raw_tags if str(t).startswith("license:")),
                    "",
                )

                # Извлечение текста README из cardData
                readme_obj = card_data.get("cardData", {})
                if isinstance(readme_obj, dict):
                    readme_text = json.dumps(readme_obj, ensure_ascii=False)
                else:
                    readme_text = str(readme_obj or "")

                # Извлечение параметров (например, '27B', '7B', '600M')
                extracted_params = extract_model_parameters(m_id, raw_tags, card_data)

                # ИИ-анализ через Qwen / PydanticAI
                logger.info(
                    f"[{idx}/{len(candidates)}] Анализ модели '{m_id}' (Params: {extracted_params or 'N/A'}, Type: {pipeline_tag or 'unknown'})..."
                )
                card: HFModelCard = await analyze_hf_model_async(
                    model_name=m_id,
                    pipeline_tag=pipeline_tag,
                    tags=cleaned_tags,
                    card_description=readme_text,
                )

                final_params = card.parameters or extracted_params

                model_dict = {
                    "name": m_id,
                    "model_name": m_id,
                    "downloads": downloads,
                    "likes": likes,
                    "trending_score": trending_score,
                    "tags": card.tags or cleaned_tags,
                    "url": f"https://huggingface.co/{m_id}",
                    "source_url": f"https://huggingface.co/{m_id}",
                    "summary": card.summary,
                    "pipeline_tag": pipeline_tag,
                    "license": license_tag,
                    "card_description": readme_text[:2000],
                    "language": lang,
                    "variant": variant,
                    "directions": card.directions,
                    "task_types": card.task_types,
                    "parameters": final_params,
                    "rank_global": rank_g,
                    "rank_ru": rank_r,
                    "fetched_at": fetched_at,
                }
                final_models.append(model_dict)
            except Exception as e:
                logger.error(f"Ошибка при обработке модели '{m_id}': {e}. Применяем надежный фолбэк.")
                pipeline_tag = item.get("pipeline_tag", "")
                fallback_params = extract_model_parameters(m_id, raw_tags)
                fallback_model = {
                    "name": m_id,
                    "model_name": m_id,
                    "downloads": downloads,
                    "likes": likes,
                    "trending_score": trending_score,
                    "tags": cleaned_tags or ["AI-Model"],
                    "url": f"https://huggingface.co/{m_id}",
                    "source_url": f"https://huggingface.co/{m_id}",
                    "summary": f"Трендовая модель {m_id} с Hugging Face.",
                    "pipeline_tag": pipeline_tag,
                    "license": "",
                    "card_description": "",
                    "language": lang,
                    "variant": variant,
                    "directions": ["nlp_llm"],
                    "task_types": ["generation"],
                    "parameters": fallback_params,
                    "rank_global": rank_g,
                    "rank_ru": rank_r,
                    "fetched_at": fetched_at,
                }
                final_models.append(fallback_model)

        # Шаг 6: Сохранение в базу данных
        save_trending_models(final_models)
        logger.info(f"Сохранено в базу данных: {len(final_models)} трендовых моделей HF.")

        # Шаг 7: Вывод консольного отчета
        print_hf_trending_summary(final_models, fetched_at=fetched_at)

        return final_models


def print_hf_trending_summary(models: list[dict], fetched_at: str | None = None) -> None:
    """Выводит красиво отформатированный отчет в консоль со сквозным рейтингом."""
    ts_str = f" (Время сбора: {fetched_at} МСК)" if fetched_at else ""
    print("\n" + "=" * 95)
    print(f"АКТУАЛЬНЫЕ ТРЕНДОВЫЕ МОДЕЛИ HUGGING FACE{ts_str}")
    print("=" * 95)

    ru_models = [m for m in models if m.get("rank_ru", 0) > 0]
    ru_models.sort(key=lambda x: x.get("rank_ru", 9999))

    print(f"\n--- [ТОП-РУССКОЯЗЫЧНЫХ МОДЕЛЕЙ (ru + rus)] (Всего: {len(ru_models)}) ---")
    for m in ru_models[:15]:
        r_ru = f"🏆 RU #{m['rank_ru']}"
        r_glob = f"🌍 Global #{m['rank_global']}" if m.get("rank_global") else "🌍 Вне мирового топа"
        params = f"⚡ {m['parameters']}" if m.get("parameters") else "⚡ N/A"
        ptype = f"🏷️ {m.get('pipeline_tag') or 'model'}"
        dirs = ", ".join(m.get("directions") or []) or "нет"
        tasks = ", ".join(m.get("task_types") or []) or "нет"
        tags = ", ".join(m.get("tags") or [])

        print(f"\n{r_ru} | {r_glob} — {m['name']} ({params} | {ptype})")
        print(f"    URL:         {m['url']}")
        print(f"    Метрики:     ⬇ {m['downloads']:,} | ♡ {m['likes']:,} | Score: {m.get('trending_score', 0)}")
        print(f"    Направление: [{dirs}] | Тип задачи: [{tasks}]")
        print(f"    Теги:        [{tags}]")
        print(f"    Описание:    {m['summary']}")

    global_models = [m for m in models if m.get("rank_global", 0) > 0]
    global_models.sort(key=lambda x: x.get("rank_global", 9999))

    print(f"\n--- [МИРОВОЙ ТОП МОДЕЛЕЙ HUGGING FACE] (Всего: {len(global_models)}) ---")
    for m in global_models[:15]:
        r_glob = f"🌍 #{m['rank_global']}"
        ru_badge = f" [🇷🇺 RU #{m['rank_ru']}]" if m.get("rank_ru") else ""
        params = f"⚡ {m['parameters']}" if m.get("parameters") else "⚡ N/A"
        ptype = f"🏷️ {m.get('pipeline_tag') or 'model'}"
        dirs = ", ".join(m.get("directions") or []) or "нет"
        tasks = ", ".join(m.get("task_types") or []) or "нет"

        print(f"\n{r_glob}{ru_badge} — {m['name']} ({params} | {ptype})")
        print(f"    URL:         {m['url']}")
        print(f"    Метрики:     ⬇ {m['downloads']:,} | ♡ {m['likes']:,}")
        print(f"    Направление: [{dirs}] | Тип задачи: [{tasks}]")
        print(f"    Описание:    {m['summary']}")
    print("\n" + "=" * 95 + "\n")


def fetch_trending_models(limit: int = 50) -> list[dict]:
    """Синхронная точка входа для фоновых задач FastAPI и скриптов."""
    return asyncio.run(fetch_trending_models_async(limit=limit))


if __name__ == "__main__":
    fetch_trending_models(limit=30)