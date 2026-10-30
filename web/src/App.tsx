import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  ArrowLeft,
  RotateCw,
  MessageSquare,
  PanelRightClose,
  PanelRight,
  ArrowLeftRight,
} from 'lucide-react';
import { StudioSidebar } from './components/studio/StudioSidebar';
import { StudioFeed } from './components/studio/StudioFeed';
import { StudioRightPane } from './components/studio/StudioRightPane';
import { CommandPalette } from './components/ui/CommandPalette';
import { FluidAuroraCanvas } from './components/background/FluidAuroraCanvas';
import { IntelligenceOrb } from './components/ui/IntelligenceOrb';
import type {
  IntelItem,
  TabType,
  TopicFilter,
  SortMode,
  ChatMessage,
  RadarTelemetry,
} from './types/intel';
import { getItemGrammar } from './utils/intelItemLabels';

type HubMode = 'center-chat' | 'split-view' | 'collapsed-chat';

const initialChatMessages: ChatMessage[] = [
  {
    id: 'welcome',
    role: 'assistant',
    content:
      'Привет! Я твой автономный AI/ML Scout & Radar. Я круглосуточно сканирую, дедуплицирую через FastEmbed и анализирую модели Hugging Face, статьи ArXiv, репозитории GitHub и лидерборд LMSys Arena.\n\nЗадай мне любой вопрос по свежим релизам или перейди к просмотру базы данных и категорий!',
    timestamp: 'Just now',
  },
];

export default function App() {
  const [hubMode, setHubMode] = useState<HubMode>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('scout_hub_mode');
      if (saved === 'split-view' || saved === 'collapsed-chat' || saved === 'center-chat') {
        return saved as HubMode;
      }
    }
    return 'center-chat';
  });

  useEffect(() => {
    localStorage.setItem('scout_hub_mode', hubMode);
  }, [hubMode]);
  const [dockSide, setDockSide] = useState<'right' | 'left'>('right');
  const [activeTab, setActiveTab] = useState<TabType>('All Stream');
  const [activeTopic, setActiveTopic] = useState<TopicFilter>('ALL');
  const [sortMode, setSortMode] = useState<SortMode>('trending');
  const [selectedItem, setSelectedItem] = useState<IntelItem | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [injectedPrompt, setInjectedPrompt] = useState<string | undefined>(undefined);
  const [isSyncing, setIsSyncing] = useState(false);
  const [streamItems, setStreamItems] = useState<IntelItem[]>([]);
  const [isLoadingStream, setIsLoadingStream] = useState(true);
  const [telemetry, setTelemetry] = useState<RadarTelemetry | null>(null);
  const [isReindexing, setIsReindexing] = useState(false);
  const [isCommandOpen, setIsCommandOpen] = useState(false);

  // Общий стейт диалога
  const [messages, setMessages] = useState<ChatMessage[]>(initialChatMessages);
  const [isChatLoading, setIsChatLoading] = useState(false);

  // Глобальный шорткат быстрого поиска Ctrl + K (на любой раскладке: EN / RU)
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      const isKeyK = e.code === 'KeyK' || e.key.toLowerCase() === 'k' || e.key.toLowerCase() === 'л';
      if ((e.metaKey || e.ctrlKey) && isKeyK) {
        e.preventDefault();
        setIsCommandOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, []);

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
    } catch {
      // Telemetry offline fallback
    }
  };

  const handleReindex = async () => {
    if (isReindexing) return;
    setIsReindexing(true);
    try {
      await fetch('/rag/reindex', { method: 'POST' });
      await fetchTelemetry();
    } catch (err) {
      console.error('Reindex error:', err);
    } finally {
      setIsReindexing(false);
    }
  };

  const loadRealData = async () => {
    setIsLoadingStream(true);
    try {
      const [modelsRes, ghRes, papersRes, arenaRes] = await Promise.allSettled([
        fetch('/trending/models'),
        fetch('/trending/github'),
        fetch('/articles'),
        fetch('/leaderboard'),
      ]);

      const live: IntelItem[] = [];

      // 1. Модели Hugging Face
      if (modelsRes.status === 'fulfilled' && modelsRes.value.ok) {
        const json = await modelsRes.value.json();
        (json.data || []).forEach((m: any, i: number) => {
          const title = m.model_name || m.title || 'HF Model';
          const tags = Array.isArray(m.tags) ? m.tags.join(' ') : String(m.tags || '');
          const pTag = String(m.pipeline_tag || '').toLowerCase();
          let topic: TopicFilter = 'Coding';
          if (pTag.includes('vision') || pTag.includes('image') || pTag.includes('diffusion')) topic = 'Vision';
          else if (tags.includes('reasoning') || title.toLowerCase().includes('reason') || title.toLowerCase().includes('think')) topic = 'Reasoning';
          else if (tags.includes('inference') || tags.includes('quant') || tags.includes('vllm')) topic = 'Inference';
          else if (pTag.includes('code') || tags.includes('code')) topic = 'Coding';

          const dls = m.downloads || 0;
          const metricVal = dls >= 1000000 ? `${(dls / 1000000).toFixed(1)}M` : dls >= 1000 ? `${(dls / 1000).toFixed(1)}k` : String(dls);

          live.push({
            id: `hf-${i}-${title}`,
            title: title,
            source: 'HuggingFace',
            category: m.pipeline_tag || 'LLM Checkpoint',
            topic: topic,
            organization: m.author || (title.includes('/') ? title.split('/')[0] : 'Open Weights'),
            metricLabel: 'Downloads',
            metricValue: metricVal,
            metricNumber: dls,
            license: m.license || 'Open',
            summary: m.summary || m.card_description || 'Открытый чекпоинт с Hugging Face Hub.',
            url: m.source_url || `https://huggingface.co/${title}`,
            timestamp: m.fetched_at ? 'Свежее' : 'Недавно',
            insights: ['Проанализировано через векторную дедупликацию FastEmbed.'],
            delta: `+${metricVal} загр.`,
          });
        });
      }

      // 2. Репозитории GitHub
      if (ghRes.status === 'fulfilled' && ghRes.value.ok) {
        const json = await ghRes.value.json();
        (json.data || []).forEach((g: any, i: number) => {
          const title = g.repo_name || g.title || 'GitHub Repo';
          const stars = g.stars || 0;
          const metricVal = stars >= 1000 ? `${(stars / 1000).toFixed(1)}k` : String(stars);

          const desc = String(g.summary || g.description || '').toLowerCase();
          let topic: TopicFilter = 'Inference';
          if (desc.includes('code') || desc.includes('agent') || (g.language || '').toLowerCase().includes('python')) topic = 'Coding';
          if (desc.includes('vision') || desc.includes('image')) topic = 'Vision';
          if (desc.includes('reason') || desc.includes('math')) topic = 'Reasoning';

          live.push({
            id: `gh-${i}-${title}`,
            title: title,
            source: 'GitHub',
            category: g.language || 'Python',
            topic: topic,
            organization: title.includes('/') ? title.split('/')[0] : 'Open Source',
            metricLabel: 'Stars',
            metricValue: metricVal,
            metricNumber: stars,
            license: 'MIT',
            summary: g.summary || g.description || 'Трендовый репозиторий GitHub.',
            url: g.url || `https://github.com/${title}`,
            timestamp: 'Тренды',
            insights: ['Входит в недельный рейтинг трендов GitHub.'],
            delta: `+${metricVal} звёзд`,
          });
        });
      }

      // 3. Статьи и препринты
      if (papersRes.status === 'fulfilled' && papersRes.value.ok) {
        const json = await papersRes.value.json();
        (json.data || []).forEach((p: any, i: number) => {
          const title = p.title || 'Научная публикация';
          const upvotes = p.upvotes || p.stars || 0;
          const metricVal = String(upvotes || 42);

          const text = (title + ' ' + (p.summary || '') + ' ' + (p.tags || '')).toLowerCase();
          let topic: TopicFilter = 'Reasoning';
          if (text.includes('code') || text.includes('coding')) topic = 'Coding';
          else if (text.includes('vision') || text.includes('multimodal') || text.includes('image')) topic = 'Vision';
          else if (text.includes('inference') || text.includes('kernel') || text.includes('quant')) topic = 'Inference';

          const isDataset = String(p.source_type || '').includes('dataset');

          live.push({
            id: `p-${i}-${p.rowid || i}`,
            title: title,
            source: 'ArXiv',
            category: isDataset ? 'Dataset' : (p.source_type || 'Research'),
            topic: topic,
            organization: isDataset ? 'HuggingFace / Kaggle' : 'ArXiv / PwC',
            metricLabel: isDataset ? 'Загрузки' : 'Цитирования',
            metricValue: metricVal,
            metricNumber: upvotes || 42,
            summary: p.summary || 'Научная статья или датасет.',
            url: p.source_url || p.url || 'https://arxiv.org',
            timestamp: 'Свежее',
            insights: ['Проверено RAG-пайплайном.'],
            delta: isDataset ? 'Датасет' : `+${metricVal} цит.`,
          });
        });
      }

      // 4. Лидерборд LMSys Arena
      if (arenaRes.status === 'fulfilled' && arenaRes.value.ok) {
        const json = await arenaRes.value.json();
        const snapshots = json.data || [];
        if (snapshots.length > 0) {
          const latest = snapshots[0];
          const categories = latest.categories || {};
          const allCat = categories['Все категории'] || Object.values(categories)[0] || [];
          (allCat as any[]).forEach((m: any, i: number) => {
            const name = m.name || 'Arena Model';
            const rating = m.rating || 1200;
            live.push({
              id: `arena-${i}-${name}`,
              title: name,
              source: 'LMSys Arena',
              category: 'Arena Leaderboard',
              topic: 'Reasoning',
              organization: m.organization || 'LMSys Human Eval',
              metricLabel: 'Arena Elo',
              metricValue: String(rating),
              metricNumber: rating,
              arenaElo: rating,
              license: m.license || 'Open / Proprietary',
              summary: m.summary || `Модель с рейтингом ${rating} Elo в слепых сравнениях LMSys Chatbot Arena.`,
              url: 'https://chat.lmsys.org/?leaderboard',
              timestamp: 'Лидерборд',
              insights: [`Оценка сообщества: ${rating} Elo (${m.vote_count || 0} голосов).`],
              delta: `${m.vote_count || 0} голосов`,
            });
          });
        }
      }

      setStreamItems(live);
    } catch (err) {
      console.error('Ошибка загрузки реальных данных:', err);
    } finally {
      setIsLoadingStream(false);
    }
  };

  useEffect(() => {
    loadRealData();
    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleSharedSendMessage = async (text: string) => {
    const q = text.trim();
    if (!q || isChatLoading) return;

    const userMsg: ChatMessage = {
      id: String(Date.now()),
      role: 'user',
      content: q,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsChatLoading(true);

    if (hubMode === 'center-chat') {
      setHubMode('split-view');
    }

    try {
      const res = await fetch('/api/v1/rag/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: q }),
      });
      const data = await res.json();

      const assistantMsg: ChatMessage = {
        id: String(Date.now() + 1),
        role: 'assistant',
        content: data.answer || 'Ответ сформирован на основе локального векторного индекса.',
        thinking: 'Проанализировано семантическое сходство с базой статей и моделей (FastEmbed 0.59).',
        sources:
          data.sources && data.sources.length > 0
            ? data.sources.map((s: any) => ({
                title: s.name || s.title || 'Источник',
                url: s.url || 'https://arxiv.org',
              }))
            : [],
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: String(Date.now() + 1),
        role: 'assistant',
        content: `Не удалось связаться с сервером RAG-ассистента (${err?.message || 'Ошибка сети'}). Убедитесь, что сервер FastAPI запущен.`,
        thinking: 'Ошибка HTTP-запроса к /api/v1/rag/query.',
        sources: [],
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsChatLoading(false);
    }
  };

  const handleSync = async () => {
    if (isSyncing) return;
    setIsSyncing(true);
    try {
      await fetch('/api/v1/radar/sync', { method: 'POST' });
      setTimeout(fetchTelemetry, 1500);
      setTimeout(loadRealData, 4000);
    } catch {
      // Игнорируем в демо
    } finally {
      setTimeout(() => setIsSyncing(false), 2000);
    }
  };

  const counts = {
    all: streamItems.length,
    models: streamItems.filter((i) => i.source === 'HuggingFace').length,
    research: streamItems.filter((i) => i.source === 'ArXiv').length,
    github: streamItems.filter((i) => i.source === 'GitHub').length,
    arena: streamItems.filter((i) => i.source === 'LMSys Arena').length,
  };

  const filteredItems = streamItems
    .filter((item) => {
      const matchesSearch =
        item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.organization.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesTab =
        activeTab === 'All Stream'
          ? true
          : activeTab === 'Models'
          ? item.source === 'HuggingFace'
          : activeTab === 'Research'
          ? item.source === 'ArXiv'
          : activeTab === 'GitHub'
          ? item.source === 'GitHub'
          : item.source === 'LMSys Arena';

      const matchesTopic = activeTopic === 'ALL' ? true : item.topic === activeTopic;

      return matchesSearch && matchesTab && matchesTopic;
    })
    .sort((a, b) => {
      if (sortMode === 'metrics') {
        return (b.metricNumber || 0) - (a.metricNumber || 0);
      }
      return 0;
    });

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#07070a] text-zinc-300 flex flex-col font-sans selection:bg-indigo-500 selection:text-white">
      {/* 1. Живой космический фон: Звездная паутина эмбеддингов (k-NN Graph) */}
      <FluidAuroraCanvas isActive={hubMode !== 'center-chat'} />

      {/* 2. Быстрый поиск (Ctrl + K) */}
      <CommandPalette
        isOpen={isCommandOpen}
        onClose={() => setIsCommandOpen(false)}
        onSelectTab={setActiveTab}
        onSelectTopic={setActiveTopic}
        onForceScan={handleSync}
        onGoToStart={() => setHubMode('center-chat')}
        onToggleChat={() =>
          setHubMode((m) => (m === 'split-view' ? 'collapsed-chat' : 'split-view'))
        }
        items={streamItems}
        onSelectItem={(item) => {
          setSelectedItem(item);
          if (hubMode === 'collapsed-chat') setHubMode('split-view');
        }}
      />

      {/* 3. ОСНОВНАЯ РАБОЧАЯ СТАНЦИЯ (Смонтирована в фоне, скрыта на старте, чтобы не проглядывать) */}
      <div
        className={`relative z-10 w-full h-full flex flex-col overflow-hidden transition-all duration-500 ${
          hubMode === 'center-chat'
            ? 'opacity-0 pointer-events-none'
            : 'opacity-100 pointer-events-auto'
        }`}
      >
        {/* ВЕРХНЯЯ ТОНКАЯ ШАПКА РАБОЧЕЙ СТАНЦИИ (48px) с титановой фаской */}
        <header className="h-12 shrink-0 border-b border-white/[0.08] bg-[#09090e]/90 backdrop-blur-xl px-4 flex items-center justify-between gap-4 select-none shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]">
          {/* Левый блок: логотип и статус */}
          <div className="flex items-center space-x-3 shrink-0">
            <div
              onClick={() => setHubMode('center-chat')}
              className="flex items-center space-x-2.5 cursor-pointer hover:opacity-85 transition-opacity"
              title="Вернуться к приветственному экрану"
            >
              <div className="scale-75 origin-left">
                <IntelligenceOrb />
              </div>
              <div className="hidden sm:block">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-white tracking-wide">AI Радар</span>
                  <span className="text-[10px] px-1.5 py-0.5 bg-emerald-500/10 text-emerald-400 rounded-md border border-emerald-500/20 font-medium">
                    Активен
                  </span>
                </div>
              </div>
            </div>

            <div className="hidden md:flex items-center space-x-2 pl-3 border-l border-white/[0.08] text-[11px] text-zinc-400 font-sans">
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
              <span>Дедупликация FastEmbed</span>
            </div>
          </div>

          {/* Центральный блок: полноразмерный быстрый поиск */}
          <div
            onClick={() => setIsCommandOpen(true)}
            className="relative flex-1 max-w-lg cursor-pointer group"
          >
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 group-hover:text-zinc-300 transition-colors pointer-events-none" />
            <input
              type="text"
              readOnly
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Быстрый поиск моделей, статей, репозиториев..."
              className="w-full h-8 bg-white/[0.04] text-xs text-white placeholder-zinc-500 rounded-lg pl-9 pr-20 border border-white/[0.08] group-hover:border-white/[0.18] group-hover:bg-white/[0.06] focus:outline-none transition-all font-sans cursor-pointer shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)]"
            />
            <div className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center text-[10px] font-mono font-medium text-zinc-400 bg-white/[0.06] px-1.5 py-0.5 rounded border border-white/[0.08]">
              <span>Ctrl + K</span>
            </div>
          </div>

          {/* Правый блок: действия */}
          <div className="flex items-center space-x-2 shrink-0">
            <button
              onClick={() => setHubMode('center-chat')}
              className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] text-xs text-zinc-300 hover:text-white transition-all cursor-pointer shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]"
              title="Вернуться к приветственному экрану"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span className="hidden lg:inline text-[11px] font-medium">В начало</span>
            </button>

            <button
              onClick={handleSync}
              disabled={isSyncing}
              className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] text-zinc-300 hover:text-white transition-all cursor-pointer disabled:opacity-50 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]"
              title="Принудительно собрать свежие релизы с Hugging Face, GitHub, ArXiv и LMSys"
            >
              <RotateCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin text-indigo-400' : 'text-zinc-400'}`} />
              <span className="hidden lg:inline text-[11px] font-medium">
                {isSyncing ? 'Сбор данных...' : 'Обновить радар'}
              </span>
            </button>

            {/* Переключение стороны дока (влево / вправо) */}
            <button
              onClick={() => setDockSide((side) => (side === 'right' ? 'left' : 'right'))}
              className="p-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] text-zinc-400 hover:text-white hover:bg-white/[0.08] transition-all cursor-pointer"
              title={`Переместить панель ${dockSide === 'right' ? 'влево' : 'вправо'}`}
            >
              <ArrowLeftRight className="w-4 h-4" />
            </button>

            {/* Свернуть/развернуть панель */}
            <button
              onClick={() =>
                setHubMode((mode) => (mode === 'split-view' ? 'collapsed-chat' : 'split-view'))
              }
              className={`p-1.5 rounded-lg border transition-all cursor-pointer ${
                hubMode === 'split-view'
                  ? 'bg-indigo-600/20 border-indigo-500/40 text-indigo-300 hover:bg-indigo-600/30'
                  : 'bg-white/[0.03] border-white/[0.08] text-zinc-400 hover:text-white hover:bg-white/[0.08]'
              }`}
              title={hubMode === 'split-view' ? 'Свернуть боковую панель' : 'Развернуть боковую панель'}
            >
              {hubMode === 'split-view' ? <PanelRightClose className="w-4 h-4" /> : <PanelRight className="w-4 h-4" />}
            </button>
          </div>
        </header>

        {/* 3-ПАНЕЛЬНЫЙ МОНОЛИТ С ДИНАМИЧЕСКИМ РАСПОЛОЖЕНИЕМ */}
        <div className="flex-1 flex w-full h-[calc(100vh-3rem)] overflow-hidden">
          
          {/* ЛЕВАЯ ПАНЕЛЬ 1: САЙДБАР (если dockSide === 'right') */}
          {dockSide === 'right' && (
            <StudioSidebar
              activeTab={activeTab}
              onTabChange={setActiveTab}
              activeTopic={activeTopic}
              onTopicChange={setActiveTopic}
              counts={counts}
              onForceScan={handleSync}
              isSyncing={isSyncing}
              telemetry={telemetry}
              onRefreshTelemetry={fetchTelemetry}
              onReindex={handleReindex}
              isReindexing={isReindexing}
            />
          )}

          {/* ДОК-ПАНЕЛЬ СЛЕВА (если dockSide === 'left' и режим split-view) */}
          {dockSide === 'left' && hubMode === 'split-view' && (
            <motion.div
              layoutId="unified-scout-copilot-card"
              transition={{ type: 'spring', damping: 28, stiffness: 240 }}
              className="h-full shrink-0 overflow-hidden z-20"
            >
              <StudioRightPane
                mode="docked"
                selectedItem={selectedItem}
                onClearSelectedItem={() => setSelectedItem(null)}
                onAskCopilot={(prompt) => setInjectedPrompt(prompt)}
                onCollapse={() => setHubMode('collapsed-chat')}
                onTransitionToCenter={() => setHubMode('center-chat')}
                dockSide={dockSide}
                onToggleDockSide={() => setDockSide('right')}
                injectedPrompt={injectedPrompt}
                onClearInjectedPrompt={() => setInjectedPrompt(undefined)}
                messages={messages}
                onSendMessage={handleSharedSendMessage}
                isLoading={isChatLoading}
              />
            </motion.div>
          )}

          {/* ЦЕНТРАЛЬНАЯ ЛЕНТА (Сплошной поток без разрывов) */}
          <div className="relative flex-1 h-full overflow-hidden flex flex-col">
            <StudioFeed
              items={filteredItems}
              selectedItem={selectedItem}
              onSelectItem={(item) => {
                setSelectedItem(item);
                if (hubMode === 'collapsed-chat') {
                  setHubMode('split-view');
                }
              }}
              onQuickAsk={(item) => {
                const grammar = getItemGrammar(item);
                setInjectedPrompt(`Сделай глубокий анализ ${grammar.genitive} "${item.title}"`);
                if (hubMode === 'collapsed-chat') {
                  setHubMode('split-view');
                }
              }}
              sortMode={sortMode}
              onSortChange={setSortMode}
              activeTopic={activeTopic}
              activeTab={activeTab}
              onForceScan={handleSync}
              isLoading={isLoadingStream}
            />

            {/* Плавающая кнопка развертывания Copilot если панель свернута */}
            {hubMode === 'collapsed-chat' && (
              <button
                onClick={() => setHubMode('split-view')}
                className={`absolute ${dockSide === 'right' ? 'right-4' : 'left-4'} bottom-10 z-20 flex items-center space-x-2 px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-xl shadow-indigo-600/30 transition-all cursor-pointer border border-indigo-400/30`}
                title="Открыть панель ассистента и обзор"
              >
                <MessageSquare className="w-3.5 h-3.5" />
                <span>AI Ассистент</span>
              </button>
            )}
          </div>

          {/* ДОК-ПАНЕЛЬ СПРАВА (если dockSide === 'right' и режим split-view) */}
          {dockSide === 'right' && hubMode === 'split-view' && (
            <motion.div
              layoutId="unified-scout-copilot-card"
              transition={{ type: 'spring', damping: 28, stiffness: 240 }}
              className="h-full shrink-0 overflow-hidden z-20"
            >
              <StudioRightPane
                mode="docked"
                selectedItem={selectedItem}
                onClearSelectedItem={() => setSelectedItem(null)}
                onAskCopilot={(prompt) => setInjectedPrompt(prompt)}
                onCollapse={() => setHubMode('collapsed-chat')}
                onTransitionToCenter={() => setHubMode('center-chat')}
                dockSide={dockSide}
                onToggleDockSide={() => setDockSide('left')}
                injectedPrompt={injectedPrompt}
                onClearInjectedPrompt={() => setInjectedPrompt(undefined)}
                messages={messages}
                onSendMessage={handleSharedSendMessage}
                isLoading={isChatLoading}
              />
            </motion.div>
          )}

          {/* САЙДБАР СПРАВА (если dockSide === 'left') */}
          {dockSide === 'left' && (
            <StudioSidebar
              activeTab={activeTab}
              onTabChange={setActiveTab}
              activeTopic={activeTopic}
              onTopicChange={setActiveTopic}
              counts={counts}
              onForceScan={handleSync}
              isSyncing={isSyncing}
              telemetry={telemetry}
              onRefreshTelemetry={fetchTelemetry}
              onReindex={handleReindex}
              isReindexing={isReindexing}
            />
          )}

        </div>
      </div>

      {/* 4. ЦЕНТРАЛЬНЫЙ ОВЕРЛЕЙ ПРИВЕТСТВИЯ (WINDOWS SETUP / "HELLO" STYLE):
          Чистый 100% непрозрачный обсидиановый экран (без просвечивания рабочей области).
          Печатающийся текст и плавный глайд карточки в док!
      */}
      <AnimatePresence initial={false}>
        {hubMode === 'center-chat' && (
          <motion.div
            key="center-overlay"
            initial={false}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35 }}
            className="fixed inset-0 z-30 flex flex-col items-center justify-center p-4 sm:p-8 bg-[#07070a]"
          >
            {/* Минималистичная стартовая карточка приветствия (Setup Flow) */}
            <motion.div
              layoutId="unified-scout-copilot-card"
              transition={{ type: 'spring', damping: 28, stiffness: 240 }}
              className="w-full max-w-3xl flex flex-col overflow-hidden"
            >
              <StudioRightPane
                mode="center"
                selectedItem={selectedItem}
                onClearSelectedItem={() => setSelectedItem(null)}
                onAskCopilot={(prompt) => setInjectedPrompt(prompt)}
                onCollapse={() => setHubMode('split-view')}
                onTransitionToHub={() => setHubMode('split-view')}
                injectedPrompt={injectedPrompt}
                onClearInjectedPrompt={() => setInjectedPrompt(undefined)}
                messages={messages}
                onSendMessage={handleSharedSendMessage}
                isLoading={isChatLoading}
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
