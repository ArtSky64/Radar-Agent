from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import os
import threading

from database import (
    init_db, get_all_leaderboard_snapshots, save_leaderboard_data, get_all_articles,
    get_analysis_history, save_trending_models, get_trending_models, get_hf_trending_last_fetched_at,
    save_github_trending, get_github_trending,
)
import arena_scraper
from leaderboard_analyzer import run_leaderboard_analysis
from hf_trending_fetcher import fetch_trending_models
from github_fetcher import run_github_trending_pipeline
import rag_service
import rag_agent


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
    threading.Thread(target=rag_service.build_index, daemon=True).start()


def run_original_scraper_and_save():
    category_urls = arena_scraper.CATEGORY_URLS
    try:
        real_data = arena_scraper.collect_all_categories(category_urls)
        save_leaderboard_data(real_data)
        run_leaderboard_analysis()
    except Exception as e:
        print(f"[ERROR] Ошибка скрапера лидерборда: {e}")


@app.get("/leaderboard")
def read_leaderboard():
    try:
        snapshots_list = get_all_leaderboard_snapshots()
        return {
            "status": "success",
            "total_snapshots": len(snapshots_list),
            "data": snapshots_list,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}


@app.post("/scrape")
def trigger_scraping(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_original_scraper_and_save)
    return {
        "status": "success",
        "message": "Сбор лидерборда запущен в фоне.",
    }


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


def run_trending_fetch_and_save():
    try:
        models = fetch_trending_models(limit=30)
        if models:
            save_trending_models(models)
    except Exception as e:
        print(f"[ERROR] Ошибка сбора трендовых моделей: {e}")


@app.post("/trending/refresh")
def trigger_trending_fetch(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_trending_fetch_and_save)
    return {
        "status": "success",
        "message": "Сбор трендовых моделей HF запущен в фоне.",
    }


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


def run_github_trending_fetch_and_save():
    try:
        run_github_trending_pipeline(limit=30)
    except Exception as e:
        print(f"[ERROR] Ошибка сбора репозиториев GitHub: {e}")


@app.post("/trending/github/refresh")
def trigger_github_trending_fetch(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_github_trending_fetch_and_save)
    return {
        "status": "success",
        "message": "Сбор трендовых репозиториев GitHub запущен в фоне.",
    }


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


@app.get("/articles")
def read_articles():
    articles_list = get_all_articles()
    return {
        "status": "success",
        "total_articles": len(articles_list),
        "data": articles_list,
    }


def run_papers_fetch_and_save():
    try:
        from papers_fetcher import ingest_papers
        ingest_papers()
    except Exception as e:
        print(f"[ERROR] Ошибка при сборе статей: {e}")


@app.post("/papers/refresh")
def trigger_papers_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_papers_fetch_and_save)
    return {
        "status": "success",
        "message": "Сбор статей запущен в фоне.",
    }


def run_datasets_fetch_and_save():
    try:
        from main import run_datasets_only
        run_datasets_only()
    except Exception as e:
        print(f"[ERROR] Ошибка при сборе датасетов: {e}")


@app.post("/datasets/refresh")
def trigger_datasets_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_datasets_fetch_and_save)
    return {
        "status": "success",
        "message": "Сбор датасетов запущен в фоне.",
    }


class RagChatRequest(BaseModel):
    messages: list[dict] = Field(default_factory=list, description="История диалога")
    category: str = Field(default="all", description="Категория: all, датасет, модель, репозиторий, статья")
    max_sources: int = Field(default=5, ge=1, le=20, description="Количество карточек в рекомендации")
    top_k: int | None = Field(default=None, ge=1, le=20, description="Алиас для обратной совместимости")
    card_context: dict | None = Field(default=None, description="Контекст конкретной карточки при вызове из интерфейса")


@app.post("/rag/chat")
def rag_chat_endpoint(req: RagChatRequest):
    try:
        limit = req.top_k if req.top_k is not None else req.max_sources
        res = rag_agent.process_dialogue(
            history=req.messages,
            category_filter=req.category,
            max_sources=limit,
            card_context=req.card_context,
        )
        return {"status": "success", "data": res}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}


@app.get("/rag/stats")
def rag_stats_endpoint():
    try:
        stats = rag_service.get_catalog_stats()
        return {"status": "success", "data": stats}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": {}}


@app.post("/rag/reindex")
def rag_reindex_endpoint():
    try:
        count = rag_service.build_index(force=True)
        return {"status": "success", "indexed_count": count}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class IntelQueryRequest(BaseModel):
    prompt: str
    category: str = "all"
    max_sources: int = 5
    top_k: int | None = None
    card_context: dict | None = None


@app.post("/api/v1/rag/query")
def api_v1_rag_query(req: IntelQueryRequest):
    try:
        limit = req.top_k if req.top_k is not None else req.max_sources
        res = rag_agent.process_dialogue(
            history=[{"role": "user", "content": req.prompt}],
            category_filter=req.category,
            max_sources=limit,
            card_context=req.card_context,
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
            "cards": cards,
        }
    except Exception as e:
        return {
            "status": "error",
            "answer": f"Ошибка обработки RAG-запроса: {e}",
            "sources": [],
            "cards": [],
        }


@app.post("/api/v1/radar/sync")
def api_v1_radar_sync(background_tasks: BackgroundTasks):
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
            "message": "Радарное сканирование запущено: Hugging Face, GitHub, ArXiv и обновление RAG-индекса.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/radar/telemetry")
def api_v1_radar_telemetry():
    import httpx
    import config
    import database

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
            },
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


dist_path = os.path.join(os.path.dirname(__file__), "web", "dist")
if os.path.isdir(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")
