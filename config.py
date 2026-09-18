import os
from dotenv import load_dotenv

load_dotenv()

# --- Локальная модель (vLLM, OpenAI-совместимый API) ---
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:2233/v1")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen3.6-27B")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "not-needed")

# --- Дедупликация / векторы ---
DUPLICATE_THRESHOLD = float(os.getenv("DUPLICATE_THRESHOLD", "0.59"))
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "384"))

# --- Логирование ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "app.log")
ERROR_LOG_FILE = os.getenv("ERROR_LOG_FILE", "errors.log")

# --- База данных ---
DB_NAME = os.getenv("DB_NAME", "app_database.db")