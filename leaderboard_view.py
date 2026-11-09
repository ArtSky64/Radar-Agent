import re
"""Подготовка данных лидерборда для frontend.py.

Чистая логика без Streamlit: так её можно покрыть тестами
(frontend.py выполняет код отрисовки прямо при импорте).
"""
import math
from collections import defaultdict

def get_model_url(name: str, org: str = "", license_str: str = "") -> str:
    """Возвращает официальную рабочую ссылку на модель, сервис вендора или репозиторий."""
    n_low = (name or "").lower()
    o_low = (org or "").lower()
    lic_low = (license_str or "").lower()
    is_open = bool(lic_low and lic_low not in ("proprietary", "commercial", "closed", "unknown", "none", ""))

    clean_name = re.sub(r"\s*\([^)]*\)", "", name or "")
    clean_name = re.sub(r"\s*\[[^\]]*\]", "", clean_name).strip()

    # Anthropic / Claude
    if "claude" in n_low or o_low == "anthropic":
        return "https://claude.ai"

    # Google / Gemini / Gemma
    if "gemma" in n_low:
        return "https://huggingface.co/google"
    if "gemini" in n_low or o_low == "google":
        return "https://gemini.google.com"

    # OpenAI
    if "sora" in n_low:
        return "https://sora.com"
    if any(k in n_low for k in ("gpt", "chatgpt", "o1", "o3", "dall-e")) or o_low == "openai":
        return "https://chatgpt.com"

    # DeepSeek
    if "deepseek" in n_low or o_low == "deepseek":
        return "https://huggingface.co/deepseek-ai" if is_open else "https://chat.deepseek.com"

    # Alibaba / Qwen / Wan
    if "qwen" in n_low or o_low == "alibaba":
        return "https://huggingface.co/Qwen"
    if "wan" in n_low or o_low == "wan":
        return "https://huggingface.co/Wan-AI"

    # Meta / Llama / Muse
    if "llama" in n_low:
        return "https://huggingface.co/meta-llama"
    if "muse" in n_low or o_low == "meta":
        return "https://ai.meta.com"

    # xAI / Grok
    if "grok" in n_low or o_low == "xai":
        return "https://x.ai"

    # Mistral AI
    if any(k in n_low for k in ("mistral", "mixtral", "codestral")) or o_low == "mistral":
        return "https://huggingface.co/mistralai" if is_open else "https://chat.mistral.ai"

    # Xiaomi / MiMo
    if "mimo" in n_low or o_low == "xiaomi":
        return "https://huggingface.co/Xiaomi"

    # Zhipu AI / GLM
    if "glm" in n_low or o_low in ("zai", "zhipu"):
        return "https://huggingface.co/THUDM"

    # Black Forest Labs / FLUX
    if "flux" in n_low or o_low in ("bfl", "black forest labs"):
        return "https://huggingface.co/black-forest-labs"

    # Stability AI
    if "stable diffusion" in n_low or "sdxl" in n_low or o_low in ("stability", "stability ai"):
        return "https://huggingface.co/stabilityai"

    # Midjourney
    if "midjourney" in n_low:
        return "https://www.midjourney.com"

    # Kuaishou / Kling
    if "kling" in n_low or o_low == "kling":
        return "https://klingai.com"

    # MiniMax
    if "minimax" in n_low or o_low == "minimax":
        return "https://huggingface.co/MiniMax"

    # ByteDance / Dreamina / Seedance
    if any(k in n_low for k in ("dreamina", "seedance")) or o_low == "bytedance":
        return "https://dreamina.capcut.com"

    # Moonshot AI / Kimi
    if "kimi" in n_low or o_low == "moonshot":
        return "https://kimi.moonshot.cn"

    # Microsoft / Phi
    if "phi" in n_low or o_low in ("microsoft", "microsoft-ai"):
        return "https://huggingface.co/microsoft"

    # Luma AI
    if "luma" in n_low or o_low == "luma-ai":
        return "https://lumalabs.ai"

    # Runway
    if "runway" in n_low or o_low == "runway":
        return "https://runwayml.com"

    # Baidu / ERNIE
    if "ernie" in n_low or o_low == "baidu":
        return "https://yiyan.baidu.com"

    # Recraft
    if "recraft" in n_low or o_low == "recraft":
        return "https://www.recraft.ai"

    # Ideogram
    if "ideogram" in n_low or o_low == "ideogram":
        return "https://ideogram.ai"

    # Krea
    if "krea" in n_low or o_low == "krea":
        return "https://www.krea.ai"

    # Perplexity
    if "perplexity" in n_low or o_low == "perplexity":
        return "https://www.perplexity.ai"

    # Pika
    if "pika" in n_low or o_low == "pika":
        return "https://pika.art"

    # Leonardo AI
    if "leonardo" in n_low or o_low == "leonardo-ai":
        return "https://leonardo.ai"

    # Tencent / Hunyuan
    if "hunyuan" in n_low or o_low == "tencent":
        return "https://hunyuan.tencent.com"

    # Shengshu / Vidu
    if "vidu" in n_low or o_low == "shengshu":
        return "https://www.vidu.studio"

    # Amazon Nova
    if "amazon" in n_low or "nova" in n_low or o_low == "amazon":
        return "https://aws.amazon.com/bedrock/nova/"

    # StepFun
    if "step" in n_low or o_low == "stepfun":
        return "https://www.stepfun.com"

    # Reve
    if "reve" in n_low or o_low == "reve":
        return "https://reve.art"

    # Pixverse
    if "pixverse" in n_low:
        return "https://pixverse.ai"

    # Lightricks / LTX
    if "ltx" in n_low:
        return "https://huggingface.co/Lightricks"

    # Fallbacks
    if "/" in clean_name:
        return f"https://huggingface.co/{clean_name}"
    if is_open:
        return f"https://huggingface.co/models?search={clean_name}"
    return f"https://www.google.com/search?q={clean_name}+AI+model"


ALL_CATEGORIES = "Все категории"


def _to_number(value) -> float | None:
    """Приводит рейтинг к float. Мусор (строка, None, NaN, inf) -> None.

    arena_scraper.parse() при ValueError оставляет рейтинг строкой, а SQLite
    с INTEGER-колонкой такую строку принимает без ошибок — поэтому во
    фронтенд может дойти не число.
    """
    if isinstance(value, bool):
        return None
    
    # Если пришла строка с процентами (вдруг спарсился winrate вместо elo)
    if isinstance(value, str):
        value = value.replace('%', '').strip()
        
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_latest_records(snapshots: list[dict]) -> list[dict]:
    """Плоский список записей: по каждой категории берётся ТОЛЬКО самый
    свежий снимок, в котором эта категория есть.
    """
    records: list[dict] = []
    seen_categories: set[str] = set()

    for snap in sorted(snapshots, key=lambda s: s.get("fetched_at") or "", reverse=True):
        fetched_at = snap.get("fetched_at")
        for category, models in (snap.get("categories") or {}).items():
            if category in seen_categories:
                continue
            seen_categories.add(category)
            for m in models:
                name = m.get("name")
                rating = _to_number(m.get("rating"))
                if not name or rating is None:
                    continue

                org = m.get("organization") or ""
                lic = m.get("license") or ""
                votes = int(m.get("vote_count", 0) or 0)
                summary = (m.get("summary") or "").strip()

                if not summary or summary.startswith("•"):
                    try:
                        from arena_scraper import generate_model_breakdown
                        summary = generate_model_breakdown(
                            name=name,
                            org=org,
                            category=category,
                            rating=rating,
                            license_str=lic,
                            vote_count=votes,
                        )
                    except Exception:
                        summary = f"Модель {name} от {org or 'ведущей AI-лаборатории'} для аналитики и решения профильных задач."

                records.append({
                    "category": category,
                    "model_name": name,
                    "rating": rating,
                    "fetched_at": fetched_at,
                    "organization": org,
                    "license": lic,
                    "vote_count": votes,
                    "summary": summary,
                    "model_url": get_model_url(name, org, lic),
                })
    return records


def aggregate_all_categories(records: list[dict], method: str = "avg") -> list[dict]:
    """Режим «Все категории»: одна строка на модель.
    method='avg': рейтинг — среднее по категориям, где модель присутствует.
    method='max': рейтинг — максимум по категориям.
    """
    by_model = defaultdict(list)
    for r in records:
        by_model[r["model_name"]].append(r)

    result = []
    for name, rows in by_model.items():
        if method == "max":
            best_row = max(rows, key=lambda x: x["rating"])
            rating = best_row["rating"]
            cat_list = ", ".join(sorted(r["category"].upper() for r in rows))
            cat_label = f"МАКС: {best_row['category'].upper()} ({len(rows)} {category_count_label(len(rows)).split()[1]}: {cat_list})"
        else:
            rating = sum(r["rating"] for r in rows) / len(rows)
            cat_label = category_count_label(len(rows))

        first_row = rows[0]
        summary = next((r["summary"] for r in rows if r.get("summary") and not r.get("summary").strip().startswith("•")), "").strip()
        org = first_row.get("organization") or ""
        lic = first_row.get("license") or ""
        votes = sum(int(r.get("vote_count", 0) or 0) for r in rows)

        if not summary or summary.startswith("•"):
            try:
                from arena_scraper import generate_model_breakdown
                summary = generate_model_breakdown(
                    name=name,
                    org=org,
                    category=ALL_CATEGORIES,
                    rating=rating,
                    license_str=lic,
                    vote_count=votes,
                )
            except Exception:
                summary = f"Модель {name} от {org or 'ведущей AI-лаборатории'} для аналитики и решения профильных задач."

        result.append({
            "model_name": name,
            "rating": rating,
            "categories": sorted(r["category"] for r in rows),
            "category": cat_label,
            "organization": org,
            "license": lic,
            "vote_count": votes,
            "summary": summary,
            "model_url": get_model_url(name, org, lic),
        })

    return sorted(result, key=lambda x: x["rating"], reverse=True)


def category_count_label(n: int) -> str:
    """Возвращает строку с правильным склонением слова «категория»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} категория"
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return f"{n} категории"
    else:
        return f"{n} категорий"


def format_rating(rating: float) -> str:
    """Форматирует число рейтинга: целое без нулей на конце, иначе 1 знак после запятой."""
    if rating.is_integer():
        return str(int(rating))
    return f"{rating:.1f}"