# для запуска: uvicorn app:app --reload (бэкенд), затем python -m streamlit run frontend.py (фронтенд)

import os
from collections import defaultdict
import streamlit as st
import requests
from html import escape

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
    ТЗ Блок 5 (фидбек п.5): Агрегация «Все категории» лидерборда Arena.
    Устраняет баг plain-конкатенации, при котором одна и та же модель выводилась N раз
    с несопоставимыми Elo-рейтингами из разных категорий.

    Группирует записи по model_name и вычисляет:
    - Вариант A (method='avg', рекомендуется): средний рейтинг avg(rating) по категориям модели.
    - Вариант B (method='max'): максимальный рейтинг max(rating) + категория-источник.

    :param records: список словарей с ключами model_name, category, rating
    :param method: 'avg' (среднее) или 'max' (максимум)
    :return: отсортированный по убыванию rating список агрегированных моделей
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
            if isinstance(val, (int, float)):
                valid_ratings.append(float(val))
            elif isinstance(val, str):
                cleaned = val.replace("%", "").strip()
                try:
                    valid_ratings.append(float(cleaned))
                except ValueError:
                    pass

        if not valid_ratings:
            avg_rating = 0.0
            max_rating = 0.0
            best_cat = rows[0].get("category", "")
        else:
            avg_rating = round(sum(valid_ratings) / len(valid_ratings), 1)

            def _get_sortable_rating(row):
                v = row.get("rating")
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    try:
                        return float(v.replace("%", "").strip())
                    except ValueError:
                        return -1.0
                return -1.0

            best_row = max(rows, key=_get_sortable_rating)
            max_rating = _get_sortable_rating(best_row)
            best_cat = best_row.get("category", "")

        cats = sorted(set(r.get("category", "") for r in rows if r.get("category")))
        num_cats = len(cats)
        cats_str = ", ".join(c.upper() for c in cats)

        if method == "max":
            chosen_rating = max_rating
            cat_label = f"МАКС: {best_cat.upper()} ({num_cats} {format_cat_plural(num_cats)}: {cats_str})"
        else:
            chosen_rating = avg_rating
            cat_label = f"{num_cats} {format_cat_plural(num_cats)}: {cats_str}"

        aggregated.append({
            "model_name": name,
            "rating": chosen_rating,
            "categories": cats,
            "category": cat_label,
            "num_categories": num_cats,
            "avg_rating": avg_rating,
            "max_rating": max_rating,
            "best_category": best_cat,
            "fetched_at": rows[0].get("fetched_at"),
        })

    return sorted(aggregated, key=lambda x: x["rating"], reverse=True)


leaderboard_res = fetch_data("leaderboard")
trending_res = fetch_data("trending/models")
articles_res = fetch_data("articles")
analysis_res = fetch_data("leaderboard/analysis")

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
        filtered = aggregate_all_categories(leaderboard_records)
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

    articles = [a for a in article_list if a.get("source_type", "статья") == tab_info["source_type"]]

    if search_art:
        articles = [a for a in articles if
                    search_art.lower() in a.get('title', '').lower() or search_art.lower() in a.get('summary',
                                                                                                    '').lower()]

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
            source_url = a.get("source_url", "")
            source_type = a.get("source_type", "статья")
            type_color = _TYPE_COLORS.get(source_type, "#8B5CF6")
            type_badge = f'<span style="font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:{type_color}; border:1px solid {type_color}; border-radius:6px; padding:2px 8px; margin-right:8px;">{source_type}</span>'
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

            link_html = (
                f'<a href="{source_url}" target="_blank" style="font-size:0.85rem; color:#A78BFA; text-decoration:none;">Читать источник →</a>'
                if source_url else ""
            )
            st.markdown(
                f'<div class="custom-card"><div class="article-tags">{type_badge}{lang_badge}{topic_badge}{tags_html}</div><h4 style="margin:0; color:#FFFFFF;">{a.get("title")}</h4><p style="font-size:0.9rem; color:#D4D4D8; margin:8px 0;">{a.get("summary")}</p>{source_art_html}{rel_html}<div style="margin-top:8px;">{link_html}</div></div>',
                unsafe_allow_html=True)
    else:
        st.info("Материалы не найдены.")