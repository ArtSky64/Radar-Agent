# для запуска: uvicorn app:app --reload (бэкенд), затем python -m streamlit run frontend.py (фронтенд)

import os
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

if leaderboard_res.get("status") == "success" and leaderboard_res.get("data"): #изменено 
    
    leaderboard_records = build_latest_records(leaderboard_res["data"])
    unique_categories = {r["category"] for r in leaderboard_records}
    unique_models = {r["model_name"] for r in leaderboard_records}

trend_list = trending_res.get("data", []) if trending_res.get("status") == "success" else []
article_list = articles_res.get("data", []) if articles_res.get("status") == "success" else []

# Имитация системы тегов для статей
available_tags = ["LLM", "RLHF", "Vision", "Agents", "Optimization", "Open-Source"]
for i, art in enumerate(article_list):
    if "tags" not in art:
        art["tags"] = [available_tags[i % len(available_tags)], available_tags[(i + 2) % len(available_tags)]]

# --- НАВИГАЦИЯ (СВЕРХУ) ---

# Меню вкладок
page = st.radio(
    "Разделы",
    ["Лидерборд моделей", "Трендовые модели HF", "Papers (Статьи)", "Модели", "Датасеты", "Репозитории"],
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
    "Модели": {
        "source_type": "модель",
        "hint": "Новые модели с Hugging Face — отобраны и описаны ИИ-агентом по карточке модели.",
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

    elif page == "Трендовые модели HF":
        st.markdown("<h5 style='color:#FFFFFF; margin-bottom:10px;'>Фильтры</h5>", unsafe_allow_html=True)
        search_hf = st.text_input("Поиск по названию модели")

        sort_by = st.selectbox("Сортировать по", ["Скачиваниям", "Лайкам"])
        sort_order = st.selectbox("Порядок", ["По убыванию", "По возрастанию"])

    elif page in _CONTENT_TABS:
        st.markdown(f"<h5 style='color:#FFFFFF; margin-bottom:10px;'>Фильтры: {page}</h5>", unsafe_allow_html=True)
        search_art = st.text_input("Ключевые слова")
        selected_tags = st.multiselect("Поиск по тегам", available_tags, placeholder="Выберите теги...")

        # Язык сейчас заполняется только у HF-датасетов, поэтому фильтр
        # показываем только на вкладке "Датасеты".
        selected_languages = []
        if page == "Датасеты":
            available_languages = sorted({
                lang.strip()
                for a in article_list
                if a.get("source_type") == "датасет"
                for lang in (a.get("language") or "").split(",")
                if lang.strip()
            })
            if available_languages:
                selected_languages = st.multiselect(
                    "Язык датасета", available_languages, placeholder="Все языки..."
                )

        # Фильтры для Papers (Статьи)
        selected_topics = []
        selected_paper_source = "Все источники"
        if page == "Papers (Статьи)":
            selected_paper_source = st.selectbox(
                "Источник статей",
                ["Все источники", "Hugging Face Papers", "Papers with Code"],
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



# --- ЛОГИКА ОТРЕСОВКИ СТРАНИЦ ---

if page == "Лидерборд моделей":
    st.markdown("<h1>Лидерборд моделей</h1>", unsafe_allow_html=True)

    with st.expander("Как рассчитывается рейтинг Elo?"):
        st.write(
            "Рейтинг Elo вычисляется на основе результатов попарных «слепых» тестирований. Пользователи или автоматические бенчмарки оценивают ответы двух анонимных моделей на один и тот же промпт. Если модель побеждает, её рейтинг повышается, а у проигравшей — снижается. Величина изменения рейтинга зависит от разницы их баллов до матча: победа над сильным конкурентом (с высоким Elo) приносит значительно больше баллов, чем победа над слабым.")

    # Вывод ИИ-анализа лидерборда, если доступен
    if latest_analysis and latest_analysis.get("analysis_text"):
        with st.expander("Анализ трендов лидерборда (ИИ)", expanded=False):
            st.markdown(
                f"<div style='font-size:0.9rem; color:#E4E4E7; white-space:pre-wrap; line-height:1.5;'>"
                f"{latest_analysis['analysis_text']}"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True)

    is_aggregate = selected_cat == ALL_CATEGORIES # изменено 

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
            name = escape(str(rec["model_name"]))
            if is_aggregate:
                subtitle = escape(rec["category"].upper())
                details = (
                    '<div style="font-size:0.75rem; color:#A1A1AA; margin-top:4px;">'
                    f'{escape(", ".join(rec["categories"]))}</div>'
                )
            else:
                subtitle = escape(rec["category"].upper())
                details = ""

            st.markdown(
                f'<div class="custom-card"><div style="display:flex; justify-content:space-between; align-items:center;"><div><strong style="font-size:1.1rem; color:#FFFFFF;">#{idx + 1} {name}</strong><div style="font-size:0.8rem; color:#8B5CF6; margin-top:2px;">{subtitle}</div>{details}</div><div style="font-size:1.2rem; font-weight:700; color:#A78BFA;">{format_rating(rec["rating"])}</div></div></div>',
                unsafe_allow_html=True)
    else:
        st.warning("В данной категории пока нет записей.")

elif page == "Трендовые модели HF":
    st.markdown("<h1>Тренды Hugging Face</h1>", unsafe_allow_html=True)

    models = trend_list
    if search_hf:
        models = [m for m in models if search_hf.lower() in m.get('model_name', '').lower()]

    if models:
        sort_key = "downloads" if sort_by == "Скачиваниям" else "likes"
        is_reverse = True if sort_order == "По убыванию" else False

        models = sorted(models, key=lambda x: x.get(sort_key, 0), reverse=is_reverse)

        for m in models[:30]:
            model_name = m.get("model_name", "Unknown")
            model_url = m.get("source_url") or f"https://huggingface.co/{model_name}"
            summary = m.get("summary") or ""
            summary_html = f'<p style="font-size:0.85rem; color:#D4D4D8; margin:8px 0 0;">{summary}</p>' if summary else ""
            st.markdown(
                f'<div class="custom-card"><a href="{model_url}" target="_blank" style="text-decoration:none;"><strong style="font-size:1.1rem; color:#FFFFFF;">{model_name}</strong></a><div style="margin-top:8px; font-size:0.85rem; color:#A78BFA;"><span>⬇ Скачивания: {m.get("downloads", 0):,}</span> │ <span>♡ Лайки: {m.get("likes", 0):,}</span></div>{summary_html}</div>',
                unsafe_allow_html=True)
    else:
        st.info("Нет данных по заданным фильтрам.")

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
    else:
        articles = [a for a in article_list if a.get("source_type", "статья") == tab_info["source_type"]]

    if search_art:
        articles = [a for a in articles if
                    search_art.lower() in a.get('title', '').lower() or
                    search_art.lower() in a.get('repo_name', '').lower() or
                    search_art.lower() in a.get('summary', '').lower()]

    if selected_tags:
        articles = [a for a in articles if any(t in selected_tags for t in a.get("tags", []))]

    if page == "Датасеты" and selected_languages:
        articles = [
            a for a in articles
            if any(lang.strip() in selected_languages for lang in (a.get("language") or "").split(","))
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

    _TYPE_COLORS = {
        "статья": "#8B5CF6",
        "модель": "#22D3EE",
        "датасет": "#F59E0B",
        "репозиторий": "#34D399",
    }

    if articles:
        for a in articles:
            tags_html = "".join([f'<span class="article-tag">{t}</span>' for t in a.get("tags", [])])
            source_url = a.get("source_url") or a.get("url", "")
            source_type = a.get("source_type", "репозиторий" if page == "Репозитории" else "статья")
            type_color = _TYPE_COLORS.get(source_type, "#8B5CF6")
            type_badge = f'<span style="font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:{type_color}; border:1px solid {type_color}; border-radius:6px; padding:2px 8px; margin-right:8px;">{source_type}</span>'

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

            rel_links = a.get("related_links", [])
            rel_html = ""
            if isinstance(rel_links, list) and rel_links:
                badges = []
                for r in rel_links:
                    r_type = r.get("type", "link")
                    r_url = r.get("url", "")
                    r_name = r.get("name", "ссылка")
                    if r_url:
                        badges.append(
                            f'<a href="{r_url}" target="_blank" style="display:inline-block; font-size:0.75rem; color:#C084FC; background:#1E1B4B; border:1px solid #3B0764; border-radius:4px; padding:2px 6px; margin:2px 4px 2px 0; text-decoration:none;">🔗 {r_type}: {r_name}</a>'
                        )
                if badges:
                    rel_html = f'<div style="margin-top:6px;">{"".join(badges)}</div>'

            btn_label = "Открыть на GitHub →" if source_type == "репозиторий" else "Читать источник →"
            link_html = (
                f'<a href="{source_url}" target="_blank" style="font-size:0.85rem; color:#A78BFA; text-decoration:none;">{btn_label}</a>'
                if source_url else ""
            )
            st.markdown(
                f'<div class="custom-card">'
                f'<div class="article-tags">{type_badge}{repo_extra_badges}{lang_badge}{topic_badge}{tags_html}</div>'
                f'<h4 style="margin:0; color:#FFFFFF;">{a.get("title") or a.get("repo_name")}</h4>'
                f'<p style="font-size:0.9rem; color:#D4D4D8; margin:8px 0; line-height:1.5;">{a.get("summary")}</p>'
                f'{source_art_html}{rel_html}'
                f'<div style="margin-top:8px;">{link_html}</div></div>',
                unsafe_allow_html=True)
    else:
        st.info("Материалы не найдены.")
