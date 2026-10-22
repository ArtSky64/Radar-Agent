from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from database import (
    init_db, get_all_leaderboard_snapshots, save_leaderboard_data, get_all_articles,
    get_analysis_history, save_trending_models, get_trending_models, get_hf_trending_last_fetched_at,
    save_github_trending, get_github_trending,
)
import arena_scraper
from leaderboard_analyzer import run_leaderboard_analysis
from mcp_fetcher_hf_trending import fetch_trending_models
from github_fetcher import run_github_trending_pipeline


app = FastAPI(title="Arena AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


# Внутренняя функция бэкенда, которая соединяет оригинальный скрапер и базу данных
def run_original_scraper_and_save():
    print("[БЭКЕНД] Запуск оригинального утвержденного скрапера...")

    # Единый список категорий — теперь берём из arena_scraper.CATEGORY_URLS,
    # чтобы не держать одну и ту же копию в двух местах (было тут и в arena_scraper.main()).
    category_urls = arena_scraper.CATEGORY_URLS

    try:
        # 1. Запускаем сбор данных (функция вернет final_snapshot)
        real_data = arena_scraper.collect_all_categories(category_urls)

        # 2. Передаем собранный словарь напрямую в оригинальную функцию сохранения базы данных
        print("[БЭКЕНД] Сбор завершен. Записываем живые данные в базу...")
        save_leaderboard_data(real_data)
        print("[БЭКЕНД] Успешно сохранено! Строим инкрементальный анализ...")

        # Анализ строится СРАЗУ после сохранения нового снимка: агент видит
        # новый снимок, предыдущий снимок и свой же предыдущий анализ.
        run_leaderboard_analysis()
        print("[БЭКЕНД] Анализ лидерборда обновлён!")
    except Exception as e:
        print(f"[БЭКЕНД ОШИБКА] Ошибка при работе связки скрапера и БД: {e}")


# Эндпоинт для вывода лидерборда на фронтенд
@app.get("/leaderboard")
def read_leaderboard():
    try:
        snapshots_list = get_all_leaderboard_snapshots()
        return {
            "status": "success",
            "total_snapshots": len(snapshots_list),
            "data": snapshots_list
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}


# Эндпоинт для фонового запуска оригинального скрапера
@app.post("/scrape")
def trigger_scraping(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_original_scraper_and_save)
    return {
        "status": "success",
        "message": "Оригинальный скрапер запущен! Сбор данных займет около 1-2 минут."
    }


# Эндпоинт для истории анализа лидерборда (от новых к старым)
@app.get("/leaderboard/analysis")
def read_leaderboard_analysis():
    try:
        history = get_analysis_history(limit=10)
        return {
            "status": "success",
            "total_analyses": len(history),
            "data": history,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}


# Внутренняя функция бэкенда: тянет трендовые модели через hf-trending-mcp и сохраняет
def run_trending_fetch_and_save():
    print("[БЭКЕНД] Запуск сбора трендовых моделей HF (hf-trending-mcp)...")
    try:
        models = fetch_trending_models(limit=30)
        if not models:
            print("[БЭКЕНД] Трендовые модели не получены (пусто или ошибка MCP-сервера).")
            return
        save_trending_models(models)
        print(f"[БЭКЕНД] Сохранено трендовых моделей: {len(models)}")
    except Exception as e:
        print(f"[БЭКЕНД ОШИБКА] Не удалось получить трендовые модели: {e}")


# Эндпоинт для фонового запуска сбора трендовых моделей
@app.post("/trending/refresh")
def trigger_trending_fetch(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_trending_fetch_and_save)
    return {
        "status": "success",
        "message": "Сбор трендовых моделей HF запущен в фоне.",
    }


# Эндпоинт для вывода текущей витрины трендовых моделей
@app.get("/trending/models")
def read_trending_models(variant: str | None = None):
    try:
        models = get_trending_models(variant=variant)
        last_fetched_at = get_hf_trending_last_fetched_at()
        ru_models = [m for m in models if m.get("rank_ru", 0) > 0 or "ru" in (m.get("variant") or "")]
        global_models = [m for m in models if m.get("rank_global", 0) > 0]
        return {
            "status": "success",
            "total_models": len(models),
            "last_fetched_at": last_fetched_at,
            "data": models,
            "ru_models": ru_models,
            "global_models": global_models,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": [], "last_fetched_at": None}


# Внутренняя функция бэкенда: тянет трендовые репозитории GitHub и сохраняет
def run_github_trending_fetch_and_save():
    print("[БЭКЕНД] Запуск сбора трендовых репозиториев GitHub (weekly + monthly)...")
    try:
        repos = run_github_trending_pipeline(limit=30)
        print(f"[БЭКЕНД] Сохранено трендовых репозиториев GitHub: {len(repos)}")
    except Exception as e:
        print(f"[БЭКЕНД ОШИБКА] Не удалось получить трендовые репозитории GitHub: {e}")


# Эндпоинт для фонового запуска сбора трендовых репозиториев GitHub
@app.post("/trending/github/refresh")
def trigger_github_trending_fetch(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_github_trending_fetch_and_save)
    return {
        "status": "success",
        "message": "Сбор трендовых репозиториев GitHub (weekly + monthly) запущен в фоне.",
    }


# Эндпоинт для вывода текущей витрины трендовых репозиториев GitHub
@app.get("/trending/github")
def read_github_trending():
    try:
        repos = get_github_trending()
        last_fetched_at = repos[0].get("fetched_at") if repos else None
        return {
            "status": "success",
            "total_repos": len(repos),
            "last_fetched_at": last_fetched_at,
            "data": repos,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": [], "last_fetched_at": None}



# Твой эндпоинт для статей (оставляем без изменений)
@app.get("/articles")
def read_articles():
    articles_list = get_all_articles()
    return {
        "status": "success",
        "total_articles": len(articles_list),
        "data": articles_list
    }


# Внутренняя функция бэкенда: тянет статьи HF + PwC и сохраняет в БД
def run_papers_fetch_and_save():
    print("[БЭКЕНД] Запуск сбора статей (HF + PwC + Healthcare)...")
    try:
        from mcp_fetcher_papers import ingest_papers
        ingest_papers()
        print("[БЭКЕНД] Сбор статей успешно завершен!")
    except Exception as e:
        print(f"[БЭКЕНД ОШИБКА] Ошибка при сборе статей: {e}")


# Эндпоинт для фонового запуска сбора статей
@app.post("/papers/refresh")
def trigger_papers_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_papers_fetch_and_save)
    return {
        "status": "success",
        "message": "Сбор статей (HF + PwC + Healthcare) запущен в фоне.",
    }


# Внутренняя функция бэкенда: собирает трендовые датасеты (Hugging Face + Kaggle) через общий
# пайплайн main.py (дедуп -> ИИ-анализ -> БД). Импорт ленивый, как и у статей.
def run_datasets_fetch_and_save():
    print("[БЭКЕНД] Запуск сбора датасетов (Hugging Face + Kaggle)...")
    try:
        from main import run_datasets_only
        processed, skipped, failed = run_datasets_only()
        print(f"[БЭКЕНД] Датасеты: обработано {processed}, дублей {skipped}, ошибок {failed}")
    except Exception as e:
        print(f"[БЭКЕНД ОШИБКА] Ошибка при сборе датасетов: {e}")


# Эндпоинт для фонового запуска сбора датасетов (кнопка на вкладке «Датасеты»)
@app.post("/datasets/refresh")
def trigger_datasets_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_datasets_fetch_and_save)
    return {
        "status": "success",
        "message": "Сбор датасетов (Hugging Face + Kaggle) запущен в фоне.",
    }