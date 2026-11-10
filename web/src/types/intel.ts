export type TabType = 'All Stream' | 'Models' | 'Research' | 'GitHub' | 'Arena';
export type TopicFilter = 'ALL' | 'Reasoning' | 'Coding' | 'Inference' | 'Vision';
export type SortMode = 'trending' | 'metrics';

export interface ChatMessage {
  id: string;
  role: 'assistant' | 'user';
  content: string;
  thinking?: string;
  sources?: { title: string; url: string }[];
  timestamp: string;
}

export interface IntelItem {
  id: string;
  title: string;
  source: 'HuggingFace' | 'GitHub' | 'ArXiv' | 'LMSys Arena';
  category: string;
  topic: 'Reasoning' | 'Coding' | 'Inference' | 'Vision' | 'Benchmark';
  organization: string;
  metricLabel: string;
  metricValue: string;
  metricNumber?: number; // для числовой сортировки
  license?: string;
  summary: string;
  url: string;
  timestamp: string;
  insights?: string[];
  architecture?: string;
  arenaElo?: number;
  sparkline?: number[];
  delta?: string;
}

export interface RadarTelemetry {
  threshold: number;
  cosine_threshold?: string | number;
  vector_dim: number;
  vector_index_count: number;
  vector_indexed_count?: number;
  db_size_mb: number;
  db_total_records: number;
  total_records?: number;
  counts: {
    models: number;
    github: number;
    research: number;
    arena: number;
    total: number;
  };
  llm: {
    model: string;
    status: 'ONLINE' | 'OFFLINE';
    base_url: string;
  };
  last_fetched?: {
    hf?: string | null;
    github?: string | null;
  };
  ping_ms?: number;
}


