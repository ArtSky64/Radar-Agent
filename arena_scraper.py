import datetime
import json
import logging
import ssl
import urllib.request
import re
from collections import defaultdict

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from database import init_db, save_leaderboard_data

logger = logging.getLogger("arena_scraper")

# Канонические URL Арены (для совместимости)
CATEGORY_URLS = {
    "text": "https://arena.ai/leaderboard/chat/text",
    "vision": "https://arena.ai/leaderboard/chat/vision",
    "search": "https://arena.ai/leaderboard/chat/search",
    "document": "https://arena.ai/leaderboard/chat/document",
    "webdev": "https://arena.ai/leaderboard/code/webdev",
    "image-to-webdev": "https://arena.ai/leaderboard/code/image-to-webdev",
    "text-to-image": "https://arena.ai/leaderboard/image/text-to-image",
    "image-edit": "https://arena.ai/leaderboard/image/image-edit/single-image",
    "text-to-video": "https://arena.ai/leaderboard/video/text-to-video",
    "image-to-video": "https://arena.ai/leaderboard/video/image-to-video",
    "video-edit": "https://arena.ai/leaderboard/video/video-edit",
    "agent": "https://arena.ai/leaderboard/agent",
    "alignment": "https://arena.ai/leaderboard/agent/alignment",
}

# Соответствие категорий Арены официальным конфигам датасета lmarena-ai/leaderboard-dataset
CATEGORY_MAP = {
    "text": "text",
    "vision": "vision",
    "search": "search",
    "document": "document",
    "webdev": "webdev",
    "text-to-image": "text_to_image",
    "image-edit": "image_edit",
    "text-to-video": "text_to_video",
    "image-to-video": "image_to_video",
    "video-edit": "video_edit",
    "agent": "agent",
}

HF_DATASET_NAME = "lmarena-ai/leaderboard-dataset"
HF_API_BASE = "https://datasets-server.huggingface.co/rows"


def generate_model_breakdown(name: str, org: str, category: str, rating: float, license_str: str, vote_count: int) -> str:
    """Генерирует развернутую карточку модели: назначение (для чего), архитектура и результаты в Arena."""
    org_title = org.title() if org else "Ведущая AI-лаборатория"
    cat_lower = (category or "").lower()
    name_lower = (name or "").lower()

    if any(k in cat_lower for k in ("webdev", "code", "coding")) or "coder" in name_lower:
        purpose = "Сложная веб-разработка, сквозное написание и аудит кода (фронтенд/бэкенд), проектирование архитектуры ПО, рефакторинг и дебаггинг кодовых баз."
        stack_info = "Оптимизирована для работы с AST-деревьями, синтаксисом современных фреймворков и длинными контекстами проектов."
    elif "agent" in cat_lower or "agent" in name_lower:
        purpose = "Автономные ИИ-агенты, мультиагентные сценарии, планирование цепочек действий, надежный вызов инструментов (Tool/Function Calling) и структурированный вывод."
        stack_info = "Обладает высокой устойчивостью к сбоям в цикле рассуждений (reflection/re-planning) и точным следованием системным инструкциям."
    elif any(k in cat_lower for k in ("vision", "document", "search")) or "vision" in name_lower or "ocr" in name_lower:
        purpose = "Мультимодальный анализ, распознавание схем, таблиц, графиков, обработка отсканированных документов высокой плотности (OCR) и фактологический поиск."
        stack_info = "Включает сбалансированные визуально-текстовые энкодеры для кросс-модальных рассуждений без потери детализации."
    elif any(k in cat_lower for k in ("video", "text-to-video", "image-to-video")):
        purpose = "Генерация динамических видеороликов, интерполяция кадров, преобразование статических изображений в видео и анимация со стабильной физикой движения."
        stack_info = "Современная диффузионная или авторегрессионная видео-архитектура с пространственно-временным вниманием (Spatiotemporal Attention)."
    elif any(k in cat_lower for k in ("image", "text-to-image", "image-edit")):
        purpose = "Фотореалистичная и художественная генерация изображений, точное редактирование по маске, композиция сцен и сохранение стиля."
        stack_info = "Высокое разрешение генерации, улучшенная анатомия и точное следование комплексным текстовым промптам."
    else:
        purpose = "Глубокие логические и математические рассуждения (reasoning), аналитика сложных текстов, научные изыскания, экспертные диалоги и синтез информации."
        stack_info = "Флагманский уровень языкового интеллекта с развитой способностью к пошаговому логическому выводу (chain-of-thought)."

    is_open = license_str and license_str.lower() not in ("proprietary", "commercial", "closed", "unknown", "")
    if is_open:
        lic_desc = f"открытые веса ({license_str}), подходит для локального развертывания (vLLM, Ollama, SGLang)"
    else:
        lic_desc = f"коммерческое облачное API ({license_str or 'Proprietary'})"

    special_note = ""
    if "gemini" in name_lower:
        special_note = " Нативно поддерживает длинный контекст до 2M токенов и мультимодальный ввод."
    elif "claude" in name_lower:
        special_note = " Выделяется эталонной безопасностью, качеством генерации кода и аккуратным следованием системному промпту."
    elif "gpt" in name_lower or "o1" in name_lower or "o3" in name_lower:
        special_note = " Продвинутые возможности рассуждения с генерацией внутренних цепочек мысли перед ответом."
    elif "mimo" in name_lower:
        special_note = " Высокая энергоэффективность и оптимальный баланс скорости инференса к качеству."
    elif "deepseek" in name_lower:
        special_note = " MoE-архитектура с эффективной активацией экспертов и низкой стоимостью токена."
    elif "qwen" in name_lower:
        special_note = " Сильная мультиязычность, поддержка математики и кодинга на открытых весах."

    votes_str = f" на основе {vote_count:,} слепых матчей" if vote_count > 0 else ""
    return (
        f"• Назначение (для чего): {purpose}\n"
        f"• Архитектура и стек: Разработка {org_title} ({lic_desc}). {stack_info}{special_note}\n"
        f"• Результаты в Arena: {rating} Elo в категории «{category.upper()}»{votes_str}."
    )


def fetch_category_from_hf(config_name: str, limit: int = 25) -> list[dict]:
    """
    Забирает свежий срез категории лидерборда из официального датасета lmarena-ai на Hugging Face.
    Работает быстро по HTTP без браузера, капч и таймаутов Cloudflare.
    """
    url = f"{HF_API_BASE}?dataset={HF_DATASET_NAME}&config={config_name}&split=latest&offset=0&limit={limit}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ArenaRadarBot/1.0)"}
    )

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = []
    seen = set()
    for item in data.get("rows", []):
        row = item.get("row", {})
        name = (row.get("model_name") or "").strip()
        if not name or name in seen:
            continue

        if "rating" in row and row["rating"] is not None:
            rating = round(float(row["rating"]), 1)
        elif "score" in row and row["score"] is not None:
            raw_s = float(row["score"])
            # В бенчмарке agent оценка — нормализованная доля (0.208 -> 20.8%)
            rating = round(raw_s * 100, 1) if abs(raw_s) <= 1.0 else round(raw_s, 1)
        else:
            continue

        organization = (row.get("organization") or "").strip()
        license_str = (row.get("license") or "").strip()
        vote_count = int(row.get("vote_count") or 0)

        summary = generate_model_breakdown(
            name=name,
            org=organization,
            category=config_name,
            rating=rating,
            license_str=license_str,
            vote_count=vote_count
        )

        seen.add(name)
        results.append({
            "name": name,
            "rating": rating,
            "organization": organization,
            "license": license_str,
            "vote_count": vote_count,
            "summary": summary,
        })

    return results


def parse_browser_page(page) -> list[dict]:
    """Резервный парсер HTML-страницы через Playwright (если HF недоступен)."""
    table = page.locator("table").first
    table.locator("tbody tr").first.wait_for(timeout=10000)

    headers = table.locator("thead th, tr:first-child th").all()
    model_idx = 1
    score_idx = 2
    for i, header in enumerate(headers):
        text = header.inner_text().lower()
        if "model" in text:
            model_idx = i
        elif "score" in text or "rating" in text or "elo" in text:
            score_idx = i

    rows = table.locator("tbody tr").all()
    visible_rows = [r for r in rows if r.is_visible()]
    parsed_data = []
    seen_names = set()

    for index, row in enumerate(visible_rows):
        if len(parsed_data) >= 25:
            break
        try:
            cells = row.locator("td").all()
            if len(cells) <= max(model_idx, score_idx):
                continue

            raw_name = cells[model_idx].inner_text().strip()
            raw_rating = cells[score_idx].inner_text().strip()
            clean_name = raw_name.split("\n")[0].strip()
            clean_rating_str = raw_rating.split("\n")[0].strip().replace("%", "")

            rating_match = re.search(r"([0-9]+(?:\.[0-9]+)?)", clean_rating_str)
            if rating_match:
                val_str = rating_match.group(1)
                clean_rating = float(val_str) if "." in val_str else int(val_str)
            else:
                try:
                    clean_rating = float(clean_rating_str) if "." in clean_rating_str else int(clean_rating_str)
                except ValueError:
                    clean_rating = clean_rating_str

            if clean_name and clean_name not in seen_names:
                seen_names.add(clean_name)
                parsed_data.append({"name": clean_name, "rating": clean_rating})
        except Exception:
            continue

    return parsed_data


def collect_all_categories(category_urls=None, limit: int = 25) -> dict:
    """
    Собирает данные лидерборда LMSYS Arena по всем ключевым категориям.
    Основной надежный метод — через официальный датасет lmarena-ai/leaderboard-dataset на HF.
    При сбое обращается к Playwright как к запасному варианту.
    """
    fetched_at = datetime.datetime.now().isoformat()
    all_data = {}

    print(f"\n[Арена] Сбор данных через официальный API lmarena-ai (Hugging Face)...")
    total_cats = len(CATEGORY_MAP)
    for idx, (cat_name, hf_config) in enumerate(CATEGORY_MAP.items(), start=1):
        try:
            models = fetch_category_from_hf(hf_config, limit=limit)
            if models:
                all_data[cat_name] = models
                top1 = models[0]
                print(f"[{idx}/{total_cats}] [OK] {cat_name:<15} ({len(models)} моделей) -> #1 {top1['name']} ({top1['rating']})")
            else:
                logger.warning(f"Категория '{cat_name}' вернула пустой список.")
        except Exception as e:
            logger.warning(f"Ошибка при получении '{cat_name}' через HF: {e}")
            print(f"[{idx}/{total_cats}] [ОШИБКА HF] {cat_name}: {e}")

    # Резервный Playwright (если HF полностью упал и ничего не вернул)
    if not all_data and sync_playwright is not None:
        print("[Арена] HF недоступен, пробуем резервный Playwright...")
        urls = category_urls or CATEGORY_URLS
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                for cat, url in urls.items():
                    try:
                        ctx = browser.new_context(user_agent="Mozilla/5.0")
                        page = ctx.new_page()
                        page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        page.wait_for_selector("table", timeout=15000)
                        p = parse_browser_page(page)
                        if p:
                            all_data[cat] = p
                        ctx.close()
                    except Exception:
                        pass
                browser.close()
        except Exception as e:
            logger.warning(f"Сбой резервного Playwright: {e}")

    if not all_data:
        logger.error("Сбор лидерборда Arena не дал результатов.")
        print("[ОШИБКА] Не удалось собрать ни одной категории лидерборда Arena.")
    else:
        print(f"\n[ИТОГ] Успешно собрано категорий лидерборда Arena: {len(all_data)}/{len(CATEGORY_MAP)}")

    return {
        "fetched_at": fetched_at,
        "categories": all_data
    }


def save_to_db(data: dict) -> None:
    if not data or not data.get("categories"):
        print("\n[ПРЕДУПРЕЖДЕНИЕ] Новые данные лидерборда отсутствуют. Предыдущие данные сохранены в базе.")
        return

    init_db()
    save_leaderboard_data(data)
    total_models = sum(len(v) for v in data["categories"].values())
    print(f"\n[УСПЕХ] Сохранено в БД: {total_models} строк по {len(data['categories'])} категориям (снимок {data['fetched_at']})")

    print("[АНАЛИЗ] Строим инкрементальный анализ (новый снимок + предыдущий)...")
    try:
        from leaderboard_analyzer import run_leaderboard_analysis
        run_leaderboard_analysis()
    except Exception as e:
        logger.warning(f"Анализ лидерборда пропущен или завершился ошибкой: {e}")
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Ошибка анализа лидерборда: {e}")
    print("[АНАЛИЗ] Готово.")


def format_cat_plural(n: int) -> str:
    """Склонение слова 'категория' в русском языке."""
    if 11 <= n % 100 <= 14:
        return "категорий"
    last = n % 10
    if last == 1:
        return "категория"
    if 2 <= last <= 4:
        return "категории"
    return "категорий"


def aggregate_all_categories(records: list[dict], method: str = "avg") -> list[dict]:
    """
    Агрегация «Все категории» лидерборда Arena.
    Группирует записи по model_name и вычисляет средний или максимальный рейтинг.
    """
    by_model = defaultdict(list)
    for r in records:
        name = (r.get("model_name") or "").strip()
        if name:
            by_model[name].append(r)

    aggregated = []
    for name, rows in by_model.items():
        valid_ratings = []
        for r in rows:
            val = r.get("rating")
            try:
                valid_ratings.append(float(val))
            except (ValueError, TypeError):
                pass

        if not valid_ratings:
            continue

        if method == "max":
            chosen_rating = max(valid_ratings)
        else:
            chosen_rating = round(sum(valid_ratings) / len(valid_ratings), 1)

        cats = sorted({r.get("category", "") for r in rows if r.get("category")})
        aggregated.append({
            "model_name": name,
            "rating": chosen_rating,
            "categories": cats,
            "category": f"{len(cats)} {format_cat_plural(len(cats))}",
            "is_aggregated": True,
        })

    aggregated.sort(key=lambda x: x["rating"], reverse=True)
    return aggregated


def main():
    print("Запуск сбора лидерборда LMSYS Arena (через Hugging Face)...")
    data = collect_all_categories()
    save_to_db(data)
    print("\n[УСПЕХ] Обновление лидерборда Arena полностью завершено!")


if __name__ == "__main__":
    main()
