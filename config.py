import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Корень проекта и папка data/ ---
# Всегда абсолютный путь к директории, где лежит этот файл (config.py).
# Благодаря этому DB и логи создаются в правильном месте независимо от CWD.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# --- Локальная модель (vLLM, OpenAI-совместимый API) ---
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:2233/v1")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen3.6-27B")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "not-needed")

# --- Дедупликация / векторы ---
DUPLICATE_THRESHOLD = float(os.getenv("DUPLICATE_THRESHOLD", "0.59"))
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "384"))

def _abs_data_path(env_var: str, default_name: str) -> str:
    """
    Читает путь из env-переменной.
    - Абсолютный путь → используем как есть.
    - Относительный (в т.ч. просто 'app_database.db') → кладём в DATA_DIR.
    """
    raw = os.getenv(env_var, "")
    if not raw:
        return os.path.join(DATA_DIR, default_name)
    if os.path.isabs(raw):
        return raw
    # Убираем возможный data/ префикс, чтобы не получить data/data/...
    basename = os.path.basename(raw)
    return os.path.join(DATA_DIR, basename)

# --- Логирование ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE       = _abs_data_path("LOG_FILE",       "app.log")
ERROR_LOG_FILE = _abs_data_path("ERROR_LOG_FILE", "errors.log")

# --- База данных ---
DB_NAME = _abs_data_path("DB_NAME", "app_database.db")

# --- Papers (HF Papers + Papers with Code) ---
PWC_MCP_URL = os.getenv("PWC_MCP_URL", "https://gateway.pipeworx.io/paperswithcode/mcp")
PWC_TRENDING_TOOL = os.getenv("PWC_TRENDING_TOOL", "trending_papers")
PWC_DETAIL_TOOL = os.getenv("PWC_DETAIL_TOOL", "get_paper")
PWC_TOPIC_SLUGS = ["healthcare", "medical-imaging", "biology"]
PAPERS_WINDOW_DAYS = int(os.getenv("PAPERS_WINDOW_DAYS", "7"))
PAPERS_LIMIT = int(os.getenv("PAPERS_LIMIT", "10"))

# --- GitHub & HuggingFace ---
GITHUB_TRENDING_PERIODS = ["daily", "weekly", "monthly"]
HF_DATASET_MODES = ["query", "recent", "trending", "trending_ru"]
HF_MODEL_MODES = ["trending", "trending_ru"]
