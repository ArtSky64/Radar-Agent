import React, { useState, useEffect, useMemo } from 'react';
import {
  Flame,
  Cpu,
  Globe2,
  FileText,
  Database,
  GitFork,
  Bot,
  RotateCw,
  Activity,
  Layers,
  Sparkles,
  Search,
} from 'lucide-react';
import { StudioSidebar } from './components/studio/StudioSidebar';
import { LeaderboardSection } from './components/views/LeaderboardSection';
import { HFModelsSection } from './components/views/HFModelsSection';
import { PapersSection } from './components/views/PapersSection';
import { DatasetsSection } from './components/views/DatasetsSection';
import { RepositoriesSection } from './components/views/RepositoriesSection';
import { RAGSection } from './components/views/RAGSection';
import { FluidAuroraCanvas } from './components/background/FluidAuroraCanvas';
import { IntelligenceOrb } from './components/ui/IntelligenceOrb';
import type {
  NavigationTab,
  LeaderboardRecord,
  HFModelItem,
  ArticleItem,
  RepoItem,
  AnalysisRecord,
} from './types/domain';
import type { RadarTelemetry } from './types/intel';
import { buildLatestRecords } from './utils/leaderboard';

export default function App() {
  const [activeTab, setActiveTab] = useState<NavigationTab>('leaderboard');

  // Данные лидерборда Arena
  const [leaderboardRecords, setLeaderboardRecords] = useState<LeaderboardRecord[]>([]);
  const [latestAnalysis, setLatestAnalysis] = useState<AnalysisRecord | null>(null);
  const [leaderboardLastFetchedAt, setLeaderboardLastFetchedAt] = useState<string | null>(null);
  const [isLeaderboardRefreshing, setIsLeaderboardRefreshing] = useState(false);

  // Данные моделей Hugging Face
  const [hfModels, setHfModels] = useState<HFModelItem[]>([]);
  const [hfLastFetchedAt, setHfLastFetchedAt] = useState<string | null>(null);
  const [isHfRefreshing, setIsHfRefreshing] = useState(false);

  // Данные статей и датасетов
  const [articles, setArticles] = useState<ArticleItem[]>([]);
  const [isPapersRefreshing, setIsPapersRefreshing] = useState(false);
  const [isDatasetsRefreshing, setIsDatasetsRefreshing] = useState(false);

  // Данные репозиториев GitHub
  const [githubRepos, setGithubRepos] = useState<(RepoItem | ArticleItem)[]>([]);
  const [githubLastFetchedAt, setGithubLastFetchedAt] = useState<string | null>(null);
  const [isGithubRefreshing, setIsGithubRefreshing] = useState(false);

  // Телеметрия и синхронизация
  const [telemetry, setTelemetry] = useState<RadarTelemetry | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isReindexing, setIsReindexing] = useState(false);

  // Загрузка лидерборда и анализа
  const fetchLeaderboard = async () => {
    try {
      const [resArena, resAnalysis] = await Promise.allSettled([
        fetch('/leaderboard'),
        fetch('/leaderboard/analysis'),
      ]);

      if (resArena.status === 'fulfilled' && resArena.value.ok) {
        const json = await resArena.value.json();
        if (json.status === 'success' && Array.isArray(json.data)) {
          const records = buildLatestRecords(json.data);
          setLeaderboardRecords(records);
          if (records.length > 0 && records[0].fetched_at) {
            setLeaderboardLastFetchedAt(records[0].fetched_at);
          }
        }
      }

      if (resAnalysis.status === 'fulfilled' && resAnalysis.value.ok) {
        const json = await resAnalysis.value.json();
        if (json.status === 'success' && Array.isArray(json.data) && json.data.length > 0) {
          setLatestAnalysis(json.data[0]);
        }
      }
    } catch (e) {
      console.warn('Leaderboard fetch error:', e);
    }
  };

  // Загрузка моделей HF
  const fetchTrendingModels = async () => {
    try {
      const res = await fetch('/trending/models');
      if (res.ok) {
        const json = await res.json();
        if (json.status === 'success' && Array.isArray(json.data)) {
          setHfModels(json.data);
          setHfLastFetchedAt(json.last_fetched_at || (json.data[0]?.fetched_at ?? null));
        }
      }
    } catch (e) {
      console.warn('HF models fetch error:', e);
    }
  };

  // Загрузка статей и датасетов
  const fetchArticles = async () => {
    try {
      const res = await fetch('/articles');
      if (res.ok) {
        const json = await res.json();
        if (json.status === 'success' && Array.isArray(json.data)) {
          setArticles(json.data);
        }
      }
    } catch (e) {
      console.warn('Articles fetch error:', e);
    }
  };

  // Загрузка трендов GitHub
  const fetchGithub = async () => {
    try {
      const res = await fetch('/trending/github');
      if (res.ok) {
        const json = await res.json();
        if (json.status === 'success' && Array.isArray(json.data)) {
          setGithubRepos(json.data);
          setGithubLastFetchedAt(json.last_fetched_at || null);
        }
      }
    } catch (e) {
      console.warn('GitHub fetch error:', e);
    }
  };

  // Загрузка телеметрии
  const fetchTelemetry = async () => {
    try {
      const t0 = performance.now();
      const res = await fetch('/api/v1/radar/telemetry');
      const t1 = performance.now();
      if (res.ok) {
        const json = await res.json();
        if (json.status === 'success') {
          setTelemetry({
            ...json,
            ping_ms: Math.round(t1 - t0),
          });
        }
      }
    } catch (e) {
      console.warn('Telemetry fetch error:', e);
    }
  };

  // Первоначальная загрузка всех данных
  useEffect(() => {
    fetchLeaderboard();
    fetchTrendingModels();
    fetchArticles();
    fetchGithub();
    fetchTelemetry();

    const interval = setInterval(fetchTelemetry, 15000);
    return () => clearInterval(interval);
  }, []);

  // Синхронизация всех источников через единый pipeline
  const handleForceScan = async () => {
    if (isSyncing) return;
    setIsSyncing(true);
    try {
      await fetch('/api/v1/radar/sync', { method: 'POST' });
      setTimeout(async () => {
        await Promise.all([
          fetchLeaderboard(),
          fetchTrendingModels(),
          fetchArticles(),
          fetchGithub(),
          fetchTelemetry(),
        ]);
      }, 3500);
    } catch (e) {
      console.warn('Sync error:', e);
    } finally {
      setTimeout(() => setIsSyncing(false), 2000);
    }
  };

  // Ручные обновления разделов
  const handleRefreshArena = async () => {
    setIsLeaderboardRefreshing(true);
    try {
      await fetch('/scrape', { method: 'POST' });
      setTimeout(fetchLeaderboard, 2000);
    } finally {
      setTimeout(() => setIsLeaderboardRefreshing(false), 1500);
    }
  };

  const handleRefreshHf = async () => {
    setIsHfRefreshing(true);
    try {
      await fetch('/trending/refresh', { method: 'POST' });
      setTimeout(fetchTrendingModels, 2000);
    } finally {
      setTimeout(() => setIsHfRefreshing(false), 1500);
    }
  };

  const handleRefreshPapers = async () => {
    setIsPapersRefreshing(true);
    try {
      await fetch('/papers/refresh', { method: 'POST' });
      setTimeout(fetchArticles, 2000);
    } finally {
      setTimeout(() => setIsPapersRefreshing(false), 1500);
    }
  };

  const handleRefreshDatasets = async () => {
    setIsDatasetsRefreshing(true);
    try {
      await fetch('/datasets/refresh', { method: 'POST' });
      setTimeout(fetchArticles, 2000);
    } finally {
      setTimeout(() => setIsDatasetsRefreshing(false), 1500);
    }
  };

  const handleRefreshGithub = async () => {
    setIsGithubRefreshing(true);
    try {
      await fetch('/trending/github/refresh', { method: 'POST' });
      setTimeout(fetchGithub, 2000);
    } finally {
      setTimeout(() => setIsGithubRefreshing(false), 1500);
    }
  };

  const handleReindex = async () => {
    if (isReindexing) return;
    setIsReindexing(true);
    try {
      await fetch('/rag/reindex', { method: 'POST' });
      await fetchTelemetry();
    } finally {
      setIsReindexing(false);
    }
  };

  // Подсчёт элементов для сайдбара
  const counts = useMemo(() => {
    const ruModelsCount = hfModels.filter(
      (m) =>
        (m.rank_ru || 0) > 0 ||
        (m.language || '').toLowerCase().includes('ru') ||
        (Array.isArray(m.tags) && m.tags.includes('#Russian'))
    ).length;

    const papersCount = articles.filter(
      (a) =>
        (a.source_type === 'статья' || (!a.source_type && !a.repo_name)) &&
        !(a.summary || '').startsWith('Связанный материал к статье:')
    ).length;

    const datasetsCount = articles.filter(
      (a) =>
        a.source_type === 'датасет' &&
        !(a.summary || '').startsWith('Связанный материал к статье:')
    ).length;

    const reposCount = githubRepos.length || articles.filter((a) => a.source_type === 'репозиторий').length;

    return {
      leaderboard: leaderboardRecords.length,
      hfGlobal: hfModels.length,
      hfRu: ruModelsCount,
      papers: papersCount,
      datasets: datasetsCount,
      repositories: reposCount,
    };
  }, [leaderboardRecords, hfModels, articles, githubRepos]);

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#0A0A0F] text-zinc-300 flex flex-col font-sans selection:bg-purple-600 selection:text-white">
      {/* Декоративный фон авроры */}
      <FluidAuroraCanvas isActive={true} />

      {/* Верхний хэдер радара */}
      <header className="h-14 shrink-0 border-b border-[#2D1B4E] bg-[#0A0A0F]/90 backdrop-blur-md px-6 flex items-center justify-between gap-4 z-20 shadow-md">
        <div className="flex items-center gap-3">
          <div className="scale-75 origin-left">
            <IntelligenceOrb />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-white tracking-wide">
                AI / ML Radar Scout
              </span>
              <span className="text-[10px] px-2 py-0.5 bg-purple-500/10 text-purple-300 rounded-md border border-purple-500/30 font-medium">
                v2.0 Radar Edition
              </span>
            </div>
            <div className="text-[10px] text-zinc-500 hidden sm:block">
              Мониторинг моделей, датасетов, научных статей и трендов ИИ в режиме реального времени
            </div>
          </div>
        </div>

        {/* Индикатор телеметрии и общая кнопка сканирования */}
        <div className="flex items-center gap-3">
          {telemetry && (
            <div className="hidden md:flex items-center gap-2 text-xs font-mono text-zinc-400 bg-[#12121A] px-3 py-1.5 rounded-xl border border-[#2D1B4E]">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>БД: {telemetry.db_size_mb} MB</span>
              <span className="text-zinc-600">│</span>
              <span className="text-purple-300">Векторы: {telemetry.vector_indexed_count ?? telemetry.vector_index_count}</span>
              <span className="text-zinc-600">│</span>
              <span className="text-amber-300">{telemetry.cosine_threshold || `${telemetry.threshold} cos`}</span>
            </div>
          )}

          <button
            onClick={handleForceScan}
            disabled={isSyncing}
            className="flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold rounded-xl bg-purple-600 hover:bg-purple-500 text-white shadow-lg shadow-purple-600/20 transition-all cursor-pointer disabled:opacity-50"
          >
            <RotateCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin' : ''}`} />
            <span>{isSyncing ? 'Синхронизация...' : 'Синхронизировать всё'}</span>
          </button>
        </div>
      </header>

      {/* Основной двухколоночный контент */}
      <div className="relative z-10 w-full flex-1 flex overflow-hidden">
        {/* Боковая панель с 7 разделами */}
        <StudioSidebar
          activeTab={activeTab}
          onTabChange={setActiveTab}
          counts={counts}
          onForceScan={handleForceScan}
          isSyncing={isSyncing}
          telemetry={telemetry}
          onRefreshTelemetry={fetchTelemetry}
          onReindex={handleReindex}
          isReindexing={isReindexing}
        />

        {/* Рабочая область выбранного раздела */}
        <main className="flex-1 h-full overflow-y-auto p-6 md:p-8 bg-[#07070B]/50">
          <div className="max-w-6xl mx-auto pb-12">
            {activeTab === 'leaderboard' && (
              <LeaderboardSection
                records={leaderboardRecords}
                lastFetchedAt={leaderboardLastFetchedAt}
                latestAnalysis={latestAnalysis}
                onRefresh={handleRefreshArena}
                isRefreshing={isLeaderboardRefreshing}
              />
            )}

            {activeTab === 'hf_global' && (
              <HFModelsSection
                models={hfModels}
                isRuTab={false}
                lastFetchedAt={hfLastFetchedAt}
                onRefresh={handleRefreshHf}
                isRefreshing={isHfRefreshing}
              />
            )}

            {activeTab === 'hf_ru' && (
              <HFModelsSection
                models={hfModels}
                isRuTab={true}
                lastFetchedAt={hfLastFetchedAt}
                onRefresh={handleRefreshHf}
                isRefreshing={isHfRefreshing}
              />
            )}

            {activeTab === 'papers' && (
              <PapersSection
                articles={articles}
                onRefresh={handleRefreshPapers}
                isRefreshing={isPapersRefreshing}
              />
            )}

            {activeTab === 'datasets' && (
              <DatasetsSection
                articles={articles}
                onRefresh={handleRefreshDatasets}
                isRefreshing={isDatasetsRefreshing}
              />
            )}

            {activeTab === 'repositories' && (
              <RepositoriesSection
                repositories={githubRepos}
                lastFetchedAt={githubLastFetchedAt}
                onRefresh={handleRefreshGithub}
                isRefreshing={isGithubRefreshing}
              />
            )}

            {activeTab === 'rag' && <RAGSection />}
          </div>
        </main>
      </div>
    </div>
  );
}
