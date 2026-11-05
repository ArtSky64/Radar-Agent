import React from 'react';
import {
  Flame,
  Cpu,
  Globe2,
  FileText,
  Database,
  GitFork,
  Bot,
  RotateCw,
  RefreshCw,
  Activity,
  CheckCircle2,
} from 'lucide-react';
import type { NavigationTab } from '../../types/domain';
import type { RadarTelemetry } from '../../types/intel';

interface StudioSidebarProps {
  activeTab: NavigationTab;
  onTabChange: (tab: NavigationTab) => void;
  counts: {
    leaderboard: number;
    hfGlobal: number;
    hfRu: number;
    papers: number;
    datasets: number;
    repositories: number;
  };
  onForceScan: () => void;
  isSyncing: boolean;
  telemetry?: RadarTelemetry | null;
  onRefreshTelemetry?: () => void;
  onReindex?: () => void;
  isReindexing?: boolean;
  onToggleAssistant?: () => void;
  isAssistantOpen?: boolean;
}

export const StudioSidebar: React.FC<StudioSidebarProps> = ({
  activeTab,
  onTabChange,
  counts,
  onForceScan,
  isSyncing,
  telemetry,
  onRefreshTelemetry,
  onReindex,
  isReindexing = false,
  onToggleAssistant,
  isAssistantOpen = false,
}) => {
  const navItems: {
    id: NavigationTab;
    label: string;
    icon: React.ReactNode;
    count?: number;
    color: string;
  }[] = [
    {
      id: 'leaderboard',
      label: 'Лидерборд Arena',
      icon: <Flame className="w-4 h-4 text-amber-400" />,
      count: counts.leaderboard,
      color: 'text-amber-400',
    },
    {
      id: 'hf_global',
      label: 'Трендовые модели HF',
      icon: <Cpu className="w-4 h-4 text-purple-400" />,
      count: counts.hfGlobal,
      color: 'text-purple-400',
    },
    {
      id: 'hf_ru',
      label: 'Модели HF (RU)',
      icon: <Globe2 className="w-4 h-4 text-emerald-400" />,
      count: counts.hfRu,
      color: 'text-emerald-400',
    },
    {
      id: 'papers',
      label: 'Papers (Статьи)',
      icon: <FileText className="w-4 h-4 text-pink-400" />,
      count: counts.papers,
      color: 'text-pink-400',
    },
    {
      id: 'datasets',
      label: 'Датасеты',
      icon: <Database className="w-4 h-4 text-emerald-400" />,
      count: counts.datasets,
      color: 'text-emerald-400',
    },
    {
      id: 'repositories',
      label: 'Репозитории GitHub',
      icon: <GitFork className="w-4 h-4 text-sky-400" />,
      count: counts.repositories,
      color: 'text-sky-400',
    },
  ];

  return (
    <aside className="w-64 shrink-0 h-full bg-[#0A0A0F] border-r border-[#2D1B4E] flex flex-col justify-between select-none shadow-xl">
      <div className="p-4 space-y-5 overflow-y-auto">
        {/* Заголовок бокового меню */}
        <div>
          <div className="px-3 mb-2 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold flex items-center justify-between">
            <span>Разделы каталога</span>
            <span className="text-[10px] text-zinc-500 font-mono">6 разделов</span>
          </div>
          <div className="space-y-1">
            {navItems.map((item) => {
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onTabChange(item.id)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium transition-all cursor-pointer ${
                    isActive
                      ? 'bg-purple-950/60 text-white font-semibold border border-purple-500/50 shadow-sm'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04] border border-transparent'
                  }`}
                >
                  <div className="flex items-center space-x-2.5">
                    {item.icon}
                    <span className="truncate">{item.label}</span>
                  </div>
                  {item.count !== undefined && (
                    <span
                      className={`text-[11px] font-mono px-1.5 py-0.5 rounded ${
                        isActive
                          ? 'bg-purple-800/50 text-white'
                          : 'bg-zinc-800/50 text-zinc-400'
                      }`}
                    >
                      {item.count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Вызов ассистента */}
        {onToggleAssistant && (
          <div className="pt-2 border-t border-[#2D1B4E]">
            <div className="px-3 mb-2 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold flex items-center justify-between">
              <span>Интеллект</span>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            </div>
            <button
              onClick={onToggleAssistant}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
                isAssistantOpen
                  ? 'bg-purple-600 text-white shadow-lg shadow-purple-600/30 border border-purple-400'
                  : 'bg-purple-950/40 text-purple-300 hover:bg-purple-900/50 border border-purple-700/50'
              }`}
              title="Открыть / скрыть боковую панель AI-Ассистента"
            >
              <div className="flex items-center space-x-2.5">
                <Bot className="w-4 h-4 text-purple-400" />
                <span>AI Ассистент</span>
              </div>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-black/40 text-purple-300 border border-purple-500/30 font-mono">
                {isAssistantOpen ? 'Открыт' : 'Чат'}
              </span>
            </button>
          </div>
        )}

        {/* Быстрые действия */}
        <div className="pt-2 border-t border-[#2D1B4E]">
          <div className="px-3 mb-2 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">
            Управление данными
          </div>
          <div className="space-y-2">
            <button
              onClick={onForceScan}
              disabled={isSyncing}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-xs font-medium bg-purple-900/40 hover:bg-purple-800/40 text-purple-200 border border-purple-700/50 transition-all cursor-pointer disabled:opacity-50"
            >
              <RotateCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin' : ''}`} />
              <span>{isSyncing ? 'Сканирование источников...' : 'Синхронизировать всё'}</span>
            </button>

            {onReindex && (
              <button
                onClick={onReindex}
                disabled={isReindexing}
                className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-zinc-700/60 transition-all cursor-pointer disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isReindexing ? 'animate-spin' : ''}`} />
                <span>{isReindexing ? 'Индексация...' : 'Переиндексация RAG'}</span>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Живая телеметрия системы */}
      <div className="p-4 border-t border-[#2D1B4E] bg-[#07070B]">
        <div className="flex items-center justify-between text-[11px] mb-2 font-mono text-zinc-400">
          <div className="flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
            <span className="font-semibold text-zinc-200">ТЕЛЕМЕТРИЯ</span>
          </div>
          {onRefreshTelemetry && (
            <button
              onClick={onRefreshTelemetry}
              className="hover:text-white transition-colors cursor-pointer"
              title="Обновить метрики"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
          )}
        </div>

        <div className="space-y-1.5 text-[10px] font-mono text-zinc-400">
          <div className="flex justify-between items-center py-0.5 border-b border-zinc-900">
            <span>Статус сервера:</span>
            <span className="text-emerald-400 flex items-center gap-1 font-semibold">
              <CheckCircle2 className="w-3 h-3" />
              {telemetry ? 'Online' : 'Connected'}
            </span>
          </div>

          <div className="flex justify-between items-center py-0.5 border-b border-zinc-900">
            <span>База данных SQLite:</span>
            <span className="text-zinc-200">
              {telemetry?.db_size_mb !== undefined
                ? `${telemetry.db_size_mb} MB (${telemetry.total_records ?? telemetry.db_total_records ?? 0} записей)`
                : 'Локальная БД'}
            </span>
          </div>

          <div className="flex justify-between items-center py-0.5 border-b border-zinc-900">
            <span>Векторный индекс:</span>
            <span className="text-purple-300">
              {(telemetry?.vector_indexed_count ?? telemetry?.vector_index_count) !== undefined
                ? `${telemetry?.vector_indexed_count ?? telemetry?.vector_index_count} векторов`
                : 'Готов'}
            </span>
          </div>

          <div className="flex justify-between items-center py-0.5">
            <span>Порог семантики:</span>
            <span className="text-amber-300">
              {telemetry?.cosine_threshold || `${telemetry?.threshold || 0.59} cos`}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};
