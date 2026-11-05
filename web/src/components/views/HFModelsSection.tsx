import React, { useState, useMemo } from 'react';
import {
  RotateCw,
  Search,
  ExternalLink,
  Cpu,
  Heart,
  Download,
  TrendingUp,
  Compass,
  Target,
  Globe2,
} from 'lucide-react';
import type { HFModelItem } from '../../types/domain';
import { HF_DIRECTIONS, HF_TASK_TYPES } from '../../types/domain';
import { formatTimestampRu } from '../../utils/leaderboard';

interface HFModelsSectionProps {
  models: HFModelItem[];
  isRuTab?: boolean;
  lastFetchedAt?: string | null;
  onRefresh: () => void;
  isRefreshing?: boolean;
}

export const HFModelsSection: React.FC<HFModelsSectionProps> = ({
  models,
  isRuTab = false,
  lastFetchedAt,
  onRefresh,
  isRefreshing = false,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDirections, setSelectedDirections] = useState<string[]>([]);
  const [selectedTaskTypes, setSelectedTaskTypes] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState<string>(
    isRuTab ? 'По RU-рейтингу' : 'По мировому рейтингу'
  );

  // Фильтрация моделей
  const filtered = useMemo(() => {
    return models.filter((m) => {
      // Поиск
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const name = (m.model_name || m.name || '').toLowerCase();
        const sum = (m.summary || m.card_description || '').toLowerCase();
        if (!name.includes(q) && !sum.includes(q)) return false;
      }

      // Направления (0-4)
      if (selectedDirections.length > 0) {
        const itemDirs = m.directions || [];
        const hasMatch = itemDirs.some((d) => selectedDirections.includes(d));
        if (!hasMatch) return false;
      }

      // Типы задач (0-3)
      if (selectedTaskTypes.length > 0) {
        const itemTasks = m.task_types || [];
        const hasMatch = itemTasks.some((t) => selectedTaskTypes.includes(t));
        if (!hasMatch) return false;
      }

      return true;
    });
  }, [models, searchQuery, selectedDirections, selectedTaskTypes]);

  // Сортировка моделей
  const sorted = useMemo(() => {
    const list = [...filtered];
    if (sortBy === 'По мировому рейтингу') {
      list.sort((a, b) => {
        const rankA = (a.rank_global || 0) > 0 ? a.rank_global! : 9999;
        const rankB = (b.rank_global || 0) > 0 ? b.rank_global! : 9999;
        if (rankA !== rankB) return rankA - rankB;
        return (b.downloads || 0) - (a.downloads || 0);
      });
    } else if (sortBy === 'По RU-рейтингу') {
      list.sort((a, b) => {
        const rankA = (a.rank_ru || 0) > 0 ? a.rank_ru! : 9999;
        const rankB = (b.rank_ru || 0) > 0 ? b.rank_ru! : 9999;
        if (rankA !== rankB) return rankA - rankB;
        return (b.downloads || 0) - (a.downloads || 0);
      });
    } else if (sortBy === 'По скачиваниям') {
      list.sort((a, b) => (b.downloads || 0) - (a.downloads || 0));
    } else if (sortBy === 'По лайкам') {
      list.sort((a, b) => (b.likes || 0) - (a.likes || 0));
    }
    return list;
  }, [filtered, sortBy]);

  const toggleDirection = (dirKey: string) => {
    setSelectedDirections((prev) =>
      prev.includes(dirKey) ? prev.filter((k) => k !== dirKey) : [...prev, dirKey]
    );
  };

  const toggleTaskType = (taskKey: string) => {
    setSelectedTaskTypes((prev) =>
      prev.includes(taskKey) ? prev.filter((k) => k !== taskKey) : [...prev, taskKey]
    );
  };

  return (
    <div className="space-y-6">
      {/* Шапка раздела */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#2D1B4E]">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            {isRuTab ? (
              <>
                <Globe2 className="w-6 h-6 text-emerald-400" />
                🇷🇺 Трендовые модели Hugging Face с поддержкой русского языка
              </>
            ) : (
              <>
                <Cpu className="w-6 h-6 text-purple-400" />
                🌍 Трендовые модели Hugging Face (Мировые тренды)
              </>
            )}
          </h1>
          <p className="text-xs text-zinc-400 mt-1">
            {isRuTab
              ? 'Объединённый рейтинг моделей по фильтрам language=ru и language=rus с дедупликацией и сквозным рейтингом.'
              : 'Свежие трендовые модели с Hugging Face Hub со сквозной классификацией по направлениям и типам задач.'}
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
            title="Запустить парсинг трендов Hugging Face"
          >
            <RotateCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>Обновить тренды HF</span>
          </button>
        </div>
      </div>

      {/* Панель фильтров */}
      <div className="p-4 rounded-xl bg-[#12121A] border border-[#2D1B4E] space-y-3.5 text-xs">
        {/* Строка поиска и селект сортировки */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="sm:col-span-2 relative">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-zinc-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Поиск по названию или описанию модели..."
              className="w-full bg-[#0A0A0F] border border-[#2D1B4E] rounded-lg pl-9 pr-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-purple-500"
            />
          </div>

          <div>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="w-full bg-[#0A0A0F] border border-[#2D1B4E] rounded-lg px-3 py-2 text-white focus:outline-none focus:border-purple-500"
            >
              {isRuTab ? (
                <>
                  <option value="По RU-рейтингу">По RU-рейтингу</option>
                  <option value="По мировому рейтингу">По мировому рейтингу</option>
                </>
              ) : (
                <>
                  <option value="По мировому рейтингу">По мировому рейтингу</option>
                  <option value="По RU-рейтингу">По RU-рейтингу</option>
                </>
              )}
              <option value="По скачиваниям">По скачиваниям</option>
              <option value="По лайкам">По лайкам</option>
            </select>
          </div>
        </div>

        {/* Направления ИИ (0-4) */}
        <div>
          <div className="text-[11px] font-semibold text-zinc-400 mb-1.5 flex items-center gap-1.5">
            <Compass className="w-3.5 h-3.5 text-sky-400" />
            Направления (0–4):
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(HF_DIRECTIONS).map(([key, label]) => {
              const active = selectedDirections.includes(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleDirection(key)}
                  className={`px-2.5 py-1 rounded-md text-[11px] border transition-all cursor-pointer ${
                    active
                      ? 'bg-sky-950/80 text-sky-300 border-sky-600 font-semibold'
                      : 'bg-[#0A0A0F] text-zinc-400 border-[#2D1B4E] hover:border-zinc-700'
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Типы задач (0-3) */}
        <div>
          <div className="text-[11px] font-semibold text-zinc-400 mb-1.5 flex items-center gap-1.5">
            <Target className="w-3.5 h-3.5 text-purple-400" />
            Типы задач (0–3):
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(HF_TASK_TYPES).map(([key, label]) => {
              const active = selectedTaskTypes.includes(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleTaskType(key)}
                  className={`px-2.5 py-1 rounded-md text-[11px] border transition-all cursor-pointer ${
                    active
                      ? 'bg-purple-950/80 text-purple-300 border-purple-600 font-semibold'
                      : 'bg-[#0A0A0F] text-zinc-400 border-[#2D1B4E] hover:border-zinc-700'
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Сброс фильтров */}
        {(searchQuery || selectedDirections.length > 0 || selectedTaskTypes.length > 0) && (
          <div className="pt-1 flex justify-end">
            <button
              onClick={() => {
                setSearchQuery('');
                setSelectedDirections([]);
                setSelectedTaskTypes([]);
              }}
              className="text-[11px] text-purple-400 hover:text-purple-300 underline cursor-pointer"
            >
              Сбросить фильтры
            </button>
          </div>
        )}
      </div>

      {/* Список моделей */}
      <div className="space-y-3">
        {sorted.length === 0 ? (
          <div className="p-8 text-center rounded-xl bg-[#12121A] border border-[#2D1B4E] text-zinc-400 text-xs">
            Нет моделей по выбранным критериям.
          </div>
        ) : (
          sorted.map((m, idx) => {
            const modelName = m.model_name || m.name || 'Unknown';
            const modelUrl =
              m.source_url || m.url || `https://huggingface.co/${modelName}`;
            const rankRu = m.rank_ru || 0;
            const rankGlobal = m.rank_global || 0;
            const rawTags = Array.isArray(m.tags)
              ? m.tags
              : typeof m.tags === 'string'
              ? m.tags.split(',')
              : [];
            const tags = rawTags.map((t) => t.trim()).filter(Boolean);

            return (
              <div
                key={m.rowid || `${modelName}-${idx}`}
                className="p-4 rounded-xl bg-gradient-to-b from-[#1A0E2B] to-[#160A25] border border-[#6D28D9]/70 hover:border-[#A855F7] transition-all duration-200 text-xs shadow-md"
              >
                {/* Бэйджи */}
                <div className="flex flex-wrap items-center gap-1.5 mb-2.5">
                  {/* Ранги */}
                  {isRuTab ? (
                    <>
                      {rankRu > 0 && (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-500">
                          🏆 RU ТОП #{rankRu}
                        </span>
                      )}
                      {rankGlobal > 0 ? (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-500">
                          🌍 Мировой #{rankGlobal}
                        </span>
                      ) : (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-zinc-700">
                          🌍 Вне мирового топ-50
                        </span>
                      )}
                    </>
                  ) : (
                    <>
                      {rankGlobal > 0 && (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-500">
                          🌍 МИРОВОЙ ТОП #{rankGlobal}
                        </span>
                      )}
                      {rankRu > 0 && (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-500">
                          🇷🇺 RU #{rankRu}
                        </span>
                      )}
                    </>
                  )}

                  {/* Параметры */}
                  {m.parameters && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-950/80 text-amber-300 border border-amber-600">
                      ⚡ {m.parameters}
                    </span>
                  )}

                  {/* Pipeline Tag */}
                  {m.pipeline_tag && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-sky-950/80 text-sky-300 border border-sky-600">
                      🏷️ {m.pipeline_tag}
                    </span>
                  )}

                  {/* Направления */}
                  {(m.directions || []).map((d, dIdx) => (
                    <span
                      key={dIdx}
                      className="text-[10px] font-semibold px-2 py-0.5 rounded bg-sky-950/60 text-sky-300 border border-sky-700/50"
                    >
                      🧭 {HF_DIRECTIONS[d] || d}
                    </span>
                  ))}

                  {/* Задачи */}
                  {(m.task_types || []).map((t, tIdx) => (
                    <span
                      key={tIdx}
                      className="text-[10px] font-semibold px-2 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-700/50"
                    >
                      🎯 {HF_TASK_TYPES[t] || t}
                    </span>
                  ))}

                  {/* Теги */}
                  {tags.slice(0, 4).map((t, tIdx) => (
                    <span
                      key={tIdx}
                      className="text-[10px] px-2 py-0.5 rounded bg-[#1E1B4B] text-purple-300 border border-[#3B0764]"
                    >
                      {t}
                    </span>
                  ))}
                </div>

                {/* Название модели со ссылкой */}
                <h3 className="text-sm font-bold text-white hover:text-purple-300 transition-colors">
                  <a href={modelUrl} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 font-mono">
                    {modelName}
                    <ExternalLink className="w-3.5 h-3.5 opacity-50" />
                  </a>
                </h3>

                {/* Описание / summary */}
                {m.summary && (
                  <p className="text-zinc-300 mt-1.5 text-[11px] leading-relaxed line-clamp-3">
                    {m.summary}
                  </p>
                )}

                {/* Метрики */}
                <div className="flex items-center gap-4 mt-2.5 pt-2 border-t border-[#2D1B4E]/60 text-[11px] text-zinc-400">
                  <span className="flex items-center gap-1 text-sky-300">
                    <Download className="w-3.5 h-3.5" />
                    {(m.downloads || 0).toLocaleString()} скачиваний
                  </span>
                  <span className="flex items-center gap-1 text-amber-300">
                    <Heart className="w-3.5 h-3.5 fill-amber-400" />
                    {(m.likes || 0).toLocaleString()} лайков
                  </span>
                  {m.trending_score ? (
                    <span className="flex items-center gap-1 text-purple-300">
                      <TrendingUp className="w-3.5 h-3.5" />
                      Трендинг-балл: {Math.round(Number(m.trending_score) * 10) / 10}
                    </span>
                  ) : null}

                  <a
                    href={modelUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="ml-auto text-purple-400 hover:text-purple-300 underline font-medium"
                  >
                    Открыть на Hugging Face →
                  </a>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
