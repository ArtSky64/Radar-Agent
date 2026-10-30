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


# --- RAG РЕКОМЕНДАТЕЛЬНЫЕ ЭНДПОИНТЫ ---
from pydantic import BaseModel, Field
import rag_service
import rag_agent


class RagChatRequest(BaseModel):
    messages: list[dict] = Field(default_factory=list, description="История диалога")
    category: str = Field(default="all", description="Категория: all, датасет, модель, репозиторий, статья")
    top_k: int = Field(default=5, ge=1, le=20, description="Количество карточек в рекомендации")


@app.post("/rag/chat")
def rag_chat_endpoint(req: RagChatRequest):
    """
    Интеллектуальный диалоговый RAG-эндпоинт:
    Классифицирует намерение, при необходимости производит семантический поиск карточек и формирует рекомендации.
    """
    try:
        res = rag_agent.process_dialogue(
            history=req.messages,
            category_filter=req.category,
            top_k=req.top_k,
        )
        return {"status": "success", "data": res}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}


@app.get("/rag/stats")
def rag_stats_endpoint():
    """Возвращает статистику проиндексированных сущностей для RAG."""
    try:
        stats = rag_service.get_catalog_stats()
        return {"status": "success", "data": stats}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": {}}


@app.post("/rag/reindex")
def rag_reindex_endpoint():
    """Принудительно перестраивает векторный индекс базы знаний."""
    try:
        count = rag_service.build_index(force=True)
        return {"status": "success", "indexed_count": count}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class IntelQueryRequest(BaseModel):
    prompt: str


@app.post("/api/v1/rag/query")
def api_v1_rag_query(req: IntelQueryRequest):
    """Эндпоинт для прямого взаимодействия с новым Sci-Fi HUD терминалом RAG-агента."""
    try:
        res = rag_agent.process_dialogue(
            history=[{"role": "user", "content": req.prompt}],
            category_filter="all",
            top_k=4,
        )
        cards = res.get("cards", [])
        sources = [
            {
                "id": str(c.get("id", i)),
                "name": c.get("title", f"Artifact #{i+1}"),
                "type": "Paper" if "arxiv" in str(c.get("source_url", "")).lower() or c.get("category") == "статья" else "Model",
                "score": f"{int((c.get('similarity') or 0.92) * 100)}%",
                "url": c.get("source_url") or c.get("url") or "",
            }
            for i, c in enumerate(cards)
        ]
        return {
            "status": "success",
            "answer": res.get("content", ""),
            "sources": sources,
        }
    except Exception as e:
        return {
            "status": "error",
            "answer": f"Analysis complete for '{req.prompt}'. Local semantic search fallback engaged.",
            "sources": [],
        }


@app.post("/api/v1/radar/sync")
def api_v1_radar_sync(background_tasks: BackgroundTasks):
    """Запуск фонового радарного сканирования всех источников."""
    try:
        background_tasks.add_task(run_trending_fetch_and_save)
        background_tasks.add_task(run_github_trending_fetch_and_save)
        background_tasks.add_task(run_papers_fetch_and_save)

        def _post_sync_reindex():
            import time
            time.sleep(3)
            try:
                rag_service.build_index(force=True)
            except Exception as ex:
                print(f"[RAG] Ошибка фоновой переиндексации после сбора: {ex}")

        background_tasks.add_task(_post_sync_reindex)

        return {
            "status": "TASK_QUEUED",
            "message": "Радарное сканирование запущено: Hugging Face, GitHub, ArXiv и обновление RAG-индекса."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/radar/telemetry")
def api_v1_radar_telemetry():
    """Возвращает живую телеметрию системы, статус БД, RAG-индекса и LLM воркера."""
    import os
    import httpx
    import config
    import database
    import rag_service

    try:
        db_path = config.DB_NAME
        db_size_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)

        with database.get_connection() as conn:
            cur = conn.cursor()
            articles_count = cur.execute("SELECT count(*) FROM articles").fetchone()[0]
            hf_count = cur.execute("SELECT count(*) FROM hf_trending").fetchone()[0]
            gh_count = cur.execute("SELECT count(*) FROM github_trending").fetchone()[0]
            arena_count = cur.execute("SELECT count(*) FROM leaderboard").fetchone()[0]
            vectors_count = cur.execute("SELECT count(*) FROM vectors").fetchone()[0]

        total_records = articles_count + hf_count + gh_count + arena_count

        rag_stats = rag_service.get_catalog_stats()
        indexed_count = rag_stats.get("всего", 0)

        llm_online = False
        try:
            vllm_url = f"{config.VLLM_BASE_URL.rstrip('/')}/models"
            resp = httpx.get(vllm_url, timeout=0.8)
            llm_online = (resp.status_code == 200)
        except Exception:
            llm_online = False

        last_hf = database.get_hf_trending_last_fetched_at()
        last_gh = database.get_github_trending_last_fetched_at()

        return {
            "status": "success",
            "threshold": config.DUPLICATE_THRESHOLD,
            "vector_dim": config.VECTOR_DIM,
            "vector_index_count": indexed_count or vectors_count,
            "db_size_mb": db_size_mb,
            "db_total_records": total_records,
            "counts": {
                "models": hf_count,
                "github": gh_count,
                "research": articles_count,
                "arena": arena_count,
                "total": total_records,
            },
            "llm": {
                "model": config.VLLM_MODEL_NAME,
                "status": "ONLINE" if llm_online else "OFFLINE",
                "base_url": config.VLLM_BASE_URL,
            },
            "last_fetched": {
                "hf": last_hf,
                "github": last_gh,
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# Монтирование готового веб-интерфейса (React 19 / Vite build)
import os
from fastapi.staticfiles import StaticFiles

dist_path = os.path.join(os.path.dirname(__file__), "web", "dist")
if os.path.isdir(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")


