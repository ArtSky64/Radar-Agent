export type NavigationTab =
  | 'leaderboard'
  | 'hf_global'
  | 'hf_ru'
  | 'papers'
  | 'datasets'
  | 'repositories'
  | 'rag';

export interface LeaderboardRecord {
  model_name: string;
  rating: number;
  category: string;
  categories?: string[];
  fetched_at?: string;
  organization?: string;
  license?: string;
  vote_count?: number;
  summary?: string;
}

export interface HFModelItem {
  rowid?: number;
  model_name: string;
  name?: string;
  downloads: number;
  likes: number;
  tags?: string[] | string;
  source_url?: string;
  url?: string;
  summary?: string;
  card_description?: string;
  fetched_at?: string;
  pipeline_tag?: string;
  license?: string;
  language?: string;
  variant?: string;
  directions?: string[];
  task_types?: string[];
  parameters?: string;
  rank_global?: number;
  rank_ru?: number;
  trending_score?: number;
}

export interface RelatedLink {
  type?: string;
  url?: string;
  name?: string;
  count?: number;
  top_items?: string[];
}

export interface ArticleItem {
  rowid?: number;
  title?: string;
  repo_name?: string;
  summary?: string;
  source_url?: string;
  url?: string;
  tags?: string[] | string;
  source_type?: 'статья' | 'датасет' | 'репозиторий' | string;
  language?: string;
  topic_tag?: string;
  related_links?: RelatedLink[];
  source_article_url?: string;
  period?: 'weekly' | 'monthly' | string;
  directions?: string[];
  task_types?: string[];
  stars?: number;
  upvotes?: number;
  is_trending?: boolean;
  has_code?: boolean;
  added_at?: string;
  has_spaces?: boolean;
  rank_global?: number;
  rank_ru?: number;
  is_new?: boolean;
}

export interface RepoItem {
  rowid?: number;
  repo_name: string;
  stars: number;
  forks?: number;
  tags?: string[] | string;
  url?: string;
  summary?: string;
  description?: string;
  fetched_at?: string;
  language?: string;
  directions?: string[];
  task_types?: string[];
  is_new?: boolean;
  period?: string;
}

export interface AnalysisRecord {
  rowid?: number;
  fetched_at: string;
  analysis_text: string;
}

export interface RAGCard {
  id?: string;
  title: string;
  url: string;
  category: 'датасет' | 'модель' | 'репозиторий' | 'статья' | string;
  summary?: string;
  tags?: string[];
  metrics?: {
    stars?: number;
    downloads?: number;
    likes?: number;
  };
}

// Словари направлений и типов задач из config.py
export const HF_DIRECTIONS: Record<string, string> = {
  health_ai: 'Медицинский AI, биоинформатика, анализ биосигналов',
  cv: 'Computer Vision, обработка изображений и видео',
  audio: 'Аудиоанализ, распознавание и синтез речи',
  nlp_llm: 'NLP, LLM, языковые и текстовые модели',
  generative_ai: 'Генерация изображений, звука, мультимодальные модели',
  classical_ml: 'Классический ML: табличные данные, временные ряды',
  robotics: 'Робототехника, управление движением и датчиками',
};

export const HF_TASK_TYPES: Record<string, string> = {
  classification: 'Классификация объектов, текстов, аудио',
  regression: 'Регрессия, прогнозирование числовых показателей',
  clustering: 'Кластеризация, эмбеддинги, поиск аномалий без разметки',
  detection_tracking: 'Детекция и отслеживание объектов на изображениях/видео',
  segmentation: 'Сегментация изображений и видео',
  generation: 'Генерация синтетических данных и мультимодального контента',
  recognition: 'Распознавание образов, жестов, речи',
  reinforcement_learning: 'Обучение с подкреплением (RL), принятие решений',
  anomaly_detection: 'Поиск аномалий и выбросов в данных',
};

export const GITHUB_DIRECTIONS: Record<string, string> = {
  health_ai: 'Медицинский AI, биоинформатика',
  cv: 'Computer Vision, обработка изображений',
  audio: 'Аудио, речь, обработка звука',
  nlp_llm: 'NLP, большие языковые модели (LLM)',
  agents: 'ИИ-агенты, мультиагентные системы',
  generative_ai: 'Генеративные модели, синтез данных',
  classical_ml: 'Классический машинный анализ данных',
  robotics: 'Робототехника, управление движением',
  ml_infrastructure: 'MLOps, инференс, оптимизация вычислений',
};

export const GITHUB_TASK_TYPES: Record<string, string> = {
  classification: 'Классификация и категоризация',
  regression: 'Регрессия и прогнозирование',
  clustering: 'Кластеризация и векторный поиск',
  detection_tracking: 'Детекция и трекинг объектов',
  segmentation: 'Сегментация',
  generation: 'Генерация контента',
  recognition: 'Распознавание образов и речи',
  reinforcement_learning: 'Обучение с подкреплением',
  anomaly_detection: 'Детекция аномалий',
};
