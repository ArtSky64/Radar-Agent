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


def generate_model_breakdown(
    name: str,
    org: str = "",
    category: str = "",
    rating: float = 0.0,
    license_str: str = "",
    vote_count: int = 0
) -> str:
    """Генерирует лаконичное, информативное описание модели (1-2 предложения),
    идеально помещающееся в блок карточки лидерборда без перегрузки интерфейса."""
    cat_lower = (category or "").lower()
    name_lower = (name or "").lower()
    lic_lower = (license_str or "").lower()
    is_open = bool(lic_lower and lic_lower not in ("proprietary", "commercial", "closed", "unknown", "none", ""))

    # Распознаем организацию / вендора с нормализацией регистра
    norm_orgs = {
        'openai': 'OpenAI', 'google': 'Google', 'anthropic': 'Anthropic', 'meta': 'Meta',
        'deepseek': 'DeepSeek', 'alibaba': 'Alibaba Cloud', 'alibaba cloud': 'Alibaba Cloud',
        'xiaomi': 'Xiaomi', 'mistral': 'Mistral AI', 'mistral ai': 'Mistral AI', 'xai': 'xAI',
        'zhipu': 'Zhipu AI', 'zhipu ai': 'Zhipu AI', 'microsoft': 'Microsoft', 'minimax': 'MiniMax',
        'wanx': 'WanX', 'kuaishou': 'Kuaishou', 'black forest labs': 'Black Forest Labs',
        'midjourney': 'Midjourney', 'cohere': 'Cohere', 'stability': 'Stability AI',
        'bytedance': 'ByteDance', 'runway': 'Runway',
    }
    org_clean = (org or '').strip()
    detected_org = norm_orgs.get(org_clean.lower(), org_clean)
    if not detected_org:
        if any(k in name_lower for k in ("gemini", "gemma")):
            detected_org = "Google"
        elif "claude" in name_lower:
            detected_org = "Anthropic"
        elif any(k in name_lower for k in ("gpt", "o1", "o3", "chatgpt", "sora")):
            detected_org = "OpenAI"
        elif "deepseek" in name_lower:
            detected_org = "DeepSeek"
        elif "qwen" in name_lower:
            detected_org = "Alibaba Cloud"
        elif "mimo" in name_lower:
            detected_org = "Xiaomi"
        elif "llama" in name_lower:
            detected_org = "Meta"
        elif any(k in name_lower for k in ("mistral", "mixtral", "codestral")):
            detected_org = "Mistral AI"
        elif "grok" in name_lower:
            detected_org = "xAI"
        elif "glm" in name_lower:
            detected_org = "Zhipu AI"
        elif "phi" in name_lower:
            detected_org = "Microsoft"
        elif "minimax" in name_lower:
            detected_org = "MiniMax"
        elif "wan" in name_lower:
            detected_org = "WanX"
        elif "kling" in name_lower:
            detected_org = "Kuaishou"
        elif any(k in name_lower for k in ("flux", "black-forest")):
            detected_org = "Black Forest Labs"
        elif "midjourney" in name_lower:
            detected_org = "Midjourney"

    is_code = any(k in cat_lower for k in ("webdev", "code", "coding")) or any(k in name_lower for k in ("coder", "coding", "codestral", "dev"))
    is_agent = "agent" in cat_lower or "agent" in name_lower
    is_vision = any(k in cat_lower for k in ("vision", "document", "search")) or any(k in name_lower for k in ("vision", "vl", "ocr"))
    is_video = any(k in cat_lower for k in ("video", "text-to-video", "image-to-video")) or any(k in name_lower for k in ("sora", "kling", "wan", "t2v", "i2v"))
    is_image = any(k in cat_lower for k in ("image", "text-to-image", "image-edit")) or any(k in name_lower for k in ("flux", "midjourney", "dall-e", "sdxl"))
    is_reasoning = any(k in cat_lower for k in ("reason", "math", "hard")) or any(k in name_lower for k in ("o1", "o3", "r1", "reasoning", "think"))

    # Семейство Claude
    if "claude" in name_lower:
        if is_code:
            return "Передовая модель от Anthropic для сложной веб-разработки, написания программного кода, проектирования архитектуры и безопасного аудита репозиториев."
        if is_agent:
            return "Агентная флагманская модель от Anthropic, оптимизированная для многоэтапного планирования, надёжного вызова инструментов и следования инструкциям."
        return "Флагманская языковая модель от Anthropic, отличающаяся глубоким логическим мышлением, безопасностью и высокой связностью рассуждений."

    # Семейство Gemini / Gemma
    if "gemini" in name_lower:
        if is_code:
            return "Мультимодальная модель от Google с контекстом до 2M токенов, оптимизированная для сложного анализа кодовых баз и сквозной разработки."
        return "Флагманская мультимодальная модель от Google со сверхдлинным контекстом до 2M токенов для глубокого анализа данных и рассуждений."

    if "gemma" in name_lower:
        return "Компактная открытая модель от Google на базе технологий Gemini, оптимизированная для эффективного локального инференса."

    # Семейство OpenAI (o1, o3, GPT-4)
    if any(k in name_lower for k in ("o1", "o3")):
        return "Передовая модель рассуждений от OpenAI с внутренними цепочками мысли для решения сложных математических, научных и алгоритмических задач."

    if any(k in name_lower for k in ("gpt-4", "gpt 4", "chatgpt")):
        if is_code:
            return "Универсальная модель от OpenAI для программирования, генерации архитектурных решений, рефакторинга и дебаггинга."
        return "Флагманская мультимодальная модель от OpenAI для решения широкого спектра интеллектуальных задач и комплексной аналитики."

    # Семейство DeepSeek
    if "deepseek" in name_lower:
        if is_reasoning or "r1" in name_lower:
            return "Открытая модель рассуждений от DeepSeek с цепочками мыслей для математических доказательств, логики и сложных алгоритмов."
        if is_code:
            return "Высокоэффективная MoE-модель от DeepSeek с открытыми весами, оптимизированная для генерации кода и технической разработки."
        return "Высокопроизводительная MoE-модель от DeepSeek с открытыми весами для эффективного решения сложных языковых и аналитических задач."

    # Семейство Qwen
    if "qwen" in name_lower:
        if is_code:
            return "Мощная модель с открытыми весами от Alibaba Cloud для программирования, работы с современными фреймворками и дебаггинга."
        if is_vision:
            return "Мультимодальная модель от Alibaba Cloud для распознавания визуальных данных, плотных документов и диаграмм."
        return "Флагманская открытая модель от Alibaba Cloud с сильными способностями к многоязычным рассуждениям и математике."

    # Семейство Llama
    if "llama" in name_lower:
        if is_code:
            return "Открытая базовая модель от Meta, дообученная для генерации, анализа и документирования программного кода."
        return "Ведущая открытая модель от Meta для широкого спектра задач обработки естественного языка и локального развертывания."

    # Семейство Mistral
    if any(k in name_lower for k in ("mistral", "mixtral", "codestral")):
        if is_code or "codestral" in name_lower:
            return "Специализированная европейская модель от Mistral AI для быстрого написания, автодополнения и рефакторинга кода."
        return "Высокопроизводительная модель от Mistral AI с открытыми весами для быстрого инференса и аналитических задач."

    # Другие узнаваемые модели
    if "mimo" in name_lower:
        return "Энергоэффективная открытая модель от Xiaomi с низким временем отклика и сбалансированным качеством рассуждений."

    if "grok" in name_lower:
        return "Высокопроизводительная языковая модель от xAI с глубокими логическими способностями и актуальным пониманием контекста."

    if "glm" in name_lower:
        return "Передовая двуязычная модель от Zhipu AI для комплексного языкового анализа и решения прикладных задач."

    if "phi" in name_lower:
        return "Компактная высокоинтеллектуальная SLM-модель от Microsoft, обученная на синтетических данных эталонного качества."

    if "minimax" in name_lower:
        return "Флагманская языковая модель от MiniMax с поддержкой сверхдлинного контекста и уверенным следованием сложным инструкциям."

    if "flux" in name_lower:
        return "Генеративная диффузионная модель нового поколения от Black Forest Labs для создания фотореалистичных изображений."

    if "midjourney" in name_lower:
        return "Ведущая нейросеть для художественной генерации изображений с высокой эстетикой, кинематографичным светом и детализацией."

    if "sora" in name_lower or "kling" in name_lower or "wan" in name_lower:
        ven = norm_orgs.get((detected_org or "").lower(), detected_org) or "AI-лаборатории"
        return f"Генеративная модель от {ven} для создания видео высокой четкости со стабильной физикой и динамикой движения."

    # Общий фоллбэк с учетом вендора и домена задачи
    v_prefix = f"Разработка {detected_org}" if detected_org else ("Открытая модель" if is_open else "Нейросетевая модель")
    if is_code:
        return f"{v_prefix}, оптимизированная для сложной веб-разработки, написания программного кода и дебаггинга."
    if is_agent:
        return f"{v_prefix}, предназначенная для автономных агентных сценариев, вызова инструментов и пошагового планирования."
    if is_vision:
        return f"{v_prefix}, ориентированная на мультимодальный анализ, распознавание документов и визуальную аналитику."
    if is_video:
        return f"{v_prefix}, разработанная для динамической генерации видео со стабильной физикой и анимацией."
    if is_image:
        return f"{v_prefix}, созданная для фотореалистичной генерации и стилизации изображений по текстовому описанию."
    if is_reasoning:
        return f"{v_prefix}, ориентированная на пошаговые логические рассуждения, математику и решение сложных задач."
    return f"{v_prefix} для глубоких аналитических рассуждений, работы со сложным контекстом и прикладных ИИ-задач."


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


def parse_browser_page(page, category: str = "") -> list[dict]:
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
                rating_num = clean_rating if isinstance(clean_rating, (int, float)) else 1000.0
                summary = generate_model_breakdown(
                    name=clean_name,
                    org="",
                    category=category,
                    rating=rating_num,
                    license_str="",
                    vote_count=0
                )
                parsed_data.append({
                    "name": clean_name,
                    "rating": clean_rating,
                    "organization": "",
                    "license": "",
                    "vote_count": 0,
                    "summary": summary,
                })
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
                        p = parse_browser_page(page, category=cat)
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
        first_row = rows[0]
        summary = next((r["summary"] for r in rows if r.get("summary")), "")
        org = first_row.get("organization") or ""
        lic = first_row.get("license") or ""
        votes = sum(int(r.get("vote_count", 0) or 0) for r in rows)

        if not summary:
            summary = generate_model_breakdown(
                name=name,
                org=org,
                category="Все категории",
                rating=chosen_rating,
                license_str=lic,
                vote_count=votes,
            )

        aggregated.append({
            "model_name": name,
            "rating": chosen_rating,
            "categories": cats,
            "category": f"{len(cats)} {format_cat_plural(len(cats))}",
            "organization": org,
            "license": lic,
            "vote_count": votes,
            "summary": summary,
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
