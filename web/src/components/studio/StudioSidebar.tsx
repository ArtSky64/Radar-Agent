import React from 'react';
import { Layers, Database, BookOpen, GitFork, Flame, Terminal, Radio, Activity, CheckCircle2, RotateCw } from 'lucide-react';
import type { TabType, TopicFilter, RadarTelemetry } from '../../types/intel';

interface StudioSidebarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  activeTopic: TopicFilter;
  onTopicChange: (topic: TopicFilter) => void;
  counts: {
    all: number;
    models: number;
    research: number;
    github: number;
    arena: number;
  };
  onForceScan: () => void;
  isSyncing: boolean;
  telemetry?: RadarTelemetry | null;
  onRefreshTelemetry?: () => void;
  onReindex?: () => void;
  isReindexing?: boolean;
}

export const StudioSidebar: React.FC<StudioSidebarProps> = ({
  activeTab,
  onTabChange,
  activeTopic,
  onTopicChange,
  counts,
  onForceScan,
  isSyncing,
  telemetry,
  onRefreshTelemetry,
  onReindex,
  isReindexing = false,
}) => {
  const sources: { id: TabType; label: string; icon: React.ReactNode; count: number; color: string }[] = [
    { id: 'All Stream', label: 'Все источники', icon: <Layers className="w-4 h-4 text-zinc-300" />, count: counts.all, color: 'text-zinc-300' },
    { id: 'Models', label: 'Модели Hugging Face', icon: <Database className="w-4 h-4 text-amber-400" />, count: counts.models, color: 'text-amber-400' },
    { id: 'Research', label: 'Статьи ArXiv', icon: <BookOpen className="w-4 h-4 text-purple-400" />, count: counts.research, color: 'text-purple-400' },
    { id: 'GitHub', label: 'Тренды GitHub', icon: <GitFork className="w-4 h-4 text-emerald-400" />, count: counts.github, color: 'text-emerald-400' },
    { id: 'Arena', label: 'Лидерборд LMSys', icon: <Flame className="w-4 h-4 text-sky-400" />, count: counts.arena, color: 'text-sky-400' },
  ];

  const topics: { id: TopicFilter; label: string; icon: string }[] = [
    { id: 'ALL', label: 'Все направления', icon: '✦' },
    { id: 'Reasoning', label: 'Рассуждения и логика', icon: '🧠' },
    { id: 'Coding', label: 'Кодинг и AI-агенты', icon: '💻' },
    { id: 'Inference', label: 'Инференс и оптимизация', icon: '⚡' },
    { id: 'Vision', label: 'Мультимодальность', icon: '👁️' },
  ];

  return (
    <aside className="w-64 shrink-0 h-full bg-[#09090e]/60 backdrop-blur-md border-r border-white/[0.08] flex flex-col justify-between select-none shadow-[inset_-1px_0_0_0_rgba(255,255,255,0.02)]">
      <div className="p-4 space-y-6 overflow-y-auto">
        
        {/* Раздел 1: Источники данных */}
        <div>
          <div className="px-3 mb-2 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold flex items-center justify-between">
            <span>Источники данных</span>
            <span className="text-[10px] text-zinc-500 font-mono">4 потока</span>
          </div>
          <div className="space-y-0.5">
            {sources.map((src) => {
              const isActive = activeTab === src.id;
              return (
                <button
                  key={src.id}
                  onClick={() => onTabChange(src.id)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium transition-all cursor-pointer ${
                    isActive
                      ? 'bg-white/[0.08] text-white font-semibold shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)] border border-white/[0.08]'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.03] border border-transparent'
                  }`}
                >
                  <div className="flex items-center space-x-2.5">
                    {src.icon}
                    <span>{src.label}</span>
                  </div>
                  <span className={`text-[11px] font-mono ${isActive ? 'text-white' : 'text-zinc-500'}`}>
                    {src.count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Раздел 2: Тематические фильтры */}
        <div>
          <div className="px-3 mb-2 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">
            Направления
          </div>
          <div className="space-y-0.5">
            {topics.map((t) => {
              const isTopicActive = activeTopic === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => onTopicChange(t.id)}
                  className={`w-full flex items-center justify-between px-3 py-1.5 rounded-xl text-xs font-medium transition-all cursor-pointer ${
                    isTopicActive
                      ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 font-semibold shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.03] border border-transparent'
                  }`}
                >
                  <div className="flex items-center space-x-2">
                    <span>{t.icon}</span>
                    <span>{t.label}</span>
                  </div>
                  {isTopicActive && (
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Раздел 3: Живая телеметрия и осциллограф */}
        <div>
          <div className="px-3 mb-2 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Radio className={`w-3 h-3 ${telemetry?.llm?.status === 'ONLINE' ? 'text-emerald-400' : 'text-amber-400'} animate-pulse`} />
              <span>Телеметрия радара</span>
            </div>
            <div className="flex items-center gap-1.5 font-mono text-[10px]">
              <span className={telemetry?.ping_ms != null ? 'text-emerald-400' : 'text-zinc-500'}>
                {telemetry?.ping_ms != null ? `${telemetry.ping_ms}ms` : 'online'}
              </span>
              {onRefreshTelemetry && (
                <button
                  onClick={onRefreshTelemetry}
                  title="Обновить телеметрию"
                  className="text-zinc-500 hover:text-white transition-colors cursor-pointer"
                >
                  <Activity className="w-2.5 h-2.5" />
                </button>
              )}
            </div>
          </div>

          <div className="p-3.5 rounded-2xl bg-black/50 border border-white/[0.08] space-y-3 text-[11px] font-mono shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]">
            <div className="flex justify-between items-center text-zinc-400">
              <span>Порог сходства:</span>
              <span className="text-indigo-300 font-semibold bg-indigo-500/10 px-1.5 py-0.5 rounded border border-indigo-500/20">
                {telemetry ? `${telemetry.threshold} cos` : '0.59 cos'}
              </span>
            </div>

            <div className="space-y-1.5">
              <div className="flex justify-between items-center text-zinc-400">
                <span>Векторный индекс:</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-white font-semibold">
                    {telemetry ? telemetry.vector_index_count.toLocaleString() : counts.all}
                  </span>
                  {onReindex && (
                    <button
                      onClick={onReindex}
                      disabled={isReindexing}
                      title="Переиндексировать векторную базу знаний"
                      className="p-1 rounded bg-white/[0.05] hover:bg-white/[0.1] text-zinc-400 hover:text-white transition-all cursor-pointer disabled:opacity-50"
                    >
                      <RotateCw className={`w-2.5 h-2.5 ${isReindexing ? 'animate-spin text-indigo-400' : ''}`} />
                    </button>
                  )}
                </div>
              </div>
              {/* Прогресс-бар емкости */}
              <div className="w-full h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.min(100, Math.max(15, ((telemetry?.vector_index_count || counts.all || 1) / Math.max(100, (telemetry?.db_total_records || counts.all || 1))) * 100))}%`
                  }}
                />
              </div>
              <div className="flex justify-between text-[10px] text-zinc-500">
                <span>SQLite DB</span>
                <span>{telemetry ? `${telemetry.db_size_mb} MB · ${telemetry.db_total_records} зап.` : 'База данных'}</span>
              </div>
            </div>

            <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-zinc-400">
              <span className="flex items-center gap-1.5">
                <CheckCircle2 className={`w-3 h-3 ${telemetry?.llm?.status === 'ONLINE' ? 'text-emerald-400' : 'text-amber-400'}`} />
                <span className="truncate max-w-[120px]" title={telemetry?.llm?.model || 'PydanticAI LLM'}>
                  {telemetry?.llm?.model ? telemetry.llm.model.split('/').pop() : 'PydanticAI'}
                </span>
              </span>
              <span className={`font-bold ${telemetry?.llm?.status === 'ONLINE' ? 'text-emerald-400' : 'text-amber-400'}`}>
                {telemetry?.llm?.status || 'ОНЛАЙН'}
              </span>
            </div>
          </div>
        </div>

      </div>

      {/* Нижняя кнопка ручного сканирования */}
      <div className="p-4 border-t border-white/[0.08] bg-[#0c0c11]/90">
        <button
          onClick={onForceScan}
          disabled={isSyncing}
          className="w-full flex items-center justify-center space-x-2 py-2.5 px-3 rounded-xl bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.08] text-xs font-semibold text-zinc-300 hover:text-white transition-all cursor-pointer disabled:opacity-50 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]"
        >
          <Terminal className="w-3.5 h-3.5 text-indigo-400" />
          <span>{isSyncing ? 'Сбор данных...' : 'Запустить сбор данных'}</span>
        </button>
      </div>
    </aside>
  );
};
