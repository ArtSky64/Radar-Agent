# для запуска: uvicorn app:app --reload (бэкенд), затем python -m streamlit run frontend.py (фронтенд)

import os
from html import escape
import requests
import streamlit as st
from datetime import datetime, timedelta, timezone

# Московский часовой пояс (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))


def format_timestamp_ru(ts_str: str | None) -> str:
    """Преобразует ISO строку даты/времени в понятный формат по МСК (UTC+3)."""
    if not ts_str:
        return "нет данных"
    try:
        ts = str(ts_str).strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc).astimezone(MSK_TZ)
        else:
            dt = dt.astimezone(MSK_TZ)

        months = [
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ]
        return f"{dt.day} {months[dt.month - 1]} {dt.year} г., {dt.strftime('%H:%M')} (МСК)"
    except Exception:
        return str(ts_str)



from leaderboard_view import (
    ALL_CATEGORIES,
    aggregate_all_categories,
    build_latest_records,
    category_count_label,
    format_rating,
)


# Устанавливаем широкую компоновку и принудительно открываем сайдбар
st.set_page_config(layout="wide", initial_sidebar_state="expanded")

# --- ПОЛНОСТЬЮ ПЕРЕПИСАННЫЙ CSS ---
custom_css = """
<style>
    /* 1. Глобальные переменные: жесткое удаление дефолтных серых рамок Streamlit */
    :root {
        --border-color: #2D1B4E !important;
        --secondary-background-color: #0A0A0F !important;
        --primary-color: #8B5CF6 !important;
    }

    /* 2. Глобальный фон */
    [data-testid="stAppViewContainer"], 
    .stApp { 
        background-color: #0A0A0F !important; 
    }

    /* 3. Жесткая фиксация сайдбара и удаление серой правой границы */
    [data-testid="stSidebar"] { 
        background-color: #0A0A0F !important; 
        border-right: 1px solid #2D1B4E !important; 
        width: 260px !important;
        min-width: 260px !important;
        max-width: 260px !important;
        transform: none !important;
        visibility: visible !important;
        position: relative !important;
    }

    /* 4. ПОЛНОЕ УДАЛЕНИЕ КНОПОК СКРЫТИЯ (для всех версий Streamlit) */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarNav"] button,
    section[data-testid="stSidebar"] button[kind="icon"] {
        display: none !important;
        opacity: 0 !important;
        pointer-events: none !important;
        width: 0 !important;
        height: 0 !important;
        position: absolute !important;
        z-index: -100 !important;
    }

    /* 5. Скрытие кнопки Deploy и стандартного меню Streamlit */
    #MainMenu, header, [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
        display: none !important;
    }

    /* 6. Компенсация отступа сверху после удаления хедера */
    .block-container { 
        padding-top: 2rem !important; 
        max-width: 98% !important; 
    }

    /* 7. Типографика и удаление любых серых линий-разделителей */
    p, span, label, li, .stMarkdown, div[data-baseweb="select"] { color: #A1A1AA !important; font-family: 'Inter', sans-serif; }
    h1, h2, h3, h4, h5, h6, strong { color: #FFFFFF !important; font-weight: 600 !important; }

    hr { 
        border-color: #2D1B4E !important; 
        border-bottom: 1px solid #2D1B4E !important; 
        background-color: transparent !important;
    }

    /* 8. Инпуты и селекты (очистка серых рамок) */
    div[data-baseweb="select"] > div, 
    div[data-baseweb="input"] > div,
    div[data-baseweb="number-input"] > div,
    div[data-baseweb="multiselect"] > div {
        background-color: #12121A !important;
        border: 1px solid #2D1B4E !important;
        border-radius: 8px !important;
        color: #FFFFFF !important;
    }
    div[data-baseweb="select"] > div:hover, 
    div[data-baseweb="input"] > div:hover,
    div[data-baseweb="multiselect"] > div:hover {
        border-color: #8B5CF6 !important;
    }

    /* Теги в multiselect */
    span[data-baseweb="tag"] {
        background-color: #1E1B4B !important;
        color: #C084FC !important;
        border: 1px solid #3B0764 !important;
    }

    /* 9. Карточки контента */
    .custom-card {
        background: linear-gradient(
            180deg,
            #1A0E2B 0%,
            #160A25 100%
        ) !important;
        border: 1px solid #6D28D9 !important;
        border-radius: 18px !important;
        padding: 24px 28px !important;
        margin-bottom: 20px !important;
        box-shadow:
            inset 0 1px 0 rgba(255,255,255,.03),
            0 8px 22px rgba(124,58,237,.10);
        transition: all .25s ease;
    }
    .custom-card:hover {
        transform: translateY(-3px);
        border-color: #A855F7 !important;
        background: linear-gradient(
            180deg,
            #211036 0%,
            #190C2A 100%
        ) !important;
        box-shadow: 0 15px 40px rgba(124,58,237,.25);
    }

    /* Стили для тегов в карточках статей */
    .article-tags { margin-bottom: 12px; display: flex; gap: 6px; flex-wrap: wrap; }
    .article-tag { 
        background-color: #1E1B4B; 
        color: #C084FC; 
        padding: 4px 10px; 
        border-radius: 6px; 
        font-size: 0.75rem; 
        border: 1px solid #3B0764; 
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)


# --- БЭКЕНД ИНТЕГРАЦИЯ ---
# В докере сервисы общаются по именам сервисов (api), а не через localhost —
# localhost внутри контейнера frontend это сам контейнер frontend, а не api.
API_URL = os.getenv("API_URL", "http://localhost:8000")


def fetch_data(endpoint):
    try:
        res = requests.get(f"{API_URL}/{endpoint}", timeout=5)
        return res.json() if res.status_code == 200 else {"status": "error", "data": []}
    except:
        return {"status": "connect_error", "data": []}



leaderboard_res = fetch_data("leaderboard")
trending_res = fetch_data("trending/models")
articles_res = fetch_data("articles")
analysis_res = fetch_data("leaderboard/analysis")
github_trending_res = fetch_data("trending/github")

github_trending_list = github_trending_res.get("data", []) if github_trending_res.get("status") == "success" else []
github_last_fetched_at = github_trending_res.get("last_fetched_at")
if not github_trending_list:
    try:
        from database import get_github_trending, get_github_trending_last_fetched_at
        github_trending_list = get_github_trending()
        github_last_fetched_at = get_github_trending_last_fetched_at()
    except Exception:
        pass
elif not github_last_fetched_at and github_trending_list:
    github_last_fetched_at = github_trending_list[0].get("fetched_at")


analysis_list = analysis_res.get("data", []) if analysis_res.get("status") == "success" else []
latest_analysis = analysis_list[0] if analysis_list else None


# Парсинг реальных данных из бэкенда
leaderboard_records = []
unique_models = set()
unique_categories = set()

if leaderboard_res.get("status") == "success" and leaderboard_res.get("data"):
    leaderboard_records = build_latest_records(leaderboard_res["data"])
    unique_categories = {r["category"] for r in leaderboard_records}
    unique_models = {r["model_name"] for r in leaderboard_records}

if not leaderboard_records:
    try:
        from database import get_all_leaderboard_snapshots
        snaps = get_all_leaderboard_snapshots()
        if snaps:
            leaderboard_records = build_latest_records(snaps)
            unique_categories = {r["category"] for r in leaderboard_records}
            unique_models = {r["model_name"] for r in leaderboard_records}
    except Exception:
        pass

leaderboard_last_fetched_at = leaderboard_records[0].get("fetched_at") if leaderboard_records else None

trend_list = trending_res.get("data", []) if trending_res.get("status") == "success" else []
hf_last_fetched_at = trending_res.get("last_fetched_at")
if not trend_list:
    try:
        from database import get_trending_models, get_hf_trending_last_fetched_at
        trend_list = get_trending_models()
        hf_last_fetched_at = get_hf_trending_last_fetched_at()
    except Exception:
        pass
elif not hf_last_fetched_at and trend_list:
    hf_last_fetched_at = trend_list[0].get("fetched_at")

# Списки русских и глобальных моделей
ru_trend_list = [m for m in trend_list if m.get("rank_ru", 0) > 0 or "ru" in (m.get("variant") or "")]
ru_trend_list.sort(key=lambda x: (x.get("rank_ru") if x.get("rank_ru", 0) > 0 else 9999, -x.get("downloads", 0)))

global_trend_list = [m for m in trend_list if m.get("rank_global", 0) > 0]
if not global_trend_list:
    global_trend_list = list(trend_list)
global_trend_list.sort(key=lambda x: (x.get("rank_global") if x.get("rank_global", 0) > 0 else 9999, -x.get("downloads", 0)))

article_list = articles_res.get("data", []) if articles_res.get("status") == "success" else []

# Теги берём из БД как есть (раньше подставлялись выдуманные LLM/RLHF/...).
for art in article_list:
    if not isinstance(art.get("tags"), list):
        art["tags"] = []
available_tags = sorted({t for art in article_list for t in art["tags"] if isinstance(t, str) and t})

# --- НАВИГАЦИЯ (СВЕРХУ) ---

# Меню вкладок
page = st.radio(
    "Разделы",
    ["Лидерборд моделей", "Трендовые модели HF", "Трендовые модели HF с поддержкой русского языка", "Papers (Статьи)", "Датасеты", "Репозитории"],
    horizontal=True, label_visibility="collapsed",
)
st.divider()

# Вкладки, разбитые из бывшей "Базы статей" по source_type — используются
# и для фильтрации списка article_list, и для сносок-пояснений под заголовком.
_CONTENT_TABS = {
    "Papers (Статьи)": {
        "source_type": "статья",
        "hint": "Научные статьи и препринты из Hugging Face Papers и Papers with Code (PwC) — склеены по arxiv_id, ранжированы по upvotes, саммари и теги сформированы ИИ.",
    },
    "Датасеты": {
        "source_type": "датасет",
        "hint": "Новые датасеты с Hugging Face и Kaggle — отобраны и переведены ИИ-агентом по описанию датасета.",
    },
    "Репозитории": {
        "source_type": "репозиторий",
        "hint": "Свежие GitHub-репозитории по тематике ML/AI, найденные за последние дни.",
    },
}

# --- СЛЕВА: ФИЛЬТРЫ ДЛЯ ТЕКУЩЕЙ ВКЛАДКИ ---
with st.sidebar:
    st.markdown("<h3 style='margin-bottom: 1.5rem; color: #FFFFFF;'>Панель</h3>", unsafe_allow_html=True)

    if page == "Лидерборд моделей":
        st.markdown("<h5 style='color:#FFFFFF; margin-bottom:10px;'>Фильтры лидерборда</h5>", unsafe_allow_html=True)
        cats = sorted(unique_categories)
        selected_cat = st.selectbox("Категория", [ALL_CATEGORIES] + cats)

        agg_method = "avg"
        if selected_cat == "Все категории":
            agg_choice = st.radio(
                "Метод агрегации",
                ["Средний рейтинг (рекомендуется)", "Максимальный рейтинг"],
                help="Вариант А (рекомендуется): средний балл Elo по всем категориям модели. Вариант B: максимальный балл в лучшей нише модели.",
            )
            agg_method = "avg" if "Средний" in agg_choice else "max"

        if leaderboard_last_fetched_at:
            st.markdown(
                f"<div style='margin-top:14px; padding:10px 12px; background:#12121A; border:1px solid #2D1B4E; border-radius:8px; font-size:0.8rem; color:#A1A1AA;'>"
                f"🕒 <strong>Последний сбор лидерборда:</strong><br>"
                f"<span style='color:#34D399; font-weight:600;'>{format_timestamp_ru(leaderboard_last_fetched_at)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    elif page in ("Трендовые модели HF", "Трендовые модели HF с поддержкой русского языка"):
        is_ru_page = (page == "Трендовые модели HF с поддержкой русского языка")
        title_prefix = "Тренды HF (RU)" if is_ru_page else "Мировые тренды HF"
        st.markdown(f"<h5 style='color:#FFFFFF; margin-bottom:10px;'>Фильтры: {title_prefix}</h5>", unsafe_allow_html=True)

        try:
            import config
            hf_dir_keys = list(config.HF_DIRECTIONS.keys())
            hf_task_keys = list(config.HF_TASK_TYPES.keys())
        except Exception:
            hf_dir_keys = []
            hf_task_keys = []

        search_hf = st.text_input("Поиск по названию модели", key="search_hf_model")

        selected_hf_dirs = st.multiselect(
            "Направление (0-4)",
            hf_dir_keys,
            placeholder="Все направления...",
            help="Категории: health_ai, cv, audio, nlp_llm, generative_ai, classical_ml, robotics",
            key="hf_dirs"
        )

        selected_hf_tasks = st.multiselect(
            "Тип задачи (0-3)",
            hf_task_keys,
            placeholder="Все типы задач...",
            help="Задачи: classification, regression, clustering, detection_tracking, segmentation, generation, recognition, reinforcement_learning, anomaly_detection",
            key="hf_tasks"
        )

        sort_options = (
            ["По RU-рейтингу", "По мировому рейтингу", "По скачиваниям", "По лайкам"]
            if is_ru_page
            else ["По мировому рейтингу", "По RU-рейтингу", "По скачиваниям", "По лайкам"]
        )
        sort_hf = st.selectbox("Сортировка", sort_options, key="sort_hf_model")

        if hf_last_fetched_at:
            st.markdown(
                f"<div style='margin-top:14px; padding:10px 12px; background:#12121A; border:1px solid #2D1B4E; border-radius:8px; font-size:0.8rem; color:#A1A1AA;'>"
                f"🕒 <strong>Последний сбор трендов:</strong><br>"
                f"<span style='color:#34D399; font-weight:600;'>{format_timestamp_ru(hf_last_fetched_at)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    elif page in _CONTENT_TABS:
        st.markdown(f"<h5 style='color:#FFFFFF; margin-bottom:10px;'>Фильтры: {page}</h5>", unsafe_allow_html=True)
        search_art = st.text_input("Ключевые слова")
        selected_tags = st.multiselect("Поиск по тегам", available_tags, placeholder="Выберите теги...")

        # Язык сейчас заполняется только у HF-датасетов, поэтому фильтр
        # показываем только на вкладке "Датасеты".
        selected_languages = []
        selected_has_spaces = "Все"
        selected_ds_source = "Все источники"
        sort_ds = "По российскому рейтингу (RU)"
        if page == "Датасеты":
            selected_ds_source = st.selectbox(
                "Источник датасета",
                ["Все источники", "Hugging Face", "Kaggle"],
                key="ds_source"
            )
            sort_ds = st.selectbox(
                "Сортировка датасетов",
                [
                    "По российскому рейтингу (RU)",
                    "По мировому рейтингу (Global)",
                    "По лайкам / голосам",
                    "Сначала новые"
                ],
                key="ds_sort"
            )
            available_languages = sorted({
                lang.strip()
                for a in article_list
                if a.get("source_type") == "датасет"
                for lang in (a.get("language") or "").split(",")
                if lang.strip()
            })
            selected_has_spaces = st.selectbox(
                "Наличие Spaces (демо)",
                ["Все", "Только со Spaces (True)", "Без Spaces (False)"],
                key="ds_has_spaces"
            )
            if available_languages:
                selected_languages = st.multiselect(
                    "Язык датасета", available_languages, placeholder="Все языки..."
                )

        # Фильтры для Papers (Статьи)
        selected_topics = []
        selected_paper_source = "Все источники"
        selected_has_code = "Все"
        sort_paper = "По трендовости (Upvotes 🔥)"
        if page == "Papers (Статьи)":
            selected_paper_source = st.selectbox(
                "Источник статей",
                ["Все источники", "Hugging Face Papers", "Papers with Code"],
            )
            selected_has_code = st.selectbox(
                "Наличие кода",
                ["Все", "Только с кодом (True)", "Без кода (False)"],
            )
            sort_paper = st.selectbox(
                "Сортировка статей",
                ["По трендовости (Upvotes 🔥)", "Сначала новые (New 🕒)"],
            )
            available_topics = sorted({
                a.get("topic_tag", "").strip()
                for a in article_list
                if a.get("source_type") == "статья" and a.get("topic_tag")
            })
            if available_topics:
                selected_topics = st.multiselect(
                    "Тематический срез", available_topics, placeholder="Все темы..."
                )

        # Фильтры для Репозиториев (ТЗ созвона)
        selected_directions = []
        selected_task_types = []
        selected_repo_status = "Все"

        if page == "Репозитории":
            try:
                import config
                all_dir_keys = list(config.GITHUB_DIRECTIONS.keys())
                all_task_keys = list(config.GITHUB_TASK_TYPES.keys())
            except Exception:
                all_dir_keys = []
                all_task_keys = []

            selected_directions = st.multiselect(
                "Направление (0-4)",
                all_dir_keys,
                placeholder="Все направления...",
                help="Фиксированный список направлений"
            )
            selected_task_types = st.multiselect(
                "Тип задачи (0-3)",
                all_task_keys,
                placeholder="Все типы задач...",
                help="Фиксированный список типов задач"
            )
            selected_repo_status = st.selectbox(
                "Статус",
                ["Все", "Новые в тренде", "Уже были в базе (в тренде)"]
            )
            if github_last_fetched_at:
                st.markdown(
                    f"<div style='margin-top:14px; padding:10px 12px; background:#12121A; border:1px solid #2D1B4E; border-radius:8px; font-size:0.8rem; color:#A1A1AA;'>"
                    f"🕒 <strong>Последний сбор:</strong><br>"
                    f"<span style='color:#34D399; font-weight:600;'>{format_timestamp_ru(github_last_fetched_at)}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )



def render_hf_model_card(m: dict, is_ru_tab: bool = False):
    model_name = m.get("model_name") or m.get("name", "Unknown")
    model_url = m.get("source_url") or m.get("url") or f"https://huggingface.co/{model_name}"

    rank_ru = m.get("rank_ru", 0)
    rank_global = m.get("rank_global", 0)

    rank_badges = []
    if is_ru_tab:
        if rank_ru > 0:
            rank_badges.append(
                f'<span style="font-size:0.75rem; font-weight:700; color:#34D399; background:#064E3B; border:1px solid #059669; border-radius:6px; padding:2px 8px; margin-right:6px;">🏆 RU ТОП #{rank_ru}</span>'
            )
        if rank_global > 0:
            rank_badges.append(
                f'<span style="font-size:0.75rem; font-weight:700; color:#A78BFA; background:#2E1065; border:1px solid #7C3AED; border-radius:6px; padding:2px 8px; margin-right:6px;">🌍 Мировой #{rank_global}</span>'
            )
        else:
            rank_badges.append(
                f'<span style="font-size:0.75rem; font-weight:600; color:#71717A; background:#18181B; border:1px solid #27272A; border-radius:6px; padding:2px 8px; margin-right:6px;">🌍 Вне мирового топ-50</span>'
            )
    else:
        if rank_global > 0:
            rank_badges.append(
                f'<span style="font-size:0.75rem; font-weight:700; color:#A78BFA; background:#2E1065; border:1px solid #7C3AED; border-radius:6px; padding:2px 8px; margin-right:6px;">🌍 МИРОВОЙ ТОП #{rank_global}</span>'
            )
        if rank_ru > 0:
            rank_badges.append(
                f'<span style="font-size:0.75rem; font-weight:700; color:#34D399; background:#064E3B; border:1px solid #059669; border-radius:6px; padding:2px 8px; margin-right:6px;">🇷🇺 RU #{rank_ru}</span>'
            )

    params = (m.get("parameters") or "").strip()
    param_badge = (
        f'<span style="font-size:0.75rem; font-weight:700; color:#FBBF24; background:#451A03; border:1px solid #D97706; border-radius:6px; padding:2px 8px; margin-right:6px;">⚡ {params}</span>'
        if params else ""
    )

    ptype = (m.get("pipeline_tag") or "").strip()
    ptype_badge = (
        f'<span style="font-size:0.75rem; font-weight:700; color:#38BDF8; background:#0F172A; border:1px solid #0284C7; border-radius:6px; padding:2px 8px; margin-right:6px;">🏷️ {ptype}</span>'
        if ptype else ""
    )

    dirs_badges = "".join([
        f'<span style="font-size:0.7rem; font-weight:600; color:#38BDF8; background:#0F172A; border:1px solid #0284C7; border-radius:6px; padding:2px 8px; margin-right:4px;">🧭 {d}</span>'
        for d in m.get("directions", [])
    ])

    tasks_badges = "".join([
        f'<span style="font-size:0.7rem; font-weight:600; color:#C084FC; background:#2E1065; border:1px solid #7E22CE; border-radius:6px; padding:2px 8px; margin-right:4px;">🎯 {t}</span>'
        for t in m.get("task_types", [])
    ])

    tags_html = "".join([f'<span class="article-tag">{t}</span>' for t in m.get("tags", [])[:5]])
    all_badges_html = f'<div class="article-tags" style="margin-bottom:8px;">{"".join(rank_badges)}{param_badge}{ptype_badge}{dirs_badges}{tasks_badges}{tags_html}</div>'

    downloads = m.get("downloads", 0)
    likes = m.get("likes", 0)
    score = m.get("trending_score", 0)
    score_str = f' │ <span style="color:#A1A1AA;">📈 Трендинг-балл: {round(float(score), 1)}</span>' if score else ""
    metrics_html = f'<div style="font-size:0.85rem; color:#A78BFA; margin-top:8px;"><span>⬇ Скачивания: {downloads:,}</span> │ <span>♡ Лайки: {likes:,}</span>{score_str}</div>'

    summary = m.get("summary") or ""
    summary_html = f'<p style="font-size:0.9rem; color:#D4D4D8; margin:8px 0; line-height:1.5;">{summary}</p>' if summary else ""
    link_html = f'<div style="margin-top:8px;"><a href="{model_url}" target="_blank" style="font-size:0.85rem; color:#A78BFA; text-decoration:none;">Открыть на Hugging Face →</a></div>'

    st.markdown(
        f'<div class="custom-card">'
        f'{all_badges_html}'
        f'<h4 style="margin:0;"><a href="{model_url}" target="_blank" style="color:#FFFFFF; text-decoration:none;">{model_name}</a></h4>'
        f'{summary_html}'
        f'{metrics_html}'
        f'{link_html}'
        f'</div>',
        unsafe_allow_html=True
    )


# --- ЛОГИКА ОТРИСОВКИ СТРАНИЦ ---

if page == "Лидерборд моделей":
    st.markdown("<h1>Лидерборд моделей</h1>", unsafe_allow_html=True)

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("🔄 Обновить лидерборд Arena", help="Запустить обновление лидерборда LMSYS Chatbot Arena"):
            try:
                res = requests.post(f"{API_URL}/scrape", timeout=3)
                st.success("Обновление лидерборда запущено в фоне!")
            except Exception:
                try:
                    import arena_scraper
                    with st.spinner("Сбор данных лидерборда Arena..."):
                        data = arena_scraper.collect_all_categories(arena_scraper.CATEGORY_URLS)
                        arena_scraper.save_to_db(data)
                    st.success("Лидерборд Arena успешно обновлен!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка обновления: {e}")

    with col_info:
        if leaderboard_last_fetched_at:
            formatted_dt = format_timestamp_ru(leaderboard_last_fetched_at)
            st.markdown(
                f"<div style='display:flex; align-items:center; height:100%; padding-top:4px; font-size:0.95rem; color:#E4E4E7;'>"
                f"🕒 <span style='color:#A1A1AA; margin-right:6px;'>Последний сбор лидерборда:</span>"
                f"<span style='color:#34D399; font-weight:600; background:#064E3B; padding:3px 10px; border-radius:6px; border:1px solid #059669;'>"
                f"{formatted_dt}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    with st.expander("Как рассчитывается рейтинг Elo?"):
        st.write(
            "Рейтинг Elo вычисляется на основе результатов попарных «слепых» тестирований. Пользователи или автоматические бенчмарки оценивают ответы двух анонимных моделей на один и тот же промпт. Если модель побеждает, её рейтинг повышается, а у проигравшей — снижается. Величина изменения рейтинга зависит от разницы их баллов до матча: победа над сильным конкурентом (с высоким Elo) приносит значительно больше баллов, чем победа над слабым.")

    # Вывод ИИ-анализа лидерборда
    analysis_text = latest_analysis.get("analysis_text") if latest_analysis else None
    if not analysis_text:
        analysis_text = "Анализ формируется ИИ-агентом после сбора данных лидерборда. Нажмите кнопку «Обновить лидерборд Arena» для запуска сбора и анализа."

    with st.expander("📊 Анализ трендов лидерборда (ИИ)", expanded=True):
        st.markdown(
            f"<div style='font-size:0.92rem; color:#E4E4E7; white-space:pre-wrap; line-height:1.6;'>"
            f"{analysis_text}"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True)

    is_aggregate = selected_cat == ALL_CATEGORIES

    if is_aggregate:
        filtered = aggregate_all_categories(leaderboard_records, method=agg_method)
    else:
        filtered = sorted(
            (r for r in leaderboard_records if r["category"] == selected_cat),
            key=lambda x: x["rating"],
            reverse=True,
        )

    if filtered:
        for idx, rec in enumerate(filtered):
            raw_name = str(rec["model_name"]).strip()
            name = escape(raw_name)
            cats_to_show = rec.get("categories", [rec.get("category", "")]) if is_aggregate else [selected_cat]

            # Бейджи категорий (в виде аккуратных тегов)
            cat_badges = [
                f'<span class="article-tag" style="background:#1E1B4B; color:#C084FC; border:1px solid #3B0764; font-size:0.75rem; padding:3px 8px;">🏷️ {escape(c.upper())}</span>'
                for c in cats_to_show if c and c != ALL_CATEGORIES
            ]

            all_tags_html = (
                f'<div class="article-tags" style="margin-bottom:8px; display:flex; gap:6px; flex-wrap:wrap;">'
                f'{"".join(cat_badges)}'
                f'</div>'
            ) if cat_badges else ""

            st.markdown(
                f'<div class="custom-card">'
                f'{all_tags_html}'
                f'<div style="display:flex; justify-content:space-between; align-items:center;">'
                f'<div>'
                f'<strong style="font-size:1.15rem; color:#FFFFFF;">#{idx + 1} {name}</strong>'
                f'</div>'
                f'<div style="font-size:1.25rem; font-weight:700; color:#A78BFA;">{format_rating(rec["rating"])} <span style="font-size:0.85rem; color:#8B5CF6;">Elo</span></div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.warning(f"В категории «{selected_cat}» пока нет записей.")


elif page == "Трендовые модели HF":
    st.markdown("<h1>🌍 Мировые тренды Hugging Face</h1>", unsafe_allow_html=True)
    st.caption("Актуальный мировой рейтинг трендовых моделей с huggingface.co/models?sort=trending")

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("🔄 Обновить тренды HF", help="Запустить параллельный сбор мировых и RU трендов Hugging Face"):
            try:
                res = requests.post(f"{API_URL}/trending/refresh", timeout=3)
                st.success("Сбор трендов HF запущен в фоне!")
            except Exception:
                try:
                    from mcp_fetcher_hf_trending import fetch_trending_models
                    with st.spinner("Сбор трендовых моделей Hugging Face..."):
                        fetch_trending_models(limit=30)
                    st.success("Тренды HF успешно собраны!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка сбора: {e}")

    with col_info:
        if hf_last_fetched_at:
            formatted_dt = format_timestamp_ru(hf_last_fetched_at)
            st.markdown(
                f"<div style='display:flex; align-items:center; height:100%; padding-top:4px; font-size:0.95rem; color:#E4E4E7;'>"
                f"🕒 <span style='color:#A1A1AA; margin-right:6px;'>Последний сбор списка:</span>"
                f"<span style='color:#34D399; font-weight:600; background:#064E3B; padding:3px 10px; border-radius:6px; border:1px solid #059669;'>"
                f"{formatted_dt}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='display:flex; align-items:center; height:100%; padding-top:6px; font-size:0.9rem; color:#A1A1AA;'>"
                "🕒 <em>Данные трендов HF еще не собирались</em>"
                "</div>",
                unsafe_allow_html=True,
            )

    models = list(global_trend_list)
    if search_hf:
        models = [m for m in models if search_hf.lower() in (m.get('model_name') or m.get('name', '')).lower() or search_hf.lower() in (m.get('summary') or '').lower()]

    if selected_hf_dirs:
        models = [m for m in models if any(d in selected_hf_dirs for d in m.get("directions", []))]

    if selected_hf_tasks:
        models = [m for m in models if any(t in selected_hf_tasks for t in m.get("task_types", []))]

    if sort_hf == "По мировому рейтингу":
        models.sort(key=lambda x: (x.get("rank_global") if x.get("rank_global", 0) > 0 else 9999, -x.get("downloads", 0)))
    elif sort_hf == "По RU-рейтингу":
        models.sort(key=lambda x: (x.get("rank_ru") if x.get("rank_ru", 0) > 0 else 9999, -x.get("downloads", 0)))
    elif sort_hf == "По скачиваниям":
        models.sort(key=lambda x: x.get("downloads", 0), reverse=True)
    elif sort_hf == "По лайкам":
        models.sort(key=lambda x: x.get("likes", 0), reverse=True)

    if models:
        for m in models:
            render_hf_model_card(m, is_ru_tab=False)
    else:
        st.info("Нет моделей по выбранным фильтрам.")


elif page == "Трендовые модели HF с поддержкой русского языка":
    st.markdown("<h1>🇷🇺 Трендовые модели Hugging Face с поддержкой русского языка</h1>", unsafe_allow_html=True)
    st.info("Объединённый рейтинг моделей по ссылкам huggingface.co/models?language=ru&sort=trending и huggingface.co/models?language=rus&sort=trending с дедупликацией и сквозным рейтингом.")

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("🔄 Обновить тренды HF", key="refresh_hf_ru", help="Запустить сбор моделей Hugging Face"):
            try:
                res = requests.post(f"{API_URL}/trending/refresh", timeout=3)
                st.success("Сбор трендов HF запущен в фоне!")
            except Exception:
                try:
                    from mcp_fetcher_hf_trending import fetch_trending_models
                    with st.spinner("Сбор трендовых моделей Hugging Face..."):
                        fetch_trending_models(limit=30)
                    st.success("Тренды HF успешно собраны!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка сбора: {e}")

    with col_info:
        if hf_last_fetched_at:
            formatted_dt = format_timestamp_ru(hf_last_fetched_at)
            st.markdown(
                f"<div style='display:flex; align-items:center; height:100%; padding-top:4px; font-size:0.95rem; color:#E4E4E7;'>"
                f"🕒 <span style='color:#A1A1AA; margin-right:6px;'>Последний сбор списка:</span>"
                f"<span style='color:#34D399; font-weight:600; background:#064E3B; padding:3px 10px; border-radius:6px; border:1px solid #059669;'>"
                f"{formatted_dt}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='display:flex; align-items:center; height:100%; padding-top:6px; font-size:0.9rem; color:#A1A1AA;'>"
                "🕒 <em>Данные трендов HF еще не собирались</em>"
                "</div>",
                unsafe_allow_html=True,
            )

    models = list(ru_trend_list)
    if search_hf:
        models = [m for m in models if search_hf.lower() in (m.get('model_name') or m.get('name', '')).lower() or search_hf.lower() in (m.get('summary') or '').lower()]

    if selected_hf_dirs:
        models = [m for m in models if any(d in selected_hf_dirs for d in m.get("directions", []))]

    if selected_hf_tasks:
        models = [m for m in models if any(t in selected_hf_tasks for t in m.get("task_types", []))]

    if sort_hf == "По RU-рейтингу":
        models.sort(key=lambda x: (x.get("rank_ru") if x.get("rank_ru", 0) > 0 else 9999, -x.get("downloads", 0)))
    elif sort_hf == "По мировому рейтингу":
        models.sort(key=lambda x: (x.get("rank_global") if x.get("rank_global", 0) > 0 else 9999, -x.get("downloads", 0)))
    elif sort_hf == "По скачиваниям":
        models.sort(key=lambda x: x.get("downloads", 0), reverse=True)
    elif sort_hf == "По лайкам":
        models.sort(key=lambda x: x.get("likes", 0), reverse=True)

    if models:
        for m in models:
            render_hf_model_card(m, is_ru_tab=True)
    else:
        st.info("Нет русскоязычных моделей по выбранным фильтрам.")


elif page in _CONTENT_TABS:
    tab_info = _CONTENT_TABS[page]
    st.markdown(f"<h1>{page}</h1>", unsafe_allow_html=True)
    st.caption(tab_info["hint"])

    if page == "Репозитории":
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            if st.button("🔄 Обновить тренды GitHub", help="Запустить сбор актуальных 30 репозиториев (weekly + monthly)"):
                try:
                    res = requests.post(f"{API_URL}/trending/github/refresh", timeout=3)
                    st.success("Сбор трендов запущен в фоне!")
                except Exception:
                    try:
                        from github_fetcher import run_github_trending_pipeline
                        with st.spinner("Сбор трендов GitHub (weekly + monthly)..."):
                            run_github_trending_pipeline(limit=30)
                        st.success("Тренды успешно собраны!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка сбора: {e}")

        with col_info:
            if github_last_fetched_at:
                formatted_dt = format_timestamp_ru(github_last_fetched_at)
                st.markdown(
                    f"<div style='display:flex; align-items:center; height:100%; padding-top:4px; font-size:0.95rem; color:#E4E4E7;'>"
                    f"🕒 <span style='color:#A1A1AA; margin-right:6px;'>Последний сбор списка:</span>"
                    f"<span style='color:#34D399; font-weight:600; background:#064E3B; padding:3px 10px; border-radius:6px; border:1px solid #059669;'>"
                    f"{formatted_dt}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div style='display:flex; align-items:center; height:100%; padding-top:6px; font-size:0.9rem; color:#A1A1AA;'>"
                    "🕒 <em>Данные трендов еще не собирались</em>"
                    "</div>",
                    unsafe_allow_html=True,
                )


        # Используем актуальный слепок из github_trending, если он есть
        if github_trending_list:
            articles = list(github_trending_list)
        else:
            articles = [a for a in article_list if a.get("source_type") == "репозиторий"]

        # Фильтр по статусу в тренде
        if selected_repo_status == "Новые в тренде":
            articles = [a for a in articles if a.get("is_new")]
        elif selected_repo_status == "Уже были в базе (в тренде)":
            articles = [a for a in articles if not a.get("is_new")]

        # Фильтр по направлениям (0-4)
        if selected_directions:
            articles = [
                a for a in articles
                if any(d in selected_directions for d in a.get("directions", []))
            ]

        # Фильтр по типам задач (0-3)
        if selected_task_types:
            articles = [
                a for a in articles
                if any(t in selected_task_types for t in a.get("task_types", []))
            ]
    elif page == "Papers (Статьи)":
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            if st.button("🔄 Обновить статьи (HF + PwC)", help="Запустить балансированный сбор статей HF (30) и PwC (30)"):
                try:
                    res = requests.post(f"{API_URL}/papers/refresh", timeout=3)
                    st.success("Сбор статей запущен в фоне!")
                except Exception:
                    try:
                        from mcp_fetcher_papers import ingest_papers
                        with st.spinner("Сбор статей (HF + PwC + Healthcare)..."):
                            ingest_papers()
                        st.success("Статьи успешно собраны!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка сбора: {e}")

        with col_info:
            pwc_count = len([a for a in article_list if "PwC" in a.get("title", "")])
            hf_count = len([a for a in article_list if "[HF" in a.get("title", "")])
            st.markdown(
                f"<div style='display:flex; align-items:center; height:100%; padding-top:4px; font-size:0.95rem; color:#E4E4E7;'>"
                f"📊 <span style='color:#A1A1AA; margin-right:6px;'>В базе статей:</span>"
                f"<span style='color:#38BDF8; font-weight:600; background:#0F172A; padding:3px 10px; border-radius:6px; border:1px solid #0284C7; margin-right:8px;'>HF: {hf_count}</span>"
                f"<span style='color:#A78BFA; font-weight:600; background:#2E1065; padding:3px 10px; border-radius:6px; border:1px solid #7C3AED;'>PwC: {pwc_count}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        articles = [
            a for a in article_list
            if a.get("source_type", "статья") == tab_info["source_type"]
            and not (a.get("summary") or "").startswith("Связанный материал к статье:")
        ]
    elif page == "Датасеты":
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            if st.button("🔄 Обновить датасеты (HF + Kaggle)", help="Сбор трендовых датасетов Hugging Face (мировые + RU) и Kaggle"):
                started_in_backend = False
                try:
                    res = requests.post(f"{API_URL}/datasets/refresh", timeout=3)
                    started_in_backend = res.ok
                except Exception:
                    pass
                if started_in_backend:
                    st.success("Сбор датасетов запущен в фоне!")
                else:
                    try:
                        from main import run_datasets_only
                        with st.spinner("Сбор датасетов (Hugging Face + Kaggle)..."):
                            run_datasets_only()
                        st.success("Датасеты успешно собраны!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка сбора: {e}")

        with col_info:
            ds_total = len([a for a in article_list if a.get("source_type") == "датасет"])
            st.markdown(
                f"<div style='display:flex; align-items:center; height:100%; padding-top:4px; font-size:0.95rem; color:#E4E4E7;'>"
                f"📊 <span style='color:#A1A1AA; margin-right:6px;'>Датасетов в базе:</span>"
                f"<span style='color:#FBBF24; font-weight:600; background:#451A03; padding:3px 10px; border-radius:6px; border:1px solid #D97706;'>{ds_total}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        articles = [
            a for a in article_list
            if a.get("source_type", "статья") == tab_info["source_type"]
            and not (a.get("summary") or "").startswith("Связанный материал к статье:")
        ]
    else:
        articles = [
            a for a in article_list
            if a.get("source_type", "статья") == tab_info["source_type"]
            and not (a.get("summary") or "").startswith("Связанный материал к статье:")
        ]

    if search_art:
        articles = [a for a in articles if
                    search_art.lower() in a.get('title', '').lower() or
                    search_art.lower() in a.get('repo_name', '').lower() or
                    search_art.lower() in a.get('summary', '').lower()]

    if selected_tags:
        articles = [a for a in articles if any(t in selected_tags for t in a.get("tags", []))]

    if page == "Датасеты":
        if selected_ds_source == "Hugging Face":
            articles = [a for a in articles if "huggingface.co" in (a.get("source_url") or "").lower() or str(a.get("title", "")).startswith("[HF")]
        elif selected_ds_source == "Kaggle":
            articles = [a for a in articles if "kaggle.com" in (a.get("source_url") or "").lower() or str(a.get("title", "")).startswith("[Kaggle]")]

        if selected_has_spaces == "Только со Spaces (True)":
            articles = [a for a in articles if a.get("has_spaces")]
        elif selected_has_spaces == "Без Spaces (False)":
            articles = [a for a in articles if not a.get("has_spaces")]
        # Фильтр датасетов по языку
        articles = [
            a for a in articles
            if not selected_languages or any(lang.strip() in selected_languages for lang in (a.get("language") or "").split(","))
        ]

    if page == "Papers (Статьи)":
        if selected_paper_source == "Hugging Face Papers":
            articles = [
                a for a in articles
                if "[HF" in a.get("title", "") or "huggingface.co" in a.get("source_url", "")
            ]
        elif selected_paper_source == "Papers with Code":
            articles = [
                a for a in articles
                if "PwC" in a.get("title", "") or "paperswithcode" in a.get("source_url", "")
            ]

        if selected_topics:
            articles = [
                a for a in articles
                if a.get("topic_tag", "").strip() in selected_topics
            ]

        if selected_has_code == "Только с кодом (True)":
            articles = [
                a for a in articles
                if a.get("has_code") or any(
                    isinstance(r, dict) and (r.get("type") in ("github", "code") or "github.com" in r.get("url", ""))
                    for r in (a.get("related_links") or [])
                ) or "github.com" in (a.get("source_url") or "") or "github.com" in (a.get("summary") or "")
            ]
        elif selected_has_code == "Без кода (False)":
            articles = [
                a for a in articles
                if not (
                    a.get("has_code") or any(
                        isinstance(r, dict) and (r.get("type") in ("github", "code") or "github.com" in r.get("url", ""))
                        for r in (a.get("related_links") or [])
                    ) or "github.com" in (a.get("source_url") or "") or "github.com" in (a.get("summary") or "")
                )
            ]

    _TYPE_COLORS = {
        "статья": "#8B5CF6",
        "модель": "#22D3EE",
        "датасет": "#F59E0B",
        "репозиторий": "#34D399",
    }

    def render_article_card(a):
        tags_html = "".join([f'<span class="article-tag">{escape(str(t))}</span>' for t in (a.get("tags") or [])])
        source_url = a.get("source_url") or a.get("url", "")
        source_type = a.get("source_type", "репозиторий" if page == "Репозитории" else "статья")
        type_color = _TYPE_COLORS.get(source_type, "#8B5CF6")
        type_badge = f'<span style="font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:{type_color}; border:1px solid {type_color}; border-radius:6px; padding:2px 8px; margin-right:8px;">{source_type}</span>'

        # Бейдж наличия кода
        rel_links = a.get("related_links", [])
        if not isinstance(rel_links, list):
            rel_links = []

        has_code = bool(a.get("has_code")) or any(
            isinstance(r, dict) and (r.get("type") in ("github", "code") or "github.com" in r.get("url", ""))
            for r in rel_links
        ) or "github.com/" in (a.get("summary") or "") or "github.com/" in source_url

        if has_code:
            code_badge = '<span style="font-size:0.7rem; font-weight:700; color:#34D399; background:#064E3B; border:1px solid #059669; border-radius:6px; padding:2px 8px; margin-right:8px;">💻 Код: True</span>'
        else:
            code_badge = '<span style="font-size:0.7rem; font-weight:700; color:#9CA3AF; background:#1F2937; border:1px solid #374151; border-radius:6px; padding:2px 8px; margin-right:8px;">💻 Код: False</span>'

        # Специфичные бейджи для репозиториев
        repo_extra_badges = ""
        if page == "Репозитории" or source_type == "репозиторий":
            is_new = a.get("is_new", False)
            if is_new:
                status_badge = '<span style="font-size:0.7rem; font-weight:700; color:#34D399; background:#064E3B; border:1px solid #059669; border-radius:6px; padding:2px 8px; margin-right:6px;">🌟 НОВЫЙ В ТРЕНДЕ</span>'
            else:
                status_badge = '<span style="font-size:0.7rem; font-weight:700; color:#A78BFA; background:#2E1065; border:1px solid #7C3AED; border-radius:6px; padding:2px 8px; margin-right:6px;">🔥 В ТРЕНДЕ</span>'

            stars_count = a.get("stars", 0)
            stars_badge = f'<span style="font-size:0.7rem; font-weight:700; color:#FBBF24; background:#451A03; border:1px solid #D97706; border-radius:6px; padding:2px 8px; margin-right:6px;">⭐ {stars_count:,}</span>' if stars_count else ""

            dirs_badges = "".join([
                f'<span style="font-size:0.7rem; font-weight:600; color:#38BDF8; background:#0F172A; border:1px solid #0284C7; border-radius:6px; padding:2px 8px; margin-right:4px;">🧭 {d}</span>'
                for d in a.get("directions", [])
            ])
            tasks_badges = "".join([
                f'<span style="font-size:0.7rem; font-weight:600; color:#C084FC; background:#2E1065; border:1px solid #7E22CE; border-radius:6px; padding:2px 8px; margin-right:4px;">🎯 {t}</span>'
                for t in a.get("task_types", [])
            ])
            repo_extra_badges = f"{status_badge}{stars_badge}{dirs_badges}{tasks_badges}"

        language = (a.get("language") or "").strip()
        lang_badge = (
            f'<span style="font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:#A1A1AA; border:1px solid #2D1B4E; border-radius:6px; padding:2px 8px; margin-right:8px;">{language}</span>'
            if source_type == "датасет" and language else ""
        )
        # Лайки/звёзды датасета (HF likes, Kaggle votes) — в верхней строке карточки (ТЗ п.6)
        likes_badge = ""
        if source_type == "датасет":
            likes = int(a.get("stars", 0) or 0)
            if likes > 0:
                likes_badge = f'<span style="font-size:0.7rem; font-weight:700; color:#FBBF24; background:#451A03; border:1px solid #D97706; border-radius:6px; padding:2px 8px; margin-right:8px;">♡ {likes:,}</span>'
        topic_tag = (a.get("topic_tag") or "").strip()
        topic_badge = (
            f'<span style="font-size:0.7rem; font-weight:700; color:#EC4899; border:1px solid #EC4899; border-radius:6px; padding:2px 8px; margin-right:8px;">#{topic_tag}</span>'
            if topic_tag else ""
        )

        source_art_url = (a.get("source_article_url") or "").strip()
        source_art_html = (
            f'<div style="font-size:0.8rem; color:#A1A1AA; margin-top:4px;">Связано со статьей: <a href="{source_art_url}" target="_blank" style="color:#A78BFA; text-decoration:none;">{source_art_url}</a></div>'
            if source_art_url else ""
        )

        rel_html = ""
        top_models_html = ""
        if rel_links:
            badges = []
            for r in rel_links:
                if not isinstance(r, dict):
                    continue
                r_type = (r.get("type") or "link").lower()
                r_url = r.get("url", "")
                r_name = r.get("name") or r_url
                if not r_url:
                    continue
                safe_url = escape(str(r_url), quote=True)
                base_style = "display:inline-block; font-size:0.75rem; border-radius:6px; padding:3px 8px; margin:3px 6px 3px 0; text-decoration:none;"

                # --- Типы из ТЗ п.5: paper / models_catalog / spaces_catalog / kaggle_code ---
                if r_type == "paper":
                    badges.append(
                        f'<a href="{safe_url}" target="_blank" style="{base_style} color:#C084FC; background:#2E1065; border:1px solid #7C3AED;">'
                        f'📄 Статья: {escape(str(r_name))}</a>'
                    )
                    continue
                if r_type == "models_catalog":
                    top = [str(t) for t in (r.get("top_items") or [])][:3]
                    tip = escape("Топ моделей: " + ", ".join(top), quote=True) if top else "Каталог моделей, обученных на датасете"
                    badges.append(
                        f'<a href="{safe_url}" target="_blank" title="{tip}" style="{base_style} color:#38BDF8; background:#0C4A6E; border:1px solid #0284C7;">'
                        f'🤖 Обученные модели ↗</a>'
                    )
                    # Топ-3 — отдельный блок между кнопками и ссылкой на источник:
                    # шрифт как у основного текста карточки, модели списком в столбик.
                    if top:
                        top_models_html = (
                            '<div style="margin-top:10px;">'
                            '<div style="font-size:0.9rem; color:#A1A1AA; margin-bottom:2px;">Топ моделей:</div>'
                            '<div style="font-size:0.9rem; color:#D4D4D8; line-height:1.6;">'
                            + "".join(f'<div>• {escape(t)}</div>' for t in top)
                            + '</div></div>'
                        )
                    continue
                if r_type == "spaces_catalog":
                    badges.append(
                        f'<a href="{safe_url}" target="_blank" style="{base_style} color:#E879F9; background:#4A044E; border:1px solid #A21CAF;">'
                        f'🚀 Демо Spaces ↗</a>'
                    )
                    continue
                if r_type == "kaggle_code":
                    try:
                        cnt = int(r.get("count"))
                    except (TypeError, ValueError):
                        cnt = None
                    label_code = f"Решения: {cnt:,} ↗" if cnt else "Решения (Code) ↗"
                    badges.append(
                        f'<a href="{safe_url}" target="_blank" style="{base_style} color:#34D399; background:#064E3B; border:1px solid #059669;">'
                        f'💻 {label_code}</a>'
                    )
                    continue

                if r_type in ("github", "code"):
                    style = "color:#34D399; background:#064E3B; border:1px solid #059669;"
                    icon = "💻"
                    label = f"GitHub: {r_name}"
                elif r_type in ("модель", "model"):
                    style = "color:#38BDF8; background:#0C4A6E; border:1px solid #0284C7;"
                    icon = "🤖"
                    label = f"Модель: {r_name}"
                elif r_type in ("датасет", "dataset"):
                    style = "color:#FBBF24; background:#451A03; border:1px solid #D97706;"
                    icon = "📊"
                    label = f"Датасет: {r_name}"
                elif r_type in ("space", "спейс", "demo"):
                    style = "color:#E879F9; background:#4A044E; border:1px solid #A21CAF;"
                    icon = "🚀"
                    label = f"Space: {r_name}"
                elif r_type == "project":
                    style = "color:#60A5FA; background:#1E3A8A; border:1px solid #2563EB;"
                    icon = "🌐"
                    label = f"Project: {r_name}"
                else:
                    style = "color:#C084FC; background:#1E1B4B; border:1px solid #3B0764;"
                    icon = "🔗"
                    label = f"{r_type}: {r_name}"

                badges.append(
                    f'<a href="{r_url}" target="_blank" style="display:inline-block; font-size:0.75rem; border-radius:6px; padding:3px 8px; margin:3px 6px 3px 0; text-decoration:none; {style}">{icon} {label}</a>'
                )
            if badges:
                rel_html = f'<div style="margin-top:8px; display:flex; flex-wrap:wrap; gap:4px;">{"".join(badges)}</div>'

        btn_label = "Открыть на GitHub →" if source_type == "репозиторий" else "Читать источник →"
        link_html = (
            f'<a href="{source_url}" target="_blank" style="font-size:0.85rem; color:#A78BFA; text-decoration:none;">{btn_label}</a>'
            if source_url else ""
        )

        # Бейдж upvotes/stars для статей
        upvotes_badge = ""
        if source_type == "статья":
            votes = int(a.get("stars", 0) or a.get("upvotes", 0) or 0)
            if votes > 0:
                upvotes_badge = f'<span style="font-size:0.7rem; font-weight:700; color:#FBBF24; background:#451A03; border:1px solid #D97706; border-radius:6px; padding:2px 8px; margin-right:8px;">🔥 {votes:,} upvotes</span>'

        article_code_badge = code_badge if source_type == "статья" else ""

        dataset_spaces_badge = ""
        dataset_rank_badge = ""
        if source_type == "датасет":
            is_hf = "huggingface.co" in (source_url or "").lower() or str(a.get("title", "")).startswith("[HF")
            is_kaggle = "kaggle.com" in (source_url or "").lower() or str(a.get("title", "")).startswith("[Kaggle")
            rank_g = int(a.get("rank_global", 0) or 0)
            rank_r = int(a.get("rank_ru", 0) or 0)

            if is_hf:
                badges_list = []
                if rank_r > 0:
                    badges_list.append(
                        f'<span style="font-size:0.7rem; font-weight:700; color:#34D399; background:#064E3B; border:1px solid #059669; border-radius:6px; padding:2px 8px; margin-right:6px;">🇷🇺 RU #{rank_r}</span>'
                    )
                if rank_g > 0:
                    badges_list.append(
                        f'<span style="font-size:0.7rem; font-weight:700; color:#A78BFA; background:#2E1065; border:1px solid #7C3AED; border-radius:6px; padding:2px 8px; margin-right:6px;">🌍 Global #{rank_g}</span>'
                    )
                elif rank_r > 0 and rank_g == 0:
                    badges_list.append(
                        f'<span style="font-size:0.7rem; font-weight:600; color:#9CA3AF; background:#1F2937; border:1px solid #374151; border-radius:6px; padding:2px 8px; margin-right:6px;">🌍 Вне мирового топа</span>'
                    )
                dataset_rank_badge = "".join(badges_list)

                has_spaces = bool(a.get("has_spaces"))
                if has_spaces:
                    dataset_spaces_badge = '<span style="font-size:0.7rem; font-weight:700; color:#E879F9; background:#4A044E; border:1px solid #A21CAF; border-radius:6px; padding:2px 8px; margin-right:8px;">🚀 Spaces: Есть (True)</span>'
                else:
                    dataset_spaces_badge = '<span style="font-size:0.7rem; font-weight:700; color:#9CA3AF; background:#1F2937; border:1px solid #374151; border-radius:6px; padding:2px 8px; margin-right:8px;">🚀 Spaces: Нет (False)</span>'
            elif is_kaggle:
                k_rank = rank_g if rank_g > 0 else (a.get("rowid") or 0)
                if k_rank > 0:
                    dataset_rank_badge = f'<span style="font-size:0.7rem; font-weight:700; color:#38BDF8; background:#0C4A6E; border:1px solid #0284C7; border-radius:6px; padding:2px 8px; margin-right:6px;">🏆 Kaggle #{k_rank}</span>'
                dataset_spaces_badge = '<span style="font-size:0.7rem; font-weight:500; color:#94A3B8; background:#0F172A; border:1px solid #334155; border-radius:6px; padding:2px 8px; margin-right:8px;">Kaggle (без Spaces)</span>'

        st.markdown(
            f'<div class="custom-card">'
            f'<div class="article-tags">{type_badge}{dataset_rank_badge}{upvotes_badge}{article_code_badge}{dataset_spaces_badge}{repo_extra_badges}{lang_badge}{likes_badge}{topic_badge}{tags_html}</div>'
            f'<h4 style="margin:0; color:#FFFFFF;">{a.get("title") or a.get("repo_name")}</h4>'
            f'<div style="font-size:0.9rem; color:#D4D4D8; margin:10px 0; line-height:1.6; white-space:pre-line;">{a.get("summary")}</div>'
            f'{source_art_html}{rel_html}{top_models_html}'
            f'<div style="margin-top:8px;">{link_html}</div></div>',
            unsafe_allow_html=True)

    if page == "Papers (Статьи)":
        if sort_paper == "По трендовости (Upvotes 🔥)":
            articles = sorted(articles, key=lambda x: int(x.get("stars", 0) or x.get("upvotes", 0) or 0), reverse=True)
        elif sort_paper == "Сначала новые (New 🕒)":
            articles = sorted(articles, key=lambda x: (x.get("added_at") or "", x.get("rowid", 0)), reverse=True)

        tab_week, tab_month = st.tabs(["🔥 Тренды за неделю", "📅 Тренды за месяц"])

        with tab_week:
            week_articles = [a for a in articles if a.get("period") == "weekly"]
            if not week_articles:
                week_articles = [a for a in articles if a.get("period") != "monthly"] or articles[:30]
            if sort_paper == "По трендовости (Upvotes 🔥)":
                week_articles = sorted(week_articles, key=lambda x: int(x.get("stars", 0) or x.get("upvotes", 0) or 0), reverse=True)
            if week_articles:
                st.caption(f"Найдено статей за неделю: {len(week_articles)}")
                for a in week_articles:
                    render_article_card(a)
            else:
                st.info("Нет статей за неделю по выбранным фильтрам.")

        with tab_month:
            month_articles = list(articles)
            if sort_paper == "По трендовости (Upvotes 🔥)":
                month_articles = sorted(month_articles, key=lambda x: int(x.get("stars", 0) or x.get("upvotes", 0) or 0), reverse=True)
            if month_articles:
                st.caption(f"Найдено статей за месяц: {len(month_articles)}")
                for a in month_articles:
                    render_article_card(a)
            else:
                st.info("Нет статей за месяц по выбранным фильтрам.")
    elif page == "Датасеты":
        if sort_ds == "По российскому рейтингу (RU)":
            articles = sorted(articles, key=lambda x: (x.get("rank_ru") if (x.get("rank_ru") or 0) > 0 else 9999, -(x.get("stars") or 0)))
        elif sort_ds == "По мировому рейтингу (Global)":
            articles = sorted(articles, key=lambda x: (x.get("rank_global") if (x.get("rank_global") or 0) > 0 else 9999, -(x.get("stars") or 0)))
        elif sort_ds == "По лайкам / голосам":
            articles = sorted(articles, key=lambda x: int(x.get("stars", 0) or 0), reverse=True)
        elif sort_ds == "Сначала новые":
            articles = sorted(articles, key=lambda x: (x.get("added_at") or "", x.get("rowid", 0)), reverse=True)

        tab_ru, tab_global, tab_kaggle, tab_all = st.tabs([
            "🇷🇺 Российские тренды (RU)",
            "🌍 Мировые тренды HF",
            "🏆 Kaggle Trending",
            "📋 Все датасеты"
        ])

        with tab_ru:
            ru_datasets = [
                a for a in articles
                if (a.get("rank_ru") or 0) > 0 or "ru" in (a.get("language") or "").lower() or "#Russian" in (a.get("tags") or [])
            ]
            ru_datasets.sort(key=lambda x: (x.get("rank_ru") if (x.get("rank_ru") or 0) > 0 else 9999, -(x.get("stars") or 0)))
            if ru_datasets:
                st.caption(f"Найдено датасетов с поддержкой русского языка: {len(ru_datasets)}")
                for a in ru_datasets:
                    render_article_card(a)
            else:
                st.info("Нет русскоязычных датасетов по выбранным фильтрам.")

        with tab_global:
            global_datasets = [
                a for a in articles
                if (a.get("rank_global") or 0) > 0 and ("huggingface.co" in (a.get("source_url") or "").lower() or str(a.get("title", "")).startswith("[HF"))
            ]
            global_datasets.sort(key=lambda x: (x.get("rank_global") if (x.get("rank_global") or 0) > 0 else 9999, -(x.get("stars") or 0)))
            if global_datasets:
                st.caption(f"Найдено мировых трендовых датасетов HF: {len(global_datasets)}")
                for a in global_datasets:
                    render_article_card(a)
            else:
                st.info("Нет мировых датасетов по выбранным фильтрам.")

        with tab_kaggle:
            kaggle_datasets = [
                a for a in articles
                if "kaggle.com" in (a.get("source_url") or "").lower() or str(a.get("title", "")).startswith("[Kaggle")
            ]
            kaggle_datasets.sort(key=lambda x: (x.get("rank_global") if (x.get("rank_global") or 0) > 0 else (x.get("rowid") or 9999)))
            if kaggle_datasets:
                st.caption(f"Найдено трендовых датасетов Kaggle: {len(kaggle_datasets)}")
                for a in kaggle_datasets:
                    render_article_card(a)
            else:
                st.info("Нет датасетов Kaggle по выбранным фильтрам.")

        with tab_all:
            if articles:
                st.caption(f"Всего датасетов в каталоге: {len(articles)}")
                for a in articles:
                    render_article_card(a)
            else:
                st.info("Нет датасетов по выбранным фильтрам.")
    else:
        if articles:
            for a in articles:
                render_article_card(a)
        else:
            st.info("Материалы не найдены.")