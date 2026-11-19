import React, { useState, useMemo } from 'react';
import {
  GitFork,
  Search,
  ExternalLink,
  RefreshCw,
  Star,
  Sparkles,
  Flame,
  Compass,
  Target,
  Clock,
  Code2,
  Calendar,
} from 'lucide-react';
import type { RepoItem, ArticleItem, CardContext } from '../../types/domain';
import { GITHUB_DIRECTIONS, GITHUB_TASK_TYPES } from '../../types/domain';
import { formatTimestampRu } from '../../utils/leaderboard';

interface RepositoriesSectionProps {
  repositories: (RepoItem | ArticleItem)[];
  lastFetchedAt?: string | null;
  onRefresh?: () => Promise<void>;
  isRefreshing?: boolean;
  onAskAssistant?: (prompt: string, cardContext?: CardContext) => void;
}

export const RepositoriesSection: React.FC<RepositoriesSectionProps> = ({
  repositories,
  lastFetchedAt,
  onRefresh,
  isRefreshing = false,
  onAskAssistant,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'new' | 'existing'>('all');
  const [periodFilter, setPeriodFilter] = useState<'all' | 'weekly' | 'monthly'>('all');
  const [selectedDirections, setSelectedDirections] = useState<string[]>([]);
  const [selectedTaskTypes, setSelectedTaskTypes] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState<'trending' | 'stars' | 'newest' | 'name'>('trending');
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  // Нормализуем репозитории
  const repoList = useMemo(() => {
    return repositories.map((r: any) => {
      const repoName = r.repo_name || r.title || 'Unknown/Repo';
      const url = r.url || r.source_url || `https://github.com/${repoName}`;
      const stars = Number(r.stars || 0);
      const starsPeriod = Number(r.stars_this_period || 0);
      const isNew = Boolean(r.is_new);
      const summary = r.summary || r.description || '';
      const directions: string[] = Array.isArray(r.directions) ? r.directions : [];
      const taskTypes: string[] = Array.isArray(r.task_types) ? r.task_types : [];
      const tags: string[] = Array.isArray(r.tags)
        ? r.tags
        : typeof r.tags === 'string'
        ? r.tags.split(',')
        : [];
      const language = (r.language || '').trim();
      const period = (r.period || '').trim().toLowerCase();

      return {
        ...r,
        repo_name: repoName,
        url,
        stars,
        stars_this_period: starsPeriod,
        is_new: isNew,
        summary,
        directions,
        task_types: taskTypes,
        tags,
        language,
        period,
      };
    });
  }, [repositories]);

  // Подсчёт по периодам для вкладок
  const weeklyCount = useMemo(() => {
    return repoList.filter((r) => {
      const p = r.period;
      return p === 'weekly' || p === 'week';
    }).length;
  }, [repoList]);

  const monthlyCount = useMemo(() => {
    return repoList.filter((r) => {
      const p = r.period;
      return p === 'monthly' || p === 'month';
    }).length;
  }, [repoList]);

  // Фильтрация
  const filteredRepos = useMemo(() => {
    return repoList.filter((repo) => {
      // Поиск
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const name = repo.repo_name.toLowerCase();
        const sum = repo.summary.toLowerCase();
        if (!name.includes(q) && !sum.includes(q)) return false;
      }

      // Статус в тренде
      if (statusFilter === 'new' && !repo.is_new) return false;
      if (statusFilter === 'existing' && repo.is_new) return false;

      // Период (weekly / monthly)
      if (periodFilter === 'weekly') {
        const p = repo.period;
        // Если указан weekly или week
        if (p) {
          if (p !== 'weekly' && p !== 'week') return false;
        } else if (weeklyCount > 0) {
          // Если у других элементов период размечен, а тут пусто — отсекаем
          return false;
        }
      } else if (periodFilter === 'monthly') {
        const p = repo.period;
        if (p) {
          if (p !== 'monthly' && p !== 'month') return false;
        } else if (monthlyCount > 0) {
          return false;
        }
      }

      // Направления (0-4)
      if (selectedDirections.length > 0) {
        const hasDir = repo.directions.some((d: string) => selectedDirections.includes(d));
        if (!hasDir) return false;
      }

      // Типы задач (0-3)
      if (selectedTaskTypes.length > 0) {
        const hasTask = repo.task_types.some((t: string) => selectedTaskTypes.includes(t));
        if (!hasTask) return false;
      }

      return true;
    });
  }, [repoList, searchQuery, statusFilter, periodFilter, selectedDirections, selectedTaskTypes, weeklyCount, monthlyCount]);

  // Сортировка
  const sortedRepos = useMemo(() => {
    const list = [...filteredRepos];
    if (sortBy === 'trending') {
      list.sort((a, b) => (a.rowid || 0) - (b.rowid || 0));
    } else if (sortBy === 'stars') {
      list.sort((a, b) => b.stars - a.stars);
    } else if (sortBy === 'newest') {
      list.sort((a, b) => (b.rowid || 0) - (a.rowid || 0));
    } else if (sortBy === 'name') {
      list.sort((a, b) => a.repo_name.localeCompare(b.repo_name));
    }
    return list;
  }, [filteredRepos, sortBy]);

  const handleRefreshClick = async () => {
    if (onRefresh) {
      await onRefresh();
      return;
    }
    try {
      setRefreshMessage('Запуск сбора трендов GitHub...');
      const res = await fetch('/trending/github/refresh', { method: 'POST' });
      if (res.ok) {
        setRefreshMessage('Сбор запущен в фоне!');
      } else {
        setRefreshMessage('Ошибка запуска сбора.');
      }
    } catch {
      setRefreshMessage('Не удалось соединиться с сервером.');
    }
    setTimeout(() => setRefreshMessage(null), 4000);
  };

  const newCount = useMemo(() => repoList.filter((r) => r.is_new).length, [repoList]);

  const toggleDirection = (dir: string) => {
    setSelectedDirections((prev) =>
      prev.includes(dir) ? prev.filter((d) => d !== dir) : [...prev, dir]
    );
  };

  const toggleTaskType = (task: string) => {
    setSelectedTaskTypes((prev) =>
      prev.includes(task) ? prev.filter((t) => t !== task) : [...prev, task]
    );
  };

  return (
    <div className="space-y-6">
      {/* Шапка раздела */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <GitFork className="w-7 h-7 text-sky-400" />
              Репозитории GitHub
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-300 border border-sky-500/30">
              {repoList.length} в базе
            </span>
            {newCount > 0 && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 flex items-center gap-1">
                <Sparkles className="w-3 h-3" />
                {newCount} новых
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Трендовые GitHub-репозитории по тематике ML/AI, собранные за последний период (weekly + monthly).
          </p>
        </div>

        <div className="flex items-center gap-3">
          {refreshMessage && (
            <span className="text-xs px-2.5 py-1 rounded bg-accent/30 text-accent-foreground border border-border">
              {refreshMessage}
            </span>
          )}
          <button
            onClick={handleRefreshClick}
            disabled={isRefreshing}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-sky-950/60 hover:bg-sky-900/60 text-sky-300 border border-sky-700/50 transition-all shadow-sm disabled:opacity-50"
            title="Запустить сбор актуальных 30 репозиториев (weekly + monthly)"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            Обновить тренды GitHub
          </button>
        </div>
      </div>

      {/* Метка последнего сбора */}
      {lastFetchedAt && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock className="w-3.5 h-3.5 text-zinc-400" />
          <span>Последний сбор списка:</span>
          <span className="font-semibold text-emerald-400 bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-800/40">
            {formatTimestampRu(lastFetchedAt)}
          </span>
        </div>
      )}

      {/* Вкладки периодов трендов */}
      <div className="flex items-center gap-2 border-b border-border/80 pb-1">
        <button
          onClick={() => setPeriodFilter('all')}
          className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm font-medium transition-all ${
            periodFilter === 'all'
              ? 'bg-sky-950/40 text-sky-400 border-b-2 border-sky-400 font-semibold'
              : 'text-muted-foreground hover:text-white hover:bg-secondary/40'
          }`}
        >
          <span>🌐 Все периоды</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-sky-900/50 text-sky-300">
            {repoList.length}
          </span>
        </button>

        <button
          onClick={() => setPeriodFilter('weekly')}
          className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm font-medium transition-all ${
            periodFilter === 'weekly'
              ? 'bg-sky-950/40 text-sky-400 border-b-2 border-sky-400 font-semibold'
              : 'text-muted-foreground hover:text-white hover:bg-secondary/40'
          }`}
        >
          <span>🔥 Тренды за неделю</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-sky-900/50 text-sky-300">
            {weeklyCount}
          </span>
        </button>

        <button
          onClick={() => setPeriodFilter('monthly')}
          className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm font-medium transition-all ${
            periodFilter === 'monthly'
              ? 'bg-sky-950/40 text-sky-400 border-b-2 border-sky-400 font-semibold'
              : 'text-muted-foreground hover:text-white hover:bg-secondary/40'
          }`}
        >
          <span>📅 Тренды за месяц</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-sky-900/50 text-sky-300">
            {monthlyCount}
          </span>
        </button>
      </div>

      {/* Панель фильтров */}
      <div className="p-4 rounded-xl bg-[#12121A] border border-[#2D1B4E] space-y-4 shadow-sm">
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
          {/* Поиск */}
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
            <input
              type="text"
              placeholder="Поиск по названию или описанию..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 text-sm rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] focus:border-purple-500 focus:outline-none text-white placeholder-muted-foreground"
            />
          </div>

          {/* Фильтр по периоду */}
          <div>
            <select
              value={periodFilter}
              onChange={(e) => setPeriodFilter(e.target.value as any)}
              className="w-full px-3 py-2 text-sm rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="all">Все периоды (Weekly + Monthly)</option>
              <option value="weekly">🔥 Тренды за неделю (Weekly)</option>
              <option value="monthly">📅 Тренды за месяц (Monthly)</option>
            </select>
          </div>

          {/* Фильтр по статусу */}
          <div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as any)}
              className="w-full px-3 py-2 text-sm rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="all">Все статусы в тренде</option>
              <option value="new">🌟 Новые в тренде</option>
              <option value="existing">🔥 Уже были в базе (в тренде)</option>
            </select>
          </div>

          {/* Сортировка */}
          <div>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="w-full px-3 py-2 text-sm rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="trending">Позиция в тренде (GitHub Trending)</option>
              <option value="stars">Сортировка: по звёздам (всего)</option>
              <option value="newest">Сортировка: сначала новые в базе</option>
              <option value="name">Сортировка: по имени (A-Z)</option>
            </select>
          </div>
        </div>

        {/* Направления (0-4) */}
        <div>
          <div className="text-xs font-semibold text-muted-foreground mb-1.5 flex items-center gap-1.5">
            <Compass className="w-3.5 h-3.5 text-sky-400" />
            Направления (0–4):
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(GITHUB_DIRECTIONS).map(([key, label]) => {
              const active = selectedDirections.includes(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleDirection(key)}
                  className={`text-xs px-2.5 py-1 rounded-md border transition-all ${
                    active
                      ? 'bg-sky-950 text-sky-300 border-sky-500 font-medium'
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
          <div className="text-xs font-semibold text-muted-foreground mb-1.5 flex items-center gap-1.5">
            <Target className="w-3.5 h-3.5 text-purple-400" />
            Типы задач (0–3):
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(GITHUB_TASK_TYPES).map(([key, label]) => {
              const active = selectedTaskTypes.includes(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleTaskType(key)}
                  className={`text-xs px-2.5 py-1 rounded-md border transition-all ${
                    active
                      ? 'bg-purple-950 text-purple-300 border-purple-500 font-medium'
                      : 'bg-[#0A0A0F] text-zinc-400 border-[#2D1B4E] hover:border-zinc-700'
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Кнопка сброса */}
        {(searchQuery ||
          statusFilter !== 'all' ||
          periodFilter !== 'all' ||
          selectedDirections.length > 0 ||
          selectedTaskTypes.length > 0) && (
          <div className="pt-2 border-t border-[#2D1B4E]/60 flex justify-end">
            <button
              onClick={() => {
                setSearchQuery('');
                setStatusFilter('all');
                setPeriodFilter('all');
                setSelectedDirections([]);
                setSelectedTaskTypes([]);
              }}
              className="text-xs text-purple-400 hover:text-purple-300 underline cursor-pointer"
            >
              Сбросить все фильтры
            </button>
          </div>
        )}
      </div>

      {/* Список репозиториев */}
      <div className="space-y-4">
        {sortedRepos.length === 0 ? (
          <div className="p-8 text-center rounded-xl bg-[#12121A] border border-[#2D1B4E] text-muted-foreground">
            <GitFork className="w-10 h-10 mx-auto mb-3 opacity-40 text-sky-400" />
            <p className="text-base font-medium text-white">Репозитории не найдены</p>
            <p className="text-xs text-muted-foreground mt-1">
              Попробуйте изменить параметры поиска или фильтров.
            </p>
          </div>
        ) : (
          sortedRepos.map((repo, idx) => {
            return (
              <div
                key={repo.rowid || `${repo.repo_name}-${idx}`}
                className="p-5 rounded-2xl bg-gradient-to-b from-[#1A0E2B] to-[#160A25] border border-[#6D28D9]/70 hover:border-[#A855F7] transition-all duration-200 shadow-md hover:shadow-purple-900/20 group"
              >
                {/* Бэйджи */}
                <div className="flex flex-wrap items-center gap-2 mb-3">
                  {/* Тип контента */}
                  <span className="text-[11px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-md bg-sky-950/80 text-sky-400 border border-sky-600/50">
                    РЕПОЗИТОРИЙ
                  </span>

                  {/* Статус в тренде */}
                  {repo.is_new ? (
                    <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-emerald-950/80 text-emerald-300 border border-emerald-500/50 flex items-center gap-1">
                      <Sparkles className="w-3 h-3 text-emerald-400" />
                      🌟 НОВЫЙ В ТРЕНДЕ
                    </span>
                  ) : (
                    <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-purple-950/80 text-purple-300 border border-purple-500/50 flex items-center gap-1">
                      <Flame className="w-3 h-3 text-purple-400" />
                      🔥 В ТРЕНДЕ
                    </span>
                  )}

                  {/* Период тренда */}
                  {repo.period && (
                    <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-sky-950/80 text-sky-300 border border-sky-600/50 flex items-center gap-1">
                      <Calendar className="w-3 h-3 text-sky-400" />
                      {repo.period === 'weekly' || repo.period === 'week'
                        ? 'НЕДЕЛЯ'
                        : repo.period === 'monthly' || repo.period === 'month'
                        ? 'МЕСЯЦ'
                        : repo.period.toUpperCase()}
                    </span>
                  )}

                  {/* Звёзды */}
                  {repo.stars > 0 && (
                    <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-amber-950/60 text-amber-300 border border-amber-600/50 flex items-center gap-1.5">
                      <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
                      <span>{repo.stars.toLocaleString()}</span>
                      {repo.stars_this_period > 0 && (
                        <span className="text-amber-400/90 font-medium">
                          (+{repo.stars_this_period.toLocaleString()} {repo.period === 'monthly' || repo.period === 'month' ? 'в месяц' : 'в нед.'})
                        </span>
                      )}
                    </span>
                  )}

                  {/* Основной язык */}
                  {repo.language && (
                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-[#12121A] text-zinc-300 border border-[#2D1B4E] flex items-center gap-1">
                      <Code2 className="w-3 h-3 text-zinc-400" />
                      {repo.language}
                    </span>
                  )}

                  {/* Направления */}
                  {repo.directions.map((d: string, dIdx: number) => (
                    <span
                      key={dIdx}
                      className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-sky-950/60 text-sky-300 border border-sky-700/50"
                    >
                      🧭 {GITHUB_DIRECTIONS[d] || d}
                    </span>
                  ))}

                  {/* Типы задач */}
                  {repo.task_types.map((t: string, tIdx: number) => (
                    <span
                      key={tIdx}
                      className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-purple-950/60 text-purple-300 border border-purple-700/50"
                    >
                      🎯 {GITHUB_TASK_TYPES[t] || t}
                    </span>
                  ))}

                  {/* Теги */}
                  {repo.tags.slice(0, 4).map((tag: string, tIdx: number) => (
                    <span
                      key={tIdx}
                      className="text-[11px] px-2 py-0.5 rounded-md bg-[#1E1B4B] text-purple-300 border border-[#3B0764]"
                    >
                      {tag}
                    </span>
                  ))}
                </div>

                {/* Название репозитория */}
                <h3 className="text-lg font-semibold text-white group-hover:text-sky-300 transition-colors">
                  <a
                    href={repo.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-2 hover:underline font-mono"
                  >
                    {repo.repo_name}
                    <ExternalLink className="w-4 h-4 opacity-50 group-hover:opacity-100 transition-opacity" />
                  </a>
                </h3>

                {/* Описание — полный размер без обрезки */}
                {repo.summary && (
                  <p className="text-sm text-zinc-300 mt-2 leading-relaxed whitespace-pre-line">
                    {repo.summary}
                  </p>
                )}

                {/* Прямая ссылка и кнопка ассистента */}
                <div className="mt-3 pt-2 text-xs flex items-center justify-between">
                  <button
                    onClick={() =>
                      onAskAssistant?.(
                        `Расскажи подробно про репозиторий "${repo.repo_name}": стек технологий, архитектура, ключевые возможности и как развернуть проект`,
                        {
                          id: `gh_${repo.repo_name}`,
                          title: repo.repo_name,
                          category: 'репозиторий',
                          url: repo.url,
                          summary: repo.summary,
                          full_description: repo.summary,
                          tags: Array.isArray(repo.tags) ? repo.tags : repo.tags ? [String(repo.tags)] : [],
                          metrics: {
                            stars: repo.stars,
                            forks: repo.forks,
                          },
                          details: {
                            directions: repo.directions,
                            task_types: repo.task_types,
                            language: repo.language,
                            period: repo.period,
                          },
                        }
                      )
                    }
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-purple-600/20 hover:bg-purple-600/40 text-purple-300 hover:text-white border border-purple-500/30 text-[11px] font-semibold transition-all cursor-pointer shadow-sm"
                    title="Спросить у AI Ассистента"
                  >
                    <Sparkles className="w-3 h-3 text-purple-400" />
                    <span>Спросить ассистента</span>
                  </button>

                  <a
                    href={repo.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sky-400 hover:text-sky-300 font-medium inline-flex items-center gap-1"
                  >
                    Открыть на GitHub →
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
