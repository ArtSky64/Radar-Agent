import asyncio
import json
import logging
import httpx
from datetime import datetime
import config

logger = logging.getLogger("hf_trending_fetcher")

async def _fetch_models(client, url):
    try:
        resp = await client.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return []

async def _fetch_model_card(client, model_id):
    url = f"https://huggingface.co/api/models/{model_id}"
    try:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug(f"Error fetching card for {model_id}: {e}")
        return {}

async def fetch_trending_models_async(limit: int = 30) -> list[dict]:
    # TZ Block 4: GET /api/models?sort=trendingScore&direction=-1
    #             GET /api/models?sort=trendingScore&direction=-1&filter=ru
    async with httpx.AsyncClient(trust_env=False) as client:
        base_url = "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=50"
        
        # Parallel fetch modes
        tasks = [
            _fetch_models(client, base_url),
        ]
        if "trending_ru" in config.HF_MODEL_MODES:
            tasks.append(_fetch_models(client, base_url + "&filter=ru"))
            
        results = await asyncio.gather(*tasks)
        
        # Merge by id
        merged = {}
        for idx, dataset_list in enumerate(results):
            variant = "" if idx == 0 else "ru"
            for item in dataset_list:
                m_id = item.get("id") or item.get("modelId")
                if not m_id: continue
                if m_id not in merged:
                    merged[m_id] = item
                    merged[m_id]["_variant"] = variant
                elif variant:
                    merged[m_id]["_variant"] += f",{variant}"
                    
        # Sort back by downloads/likes or just take top N
        models_list = list(merged.values())
        models_list.sort(key=lambda x: x.get("downloads", 0), reverse=True)
        models_list = models_list[:limit]
        
        final_models = []
        from agent_manager import summarize_trending_model, AnalysisError
        
        # Fetch full cards
        for item in models_list:
            m_id = item.get("id") or item.get("modelId")
            card_data = await _fetch_model_card(client, m_id)
            
            downloads = item.get("downloads", 0)
            likes = item.get("likes", 0)
            tags = item.get("tags", [])
            pipeline_tag = card_data.get("pipeline_tag", item.get("pipeline_tag", ""))
            
            # extract license from tags or card_data
            license_tag = next((t.replace("license:", "") for t in tags if t.startswith("license:")), "")
            
            readme = card_data.get("cardData", {})
            if isinstance(readme, dict):
                readme_text = json.dumps(readme, ensure_ascii=False)
            else:
                readme_text = str(readme)
                
            model_info = {
                "name": m_id,
                "downloads": int(downloads),
                "likes": int(likes),
                "tags": tags[:10],
                "url": f"https://huggingface.co/{m_id}",
                "pipeline_tag": pipeline_tag,
                "license": license_tag,
                "card_description": readme_text[:3000],
                "language": "",
                "variant": item.get("_variant", "")
            }
            
            # Enrich with LLM
            try:
                model_info["summary"] = await asyncio.to_thread(
                    summarize_trending_model, 
                    m_id, 
                    model_info["tags"], 
                    model_info["card_description"]
                )
            except AnalysisError as e:
                logger.warning(f"Failed to summarize '{m_id}': {e}")
                model_info["summary"] = ""
                
            final_models.append(model_info)
            
        return final_models

def fetch_trending_models(limit: int = 30) -> list[dict]:
    return asyncio.run(fetch_trending_models_async(limit))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(fetch_trending_models(3), indent=2, ensure_ascii=False))