import React, { useEffect, useRef } from 'react';
import { ExternalLink, Sparkles, ChevronRight, ArrowUpDown, TrendingUp } from 'lucide-react';
import { Sparkline } from '../ui/Sparkline';
import type { IntelItem, SortMode, TabType } from '../../types/intel';
import { getItemGrammar, getTabHeaderCountLabel } from '../../utils/intelItemLabels';

interface StudioFeedProps {
  items: IntelItem[];
  selectedItem: IntelItem | null;
  onSelectItem: (item: IntelItem) => void;
  onQuickAsk: (item: IntelItem) => void;
  sortMode: SortMode;
  onSortChange: (mode: SortMode) => void;
  activeTopic: string;
  activeTab?: TabType;
  onForceScan?: () => void;
  isLoading?: boolean;
}

const sourceBadges: Record<string, { label: string; style: string; sparkColor: string }> = {
  HuggingFace: {
    label: 'HF',
    style: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    sparkColor: '#f59e0b',
  },
  GitHub: {
    label: 'GH',
    style: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
    sparkColor: '#10b981',
  },
  ArXiv: {
    label: 'ArXiv',
    style: 'bg-purple-500/10 text-purple-300 border-purple-500/20',
    sparkColor: '#a855f7',
  },
  'LMSys Arena': {
    label: 'Arena',
    style: 'bg-sky-500/10 text-sky-300 border-sky-500/20',
    sparkColor: '#38bdf8',
  },
};

function getSparkline(item: IntelItem): number[] {
  if (item.sparkline && item.sparkline.length > 0) return item.sparkline;
  const val = item.metricNumber || 50;
  return [
    Math.round(val * 0.72),
    Math.round(val * 0.79),
    Math.round(val * 0.85),
    Math.round(val * 0.91),
    Math.round(val * 0.95),
    Math.round(val * 0.98),
    val,
  ];
}

export const StudioFeed: React.FC<StudioFeedProps> = ({
  items,
  selectedItem,
  onSelectItem,
  onQuickAsk,
  sortMode,
  onSortChange,
  activeTopic,
  activeTab = 'All Stream',
  onForceScan,
  isLoading = false,
}) => {
  const feedContainerRef = useRef<HTMLDivElement | null>(null);

  // Клавиатурная навигация по ленте: стрелки ↑ / ↓ (или J / K без модификаторов)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Игнорируем если фокус в инпуте или textarea
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea') return;

      // Если зажат Ctrl/Cmd/Alt (например Ctrl + K для быстрого поиска) — не перехватываем
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (items.length === 0) return;

      const currentIndex = items.findIndex((i) => i.id === selectedItem?.id);

      const isDown =
        e.key === 'ArrowDown' ||
        e.code === 'KeyJ' ||
        e.key.toLowerCase() === 'j' ||
        e.key.toLowerCase() === 'о';

      const isUp =
        e.key === 'ArrowUp' ||
        e.code === 'KeyK' ||
        e.key.toLowerCase() === 'k' ||
        e.key.toLowerCase() === 'л';

      if (isDown) {
        e.preventDefault();
        const nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
        onSelectItem(items[nextIndex]);
      } else if (isUp) {
        e.preventDefault();
        const prevIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
        onSelectItem(items[prevIndex]);
      } else if (e.key === 'Enter' && selectedItem) {
        e.preventDefault();
        onQuickAsk(selectedItem);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [items, selectedItem, onSelectItem, onQuickAsk]);

  return (
    <div className="flex-1 flex flex-col h-full bg-[#07070c]/40 backdrop-blur-sm overflow-hidden select-none">
      
      {/* Подшапка ленты: сортировка и метаданные с фаской */}
      <div className="h-10 shrink-0 px-6 border-b border-white/[0.06] bg-[#09090e]/60 backdrop-blur-md flex items-center justify-between text-xs text-zinc-400 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]">
        <div className="flex items-center space-x-2.5">
          <span className="font-semibold text-zinc-200">
            {getTabHeaderCountLabel(activeTab, items.length)}
          </span>
          <span className="w-1 h-1 rounded-full bg-zinc-600" />
          <span className="text-[11px] font-mono text-zinc-500">Прямой эфир</span>
          {activeTopic !== 'ALL' && (
            <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
              {activeTopic}
            </span>
          )}
        </div>

        <div className="flex items-center space-x-1.5 text-xs">
          <ArrowUpDown className="w-3.5 h-3.5 text-zinc-500" />
          <span className="text-zinc-500">Сортировка:</span>
          <button
            onClick={() => onSortChange(sortMode === 'trending' ? 'metrics' : 'trending')}
            className="text-zinc-300 hover:text-white transition-colors cursor-pointer font-medium ml-1"
          >
            {sortMode === 'trending' ? 'По популярности' : 'По ключевой метрике'}
          </button>
        </div>
      </div>

      {/* Список без разрывов: сплошная монолитная лента */}
      <div
        ref={feedContainerRef}
        className="flex-1 overflow-y-auto divide-y divide-white/[0.04]"
      >
        {isLoading && items.length === 0 ? (
          <div className="py-20 text-center space-y-3">
            <div className="w-8 h-8 mx-auto rounded-full border-2 border-indigo-400 border-t-transparent animate-spin" />
            <div className="text-xs font-mono text-zinc-400">Считывание потока данных из SQLite...</div>
          </div>
        ) : items.length === 0 ? (
          <div className="py-24 text-center px-6">
            <div className="text-xs font-mono text-zinc-400 mb-2">
              По заданным фильтрам записей не обнаружено.
            </div>
            {onForceScan && (
              <button
                onClick={onForceScan}
                className="mt-2 px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 text-xs font-mono transition-all cursor-pointer"
              >
                ✦ Запустить сканирование эфира
              </button>
            )}
          </div>
        ) : (
          items.map((item) => {
            const isSelected = selectedItem?.id === item.id;
            const badge = sourceBadges[item.source] || {
              label: item.source,
              style: 'bg-zinc-800 text-zinc-300 border-zinc-700',
              sparkColor: '#6366f1',
            };

            const sparkData = getSparkline(item);
            const deltaStr = item.delta || (item.metricLabel ? `${item.metricValue} ${item.metricLabel}` : 'Активно');

            return (
              <div
                key={item.id}
                onClick={() => onSelectItem(item)}
                className={`group px-6 py-3.5 flex items-center justify-between cursor-pointer transition-all duration-100 relative ${
                  isSelected
                    ? 'bg-gradient-to-r from-indigo-500/15 via-white/[0.04] to-transparent border-l-2 border-indigo-400 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]'
                    : 'hover:bg-white/[0.03] border-l-2 border-transparent'
                }`}
              >
                {/* Левая группа: бейдж, название, метаданные */}
                <div className="flex items-center space-x-3.5 min-w-0 pr-4">
                  <span className={`shrink-0 text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${badge.style}`}>
                    {badge.label}
                  </span>

                  <div className="min-w-0">
                    <div className="flex items-center space-x-2">
                      <span className="text-[13px] font-medium text-white truncate group-hover:text-indigo-300 transition-colors tracking-tight">
                        {item.title}
                      </span>
                      {item.arenaElo && (
                        <span className="shrink-0 text-[10px] font-mono font-bold px-1.5 rounded bg-sky-500/15 text-sky-300 border border-sky-500/30">
                          {item.arenaElo} Elo
                        </span>
                      )}
                    </div>
                    <div className="flex items-center space-x-2 text-[11px] text-zinc-400 mt-0.5">
                      <span className="text-zinc-300 font-medium">{item.organization}</span>
                      <span className="text-zinc-600">·</span>
                      <span className="text-zinc-500 font-mono">{item.timestamp}</span>
                      <span className="text-zinc-600">·</span>
                      <span className="text-zinc-500 font-mono truncate">{item.category}</span>
                    </div>
                  </div>
                </div>

                {/* Правая группа: спарклайн динамики, дельта, метрика и действия */}
                <div className="flex items-center space-x-4 shrink-0">
                  {/* Мини-спарклайн тренда за 7 дней */}
                  <div className="hidden md:flex flex-col items-end pr-2">
                    <Sparkline
                      data={sparkData}
                      color={badge.sparkColor}
                      width={52}
                      height={18}
                    />
                    <div className="flex items-center gap-0.5 text-[10px] font-mono text-emerald-400/90 mt-0.5">
                      <TrendingUp className="w-2.5 h-2.5" />
                      <span>{deltaStr}</span>
                    </div>
                  </div>

                  {/* Быстрые действия на ховере */}
                  <div className="hidden sm:flex items-center space-x-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onQuickAsk(item);
                      }}
                      className="p-1.5 rounded-md hover:bg-white/10 text-zinc-400 hover:text-indigo-300 transition-colors"
                      title={`Спросить у AI Ассистента ${getItemGrammar(item).prepositional}`}
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                    </button>
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="p-1.5 rounded-md hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
                      title="Открыть первоисточник"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  </div>

                  {/* Численная метрика */}
                  <div className="text-right min-w-[70px]">
                    <div className="text-xs font-mono font-bold text-zinc-200 tabular-nums">
                      {item.metricValue}
                    </div>
                    <div className="text-[10px] font-mono text-zinc-500">
                      {item.metricLabel}
                    </div>
                  </div>

                  <ChevronRight className={`w-4 h-4 transition-colors ${isSelected ? 'text-indigo-400' : 'text-zinc-600 group-hover:text-white'}`} />
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Тонкая статусная строка подсказок горячих клавиш внизу */}
      <div className="h-7 shrink-0 px-6 border-t border-white/[0.06] bg-[#07070a]/70 backdrop-blur-md flex items-center justify-between text-[11px] font-mono text-zinc-500 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)]">
        <div className="flex items-center space-x-4">
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-300 text-[10px] border border-white/[0.08]">↑↓</kbd>
            <span className="text-zinc-500">навигация</span>
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-300 text-[10px] border border-white/[0.08]">Enter</kbd>
            <span className="text-zinc-500">спросить ассистента</span>
          </span>
          <span className="hidden sm:flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-300 text-[10px] border border-white/[0.08]">Ctrl + K</kbd>
            <span className="text-zinc-500">быстрый поиск</span>
          </span>
        </div>

        <div className="flex items-center space-x-2 text-zinc-600">
          <span>СИНХРОНИЗАЦИЯ FASTEMBED</span>
        </div>
      </div>

    </div>
  );
};
