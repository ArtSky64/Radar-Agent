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
PAPERS_WINDOW_DAYS = int(os.getenv("PAPERS_WINDOW_DAYS", "30"))
PAPERS_LIMIT_HF = int(os.getenv("PAPERS_LIMIT_HF", "30"))
PAPERS_LIMIT_PWC = int(os.getenv("PAPERS_LIMIT_PWC", "30"))
PAPERS_LIMIT = int(os.getenv("PAPERS_LIMIT", "60"))

# --- GitHub & HuggingFace ---
GITHUB_TRENDING_PERIODS = ["daily", "weekly", "monthly"]
GITHUB_TRENDING_URLS = [
    "https://github.com/trending/python?since=weekly",
    "https://github.com/trending/python?since=monthly",
]
GITHUB_TRENDING_LIMIT = 30

# Фиксированные списки тегов согласно ТЗ
GITHUB_DIRECTIONS = {
    "health_ai": "Медицинский AI, биомедицина, анализ медицинских данных",
    "cv": "Computer Vision, анализ изображений и видео",
    "audio": "Распознавание, генерация и обработка аудио",
    "nlp_llm": "NLP, LLM, обработка и генерация текста",
    "agents": "AI-агенты, мультиагентные системы",
    "generative_ai": "Генерация изображений, видео, аудио, синтетических данных",
    "classical_ml": "Классическое ML: классификация, регрессия, кластеризация",
    "robotics": "Робототехника, автономные системы",
    "ml_infrastructure": "MLOps, инференс, обучение, оптимизация и развёртывание моделей",
    "backend": "API, серверные приложения, интеграции",
    "data_engineering": "Пайплайны данных, ETL, разметка, хранение и обработка датасетов",
}
GITHUB_MAX_DIRECTIONS = 4

GITHUB_TASK_TYPES = {
    "classification": "Классификация объектов, текстов, изображений, аудио",
    "regression": "Регрессия, предсказание непрерывных значений, forecasting, временные ряды",
    "clustering": "Кластеризация, поиск закономерностей, понижение размерности, embeddings",
    "detection_tracking": "Детекция и отслеживание объектов",
    "segmentation": "Сегментация изображений и видео",
    "generation": "Генерация контента и синтетических данных",
    "recognition": "Распознавание речи, звуков, текста (ASR, speaker ID, sound events)",
    "rag_search": "RAG, поиск информации, векторные БД, retrieval",
    "agent_orchestration": "Оркестрация агентов, tool calling, MCP, промпт-инжиниринг",
    "training_finetuning": "Обучение и дообучение моделей",
    "inference_optimization": "Ускорение и оптимизация инференса",
    "evaluation": "Бенчмарки, оценка качества, интерпретируемость, XAI",
    "reinforcement_learning": "RL, RLHF, обучение с подкреплением",
    "anomaly_detection": "Поиск аномалий и выбросов",
}
GITHUB_MAX_TASK_TYPES = 3

HF_DATASET_MODES = ["trending", "trending_ru"]
HF_MODEL_MODES = ["trending", "trending_ru"]

# Фиксированные списки тегов для моделей Hugging Face согласно ТЗ куратора
HF_DIRECTIONS = {
    "health_ai": "Медицинский AI, биомедицина, анализ медицинских данных",
    "cv": "Computer Vision, анализ изображений и видео",
    "audio": "Распознавание, генерация и обработка аудио",
    "nlp_llm": "NLP, LLM, обработка и генерация текста",
    "generative_ai": "Генерация изображений, видео, аудио, синтетических данных",
    "classical_ml": "Классическое ML: классификация, регрессия, кластеризация",
    "robotics": "Робототехника, автономные системы",
}
HF_MAX_DIRECTIONS = 4

HF_TASK_TYPES = {
    "classification": "Классификация объектов, текстов, изображений, аудио",
    "regression": "Регрессия, предсказание непрерывных значений, forecasting, временные ряды",
    "clustering": "Кластеризация, поиск закономерностей, понижение размерности, embeddings",
    "detection_tracking": "Детекция и отслеживание объектов",
    "segmentation": "Сегментация изображений и видео",
    "generation": "Генерация контента и синтетических данных",
    "recognition": "Распознавание речи, звуков, текста (ASR, speaker ID, sound events)",
    "reinforcement_learning": "RL, RLHF, обучение с подкреплением",
    "anomaly_detection": "Поиск аномалий и выбросов",
}
HF_MAX_TASK_TYPES = 3

HF_TRENDING_URL_GENERAL = "https://huggingface.co/models?sort=trending"
HF_TRENDING_URL_RU_1 = "https://huggingface.co/models?language=ru&sort=trending"
HF_TRENDING_URL_RU_2 = "https://huggingface.co/models?language=rus&sort=trending"
HF_TRENDING_LIMIT = 50


