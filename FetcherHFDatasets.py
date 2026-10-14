import asyncio
import json
import logging
import httpx
from datetime import datetime, timezone
import config
from pydantic import BaseModel, Field
import re

try:
    from pydantic_ai import Agent
    from agent_manager import get_model
except ImportError:
    Agent = None
    def get_model(): return None

logger = logging.getLogger("hf_datasets_fetcher")

class SelectedDataset(BaseModel):
    id: str = Field(description="ID")
    russian_translation: str = Field(description="Summary in Russian")

class SelectionResult(BaseModel):
    selected_datasets: list[SelectedDataset] = Field(description="Selected datasets")

def _get_hf_dataset_agent() -> Agent:
    return Agent(
        model=get_model(),
        output_type=SelectionResult,
        system_prompt=(
            "Ты — Senior ML Engineer. Тебе дают список новых или популярных "
            "датасетов (id, title, full_text). Отбери самые ценные. "
            "Напиши russian_translation: краткое описание на русском."
        )
    )

def clean_hf_readme(text: str) -> str:
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"^[#]+\s+", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "").replace("*", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

async def fetch_dataset_readme_directly(dataset_id: str) -> str:
    url = f"https://huggingface.co/datasets/{dataset_id.strip()}/raw/main/README.md"
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            response = await client.get(url, follow_redirects=True)
            if response.status_code == 200:
                return response.text
    except Exception as e:
        logger.debug(f"Failed to fetch readme for {dataset_id}: {e}")
    return ""

async def fetch_hf_datasets_by_mode(mode: str) -> list[dict]:
    articles_payload = []
    base_url = "https://huggingface.co/api/datasets"
    
    if mode == "query":
        url = f"{base_url}?search=machine%20learning&limit=20"
    elif mode == "recent":
        url = f"{base_url}?sort=lastModified&direction=-1&limit=20"
    elif mode == "trending":
        url = f"{base_url}?sort=trendingScore&direction=-1&limit=20"
    elif mode == "trending_ru":
        url = f"{base_url}?sort=trendingScore&direction=-1&limit=30&filter=language:ru"
    else:
        logger.warning(f"Unknown mode: {mode}")
        return []

    logger.info(f"Fetching HF Datasets (mode={mode})...")
    
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(url, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            
            all_candidates = []
            for item in data:
                d_id = item.get("id")
                if not d_id: continue
                
                raw_readme = await fetch_dataset_readme_directly(d_id)
                if not raw_readme: continue
                clean_text = clean_hf_readme(raw_readme)
                if len(clean_text) < 50: continue
                
                tags = item.get("tags", [])
                langs = [t.replace("language:", "") for t in tags if t.startswith("language:")]
                
                all_candidates.append({
                    "id": f"hf_dataset:{d_id}",
                    "title": d_id,
                    "full_text": clean_text,
                    "url": f"https://huggingface.co/datasets/{d_id}",
                    "language": ", ".join(langs)
                })
            
            if not all_candidates:
                return []
                
            llm_input = [
                {"id": c["id"], "title": c["title"], "full_text": c["full_text"][:2500]} 
                for c in all_candidates[:10]
            ]
            
            prompt = "Кандидаты:\n" + json.dumps(llm_input, ensure_ascii=False)
            agent = _get_hf_dataset_agent()
            if not agent:
                return []
            result = await agent.run(prompt)
            
            candidates_by_id = {c["id"]: c for c in all_candidates}
            for res_item in result.output.selected_datasets:
                original = candidates_by_id.get(res_item.id)
                if not original: continue
                
                articles_payload.append({
                    "title": f"[HF Dataset] {original['title']}",
                    "text": f"Датасет: {original['title']}\n\nОписание:\n{res_item.russian_translation}",
                    "source_url": original["url"],
                    "language": original.get("language", ""),
                })
                
    except Exception as e:
        logger.error(f"Error in mode {mode}: {e}")
        
    return articles_payload

def stream_hf_datasets_by_mode(mode: str):
    articles = asyncio.run(fetch_hf_datasets_by_mode(mode))
    for article in articles:
        yield article

def stream_hf_datasets(query: str = "machine learning"):
    """Алиас для обратной совместимости со старыми тестами и вызовами."""
    yield from stream_hf_datasets_by_mode("query")
