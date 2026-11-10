import React, { useState, useMemo } from 'react';
import { RotateCw, ChevronDown, ChevronUp, ExternalLink, Flame, Sparkles, HelpCircle } from 'lucide-react';
import type { LeaderboardRecord, AnalysisRecord } from '../../types/domain';
import {
  ALL_CATEGORIES,
  aggregateAllCategories,
  formatRating,
  formatTimestampRu,
  getLeaderboardModelUrl,
} from '../../utils/leaderboard';

interface LeaderboardSectionProps {
  records: LeaderboardRecord[];
  lastFetchedAt?: string | null;
  latestAnalysis?: AnalysisRecord | null;
  onRefresh: () => void;
  isRefreshing?: boolean;
  onAskAssistant?: (prompt: string) => void;
}

export const LeaderboardSection: React.FC<LeaderboardSectionProps> = ({
  records,
  lastFetchedAt,
  latestAnalysis,
  onRefresh,
  isRefreshing = false,
  onAskAssistant,
}) => {
  const [selectedCat, setSelectedCat] = useState<string>(ALL_CATEGORIES);
  const [aggMethod, setAggMethod] = useState<'avg' | 'max'>('avg');
  const [isEloOpen, setIsEloOpen] = useState(false);
  const [isAnalysisOpen, setIsAnalysisOpen] = useState(true);

  // Сбор уникальных категорий
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const r of records) {
      if (r.category && r.category !== ALL_CATEGORIES) {
        set.add(r.category);
      }
    }
    return [ALL_CATEGORIES, ...Array.from(set).sort()];
  }, [records]);

  const isAggregate = selectedCat === ALL_CATEGORIES;

  // Фильтрация и ранжирование
  const filtered = useMemo(() => {
    if (isAggregate) {
      return aggregateAllCategories(records, aggMethod);
    }
    return records
      .filter((r) => r.category === selectedCat)
      .sort((a, b) => b.rating - a.rating);
  }, [records, selectedCat, aggMethod, isAggregate]);

  const defaultAnalysisText =
    'Анализ формируется ИИ-агентом после сбора данных лидерборда. Нажмите кнопку «Обновить лидерборд Arena» для запуска сбора и анализа.';
  const analysisText = latestAnalysis?.analysis_text || defaultAnalysisText;

  return (
    <div className="space-y-6">
      {/* Шапка и запуск обновления */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#2D1B4E]">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <Flame className="w-6 h-6 text-amber-400" />
            Лидерборд моделей LMSYS Arena
          </h1>
          <p className="text-xs text-zinc-400 mt-1">
            Рейтинги Chatbot Arena по слепым человеческим оценкам (Elo) с разбивкой по категориям и агрегацией.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {lastFetchedAt && (
            <div className="text-xs text-zinc-400 flex items-center gap-1.5 font-mono">
              <span>Сбор:</span>
              <span className="text-emerald-400 bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-800/50">
                {formatTimestampRu(lastFetchedAt)}
              </span>
            </div>
          )}
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-xl bg-purple-900/40 hover:bg-purple-800/40 text-purple-200 border border-purple-600/50 transition-all cursor-pointer disabled:opacity-50"
            title="Запустить парсинг LMSYS Chatbot Arena"
          >
            <RotateCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>Обновить Arena</span>
          </button>
        </div>
      </div>

      {/* Эксплейнер рейтинга Elo */}
      <div className="rounded-xl border border-[#2D1B4E] bg-[#12121A] overflow-hidden text-xs">
        <button
          onClick={() => setIsEloOpen((prev) => !prev)}
          className="w-full px-4 py-2.5 flex items-center justify-between text-zinc-300 hover:text-white transition-colors"
        >
          <span className="flex items-center gap-2 font-medium">
            <HelpCircle className="w-4 h-4 text-purple-400" />
            Как рассчитывается рейтинг Elo?
          </span>
          {isEloOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {isEloOpen && (
          <div className="px-4 pb-3 pt-1 text-zinc-400 border-t border-[#2D1B4E]/60 leading-relaxed">
            Рейтинг Elo вычисляется на основе результатов попарных «слепых» тестирований. Пользователи или автоматические бенчмарки оценивают ответы двух анонимных моделей на один и тот же промпт. Если модель побеждает, её рейтинг повышается, а у проигравшей — снижается. Величина изменения рейтинга зависит от разницы их баллов до матча: победа над сильным конкурентом (с высоким Elo) приносит значительно больше баллов, чем победа над слабым.
          </div>
        )}
      </div>

      {/* Блок ИИ-анализа лидерборда */}
      <div className="rounded-xl border border-purple-500/40 bg-gradient-to-r from-purple-950/20 to-zinc-950/40 overflow-hidden text-xs shadow-md">
        <button
          onClick={() => setIsAnalysisOpen((prev) => !prev)}
          className="w-full px-4 py-2.5 flex items-center justify-between text-purple-300 hover:text-purple-200 transition-colors"
        >
          <span className="flex items-center gap-2 font-semibold">
            <Sparkles className="w-4 h-4 text-purple-400" />
            📊 Анализ трендов лидерборда (ИИ-агент)
          </span>
          {isAnalysisOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {isAnalysisOpen && (
          <div className="px-4 pb-3.5 pt-1 text-zinc-200 border-t border-purple-900/40 leading-relaxed whitespace-pre-wrap font-sans text-xs">
            {analysisText}
          </div>
        )}
      </div>

      {/* Панель фильтрации категорий и метода агрегации */}
      <div className="p-3.5 rounded-xl bg-[#12121A] border border-[#2D1B4E] flex flex-wrap items-center gap-4 text-xs">
        <div className="flex items-center gap-2">
          <span className="text-zinc-400">Категория:</span>
          <select
            value={selectedCat}
            onChange={(e) => setSelectedCat(e.target.value)}
            className="bg-[#0A0A0F] border border-[#2D1B4E] text-white px-3 py-1.5 rounded-lg focus:outline-none focus:border-purple-500"
          >
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        {isAggregate && (
          <div className="flex items-center gap-2">
            <span className="text-zinc-400">Агрегация:</span>
            <select
              value={aggMethod}
              onChange={(e) => setAggMethod(e.target.value as 'avg' | 'max')}
              className="bg-[#0A0A0F] border border-[#2D1B4E] text-white px-3 py-1.5 rounded-lg focus:outline-none focus:border-purple-500"
            >
              <option value="avg">Среднее по категориям (Avg)</option>
              <option value="max">Максимум по категориям (Max)</option>
            </select>
          </div>
        )}

        <div className="ml-auto text-zinc-400 font-mono">
          Моделей в таблице: <span className="text-white font-semibold">{filtered.length}</span>
        </div>
      </div>

      {/* Список моделей лидерборда */}
      <div className="space-y-3">
        {filtered.length === 0 ? (
          <div className="p-8 text-center rounded-xl bg-[#12121A] border border-[#2D1B4E] text-zinc-400 text-xs">
            Нет данных лидерборда. Нажмите кнопку «Обновить Arena» для сбора данных.
          </div>
        ) : (
          filtered.map((rec, idx) => {
            const modelUrl = getLeaderboardModelUrl(rec);
            const catsToShow = isAggregate
              ? rec.categories || [rec.category]
              : [selectedCat];

            return (
              <div
                key={`${rec.model_name}-${idx}`}
                className="p-4 rounded-xl bg-gradient-to-b from-[#1A0E2B] to-[#160A25] border border-[#6D28D9]/70 hover:border-[#A855F7] transition-all duration-200 text-xs shadow-md"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded-lg bg-purple-950/80 border border-purple-700/60 flex items-center justify-center font-bold text-purple-300 text-[11px] shrink-0">
                        #{idx + 1}
                      </span>
                      <div className="flex items-center gap-3">
                        <h3 className="text-sm font-bold text-white hover:text-purple-300 transition-colors">
                          <a
                            href={modelUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1.5"
                            title={`Открыть страницу ${rec.model_name}`}
                          >
                            {rec.model_name}
                            <ExternalLink className="w-3.5 h-3.5 opacity-50" />
                          </a>
                        </h3>
                        <button
                          onClick={() => onAskAssistant?.(`Расскажи подробно про модель ${rec.model_name} из рейтинга LMSYS Arena: её Elo-рейтинг, архитектура, лицензия и сравнение с конкурентами`)}
                          className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-purple-600/20 hover:bg-purple-600/40 text-purple-300 hover:text-white border border-purple-500/30 text-[10px] font-medium transition-colors cursor-pointer shadow-sm"
                          title="Спросить у AI Ассистента"
                        >
                          <Sparkles className="w-3 h-3 text-purple-400" />
                          <span>Спросить ассистента</span>
                        </button>
                      </div>
                      {rec.organization && (
                        <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">
                          {rec.organization}
                        </span>
                      )}
                    </div>

                    {/* Категории модели */}
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {catsToShow.map((cat, cIdx) => (
                        <span
                          key={cIdx}
                          className="text-[10px] px-2 py-0.5 rounded bg-[#1E1B4B] text-purple-300 border border-[#3B0764]"
                        >
                          {cat}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Оценка Elo */}
                  <div className="flex items-center gap-4 sm:justify-end shrink-0">
                    <div className="text-right">
                      <div className="text-lg font-black text-amber-300 font-mono">
                        {formatRating(rec.rating)}
                      </div>
                      <div className="text-[10px] text-zinc-400">
                        {isAggregate ? (aggMethod === 'avg' ? 'Avg Arena Elo' : 'Max Arena Elo') : 'Arena Elo'}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Описание / summary */}
                {rec.summary && (
                  <p className="text-zinc-300 mt-2 text-xs leading-relaxed whitespace-pre-line">
                    {rec.summary}
                  </p>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
