import datetime
import json
import logging
import time
import random
import re
from collections import defaultdict
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from database import init_db, save_leaderboard_data

logger = logging.getLogger("arena_scraper")

# ==========================================
# ЧАСТЬ 1: КАНОНИЧЕСКИЕ URL АРЕНЫ
# ==========================================
# Точные канонические URL без промежуточных 301-редиректов,
# исключающие вызовы антибот-проверок Cloudflare.
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


# ==========================================
# ЧАСТЬ 2: ПАРСЕР ТАБЛИЦЫ ЛИДЕРБОРДА
# ==========================================
def parse(page) -> list[dict]:
    """
    Извлекает топ-5 моделей из таблицы текущей категории лидерборда.
    Динамически определяет индексы колонок названия модели и рейтинга (Elo / Score).
    """
    table = page.locator("table").first
    table.locator("tbody tr").first.wait_for(timeout=10000)

    # 1. Анализируем заголовки таблицы для определения колонок
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
        if len(parsed_data) >= 5:
            break
        try:
            cells = row.locator("td").all()
            if len(cells) <= max(model_idx, score_idx):
                continue

            raw_name = cells[model_idx].inner_text().strip()
            raw_rating = cells[score_idx].inner_text().strip()

            clean_name = raw_name.split('\n')[0].strip()
            clean_rating_str = raw_rating.split('\n')[0].strip().replace('%', '')

            # Извлекаем числовое значение рейтинга (отсекая погрешности вида ±7, +14/-14)
            rating_match = re.search(r'([0-9]+(?:\.[0-9]+)?)', clean_rating_str)
            if rating_match:
                val_str = rating_match.group(1)
                clean_rating = float(val_str) if '.' in val_str else int(val_str)
            else:
                try:
                    clean_rating = float(clean_rating_str) if '.' in clean_rating_str else int(clean_rating_str)
                except ValueError:
                    clean_rating = clean_rating_str

            if clean_name and clean_name not in seen_names:
                seen_names.add(clean_name)
                parsed_data.append({"name": clean_name, "rating": clean_rating})

        except Exception as e:
            logger.debug(f"Ошибка парсинга строки {index + 1}: {e}")
            continue

    return parsed_data


# ==========================================
# ЧАСТЬ 3: КООРДИНАТОР И ЗАПУСК
# ==========================================
def collect_all_categories(category_urls=None):
    """
    Собирает данные лидерборда LMSYS Arena по всем категориям.
    Каждая категория опрашивается по каноническому URL в изолированном контексте браузера
    с глубокой stealth-маскировкой, исключающей вызовы Cloudflare Turnstile.
    Никаких устаревших моделей 2024 года в базу не подмешивается.
    """
    if category_urls is None:
        category_urls = CATEGORY_URLS

    fetched_at = datetime.datetime.now().isoformat()
    all_data = {}

    if sync_playwright is None:
        logger.warning("Playwright не установлен в окружении.")
        print("[ОШИБКА] Playwright не установлен в окружении. Сбор невозможен.")
        return {"fetched_at": fetched_at, "categories": {}}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                    "--ignore-certificate-errors",
                    "--disable-gpu",
                ]
            )

            total_cats = len(category_urls)
            for cat_idx, (category, url) in enumerate(category_urls.items(), start=1):
                print(f"\n--- [{cat_idx}/{total_cats}] Собираем категорию: {category} ---")
                print(f"Открываем страницу: {url}")

                context = browser.new_context(
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="America/New_York",
                    java_script_enabled=True,
                )
                page = context.new_page()

                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [{ name: 'PDF Viewer' }, { name: 'Chrome PDF Viewer' }, { name: 'Chromium PDF Viewer' }]
                    });
                    Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] });
                    Object.defineProperty(navigator, 'platform', { get: () => 'Linux x86_64' });
                    window.chrome = { runtime: {}, loadTimes: Date.now, csi: () => {}, app: {} };
                """)

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_selector("table", timeout=20000)
                    parsed_list = parse(page)
                    if parsed_list:
                        all_data[category] = parsed_list
                        top1 = parsed_list[0]
                        print(f"[УСПЕХ] Собрано {len(parsed_list)} моделей для категории '{category}'")
                        print(f"        #1 {top1['name']} ({top1['rating']} Elo)")
                    else:
                        print(f"[ПРЕДУПРЕЖДЕНИЕ] Категория '{category}' не вернула строк.")
                except Exception as e:
                    print(f"[ПРОПУСК] Категория '{category}' пропущена: {e}")
                    logger.warning(f"Не удалось собрать категорию '{category}': {e}")
                finally:
                    context.close()

                # Небольшая естественная пауза между запросами
                time.sleep(random.uniform(1.2, 2.2))

            browser.close()
    except Exception as e:
        logger.warning(f"Сбой при работе браузера Playwright: {e}")
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Ошибка браузера Playwright: {e}")

    if not all_data:
        logger.error("Скрапинг арены в реальном времени не дал результатов.")
        print("[ОШИБКА] Не удалось собрать ни одной категории лидерборда Arena.")
    else:
        print(f"\n[ИТОГ] Собрано актуальных категорий с живого сайта: {len(all_data)}/{len(category_urls)}")

    final_snapshot = {
        "fetched_at": fetched_at,
        "categories": all_data
    }

    return final_snapshot


def save_to_db(data):
    if not data or not data.get("categories"):
        print("\n[ПРЕДУПРЕЖДЕНИЕ] Новые данные лидерборда отсутствуют. Предыдущие данные сохранены в базе.")
        return

    init_db()
    save_leaderboard_data(data)
    print(f"\n[УСПЕХ] Сохранено в БД: {sum(len(v) for v in data['categories'].values())} строк "
          f"по {len(data['categories'])} категориям (снимок от {data['fetched_at']})")

    print("[АНАЛИЗ] Строим инкрементальный анализ (новый снимок + предыдущий + предыдущий анализ)...")
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
    Группирует записи по model_name и вычисляет:
    - method='avg': средний рейтинг Elo по категориям модели.
    - method='max': максимальный рейтинг.
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
    print(f"Запуск скрапера Arena AI для {len(CATEGORY_URLS)} категорий...")
    data = collect_all_categories(CATEGORY_URLS)
    save_to_db(data)
    print("\n[УСПЕХ] Сбор данных Arena AI завершен!")


if __name__ == "__main__":
    main()