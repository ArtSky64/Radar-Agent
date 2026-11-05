import React, { useState, useMemo } from 'react';
import {
  Database,
  Search,
  Filter,
  ExternalLink,
  RefreshCw,
  Heart,
  Globe,
  Sparkles,
  Layers,
  Code,
  FileText,
  Bot,
  CheckCircle2,
  XCircle,
} from 'lucide-react';
import type { ArticleItem, RelatedLink } from '../../types/domain';

interface DatasetsSectionProps {
  articles: ArticleItem[];
  onRefresh?: () => Promise<void>;
  isRefreshing?: boolean;
}

type DatasetTab = 'ru' | 'global' | 'kaggle' | 'all';
type SortOption = 'ru_rank' | 'global_rank' | 'likes' | 'newest';

export const DatasetsSection: React.FC<DatasetsSectionProps> = ({
  articles,
  onRefresh,
  isRefreshing = false,
}) => {
  const [activeTab, setActiveTab] = useState<DatasetTab>('ru');
  const [searchQuery, setSearchQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'all' | 'hf' | 'kaggle'>('all');
  const [sortOption, setSortOption] = useState<SortOption>('ru_rank');
  const [spacesFilter, setSpacesFilter] = useState<'all' | 'has_spaces' | 'no_spaces'>('all');
  const [selectedLanguage, setSelectedLanguage] = useState<string>('all');
  const [selectedTag, setSelectedTag] = useState<string>('all');
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  // Извлекаем только материалы с типом "датасет"
  const rawDatasets = useMemo(() => {
    return articles.filter(
      (a) =>
        a.source_type === 'датасет' &&
        !(a.summary || '').startsWith('Связанный материал к статье:')
    );
  }, [articles]);

  // Список доступных языков
  const availableLanguages = useMemo(() => {
    const langs = new Set<string>();
    rawDatasets.forEach((d) => {
      if (d.language) {
        d.language.split(',').forEach((l) => {
          const trimmed = l.trim();
          if (trimmed) langs.add(trimmed);
        });
      }
    });
    return Array.from(langs).sort();
  }, [rawDatasets]);

  // Список уникальных тегов
  const availableTags = useMemo(() => {
    const tags = new Set<string>();
    rawDatasets.forEach((d) => {
      const itemTags = Array.isArray(d.tags)
        ? d.tags
        : typeof d.tags === 'string'
        ? d.tags.split(',')
        : [];
      itemTags.forEach((t) => {
        const clean = t.trim();
        if (clean && clean.length < 30) tags.add(clean);
      });
    });
    return Array.from(tags).slice(0, 30);
  }, [rawDatasets]);

  // Фильтрация
  const filteredDatasets = useMemo(() => {
    return rawDatasets.filter((d) => {
      // Поиск
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const title = (d.title || '').toLowerCase();
        const summary = (d.summary || '').toLowerCase();
        const repo = (d.repo_name || '').toLowerCase();
        if (!title.includes(q) && !summary.includes(q) && !repo.includes(q)) {
          return false;
        }
      }

      // Источник
      const sourceUrl = (d.source_url || '').toLowerCase();
      const title = (d.title || '');
      if (sourceFilter === 'hf') {
        if (!sourceUrl.includes('huggingface.co') && !title.startsWith('[HF')) return false;
      } else if (sourceFilter === 'kaggle') {
        if (!sourceUrl.includes('kaggle.com') && !title.startsWith('[Kaggle')) return false;
      }

      // Spaces
      if (spacesFilter === 'has_spaces' && !d.has_spaces) return false;
      if (spacesFilter === 'no_spaces' && d.has_spaces) return false;

      // Язык
      if (selectedLanguage !== 'all') {
        const dLang = (d.language || '').toLowerCase();
        if (!dLang.includes(selectedLanguage.toLowerCase())) return false;
      }

      // Тег
      if (selectedTag !== 'all') {
        const itemTags = Array.isArray(d.tags) ? d.tags : [];
        if (!itemTags.includes(selectedTag)) return false;
      }

      return true;
    });
  }, [rawDatasets, searchQuery, sourceFilter, spacesFilter, selectedLanguage, selectedTag]);

  // Распределение по вкладкам
  const tabDatasets = useMemo(() => {
    let list = [...filteredDatasets];

    if (activeTab === 'ru') {
      list = list.filter(
        (a) =>
          (a.rank_ru || 0) > 0 ||
          (a.language || '').toLowerCase().includes('ru') ||
          (Array.isArray(a.tags) && a.tags.includes('#Russian'))
      );
      list.sort((a, b) => {
        const rankA = (a.rank_ru || 0) > 0 ? (a.rank_ru || 0) : 9999;
        const rankB = (b.rank_ru || 0) > 0 ? (b.rank_ru || 0) : 9999;
        if (rankA !== rankB) return rankA - rankB;
        return (b.stars || 0) - (a.stars || 0);
      });
      return list;
    }

    if (activeTab === 'global') {
      list = list.filter(
        (a) =>
          (a.rank_global || 0) > 0 &&
          ((a.source_url || '').toLowerCase().includes('huggingface.co') ||
            (a.title || '').startsWith('[HF'))
      );
      list.sort((a, b) => {
        const rankA = (a.rank_global || 0) > 0 ? (a.rank_global || 0) : 9999;
        const rankB = (b.rank_global || 0) > 0 ? (b.rank_global || 0) : 9999;
        if (rankA !== rankB) return rankA - rankB;
        return (b.stars || 0) - (a.stars || 0);
      });
      return list;
    }

    if (activeTab === 'kaggle') {
      list = list.filter(
        (a) =>
          (a.source_url || '').toLowerCase().includes('kaggle.com') ||
          (a.title || '').startsWith('[Kaggle')
      );
      list.sort((a, b) => {
        const rankA = (a.rank_global || 0) > 0 ? (a.rank_global || 0) : (a.rowid || 9999);
        const rankB = (b.rank_global || 0) > 0 ? (b.rank_global || 0) : (b.rowid || 9999);
        return rankA - rankB;
      });
      return list;
    }

    // Все датасеты (по выбранной сортировке)
    list.sort((a, b) => {
      if (sortOption === 'ru_rank') {
        const rankA = (a.rank_ru || 0) > 0 ? (a.rank_ru || 0) : 9999;
        const rankB = (b.rank_ru || 0) > 0 ? (b.rank_ru || 0) : 9999;
        if (rankA !== rankB) return rankA - rankB;
        return (b.stars || 0) - (a.stars || 0);
      }
      if (sortOption === 'global_rank') {
        const rankA = (a.rank_global || 0) > 0 ? (a.rank_global || 0) : 9999;
        const rankB = (b.rank_global || 0) > 0 ? (b.rank_global || 0) : 9999;
        if (rankA !== rankB) return rankA - rankB;
        return (b.stars || 0) - (a.stars || 0);
      }
      if (sortOption === 'likes') {
        return (b.stars || 0) - (a.stars || 0);
      }
      if (sortOption === 'newest') {
        return (b.rowid || 0) - (a.rowid || 0);
      }
      return 0;
    });

    return list;
  }, [filteredDatasets, activeTab, sortOption]);

  const handleRefreshClick = async () => {
    if (onRefresh) {
      await onRefresh();
      return;
    }
    try {
      setRefreshMessage('Запуск сбора датасетов в фоне...');
      const res = await fetch('/datasets/refresh', { method: 'POST' });
      if (res.ok) {
        setRefreshMessage('Сбор запущен успешно!');
      } else {
        setRefreshMessage('Ошибка запуска сбора.');
      }
    } catch (e) {
      setRefreshMessage('Не удалось соединиться с сервером.');
    }
    setTimeout(() => setRefreshMessage(null), 4000);
  };

  const ruCount = useMemo(() => {
    return rawDatasets.filter(
      (a) =>
        (a.rank_ru || 0) > 0 ||
        (a.language || '').toLowerCase().includes('ru') ||
        (Array.isArray(a.tags) && a.tags.includes('#Russian'))
    ).length;
  }, [rawDatasets]);

  const hfGlobalCount = useMemo(() => {
    return rawDatasets.filter(
      (a) =>
        (a.rank_global || 0) > 0 &&
        ((a.source_url || '').toLowerCase().includes('huggingface.co') ||
          (a.title || '').startsWith('[HF'))
    ).length;
  }, [rawDatasets]);

  const kaggleCount = useMemo(() => {
    return rawDatasets.filter(
      (a) =>
        (a.source_url || '').toLowerCase().includes('kaggle.com') ||
        (a.title || '').startsWith('[Kaggle')
    ).length;
  }, [rawDatasets]);

  return (
    <div className="space-y-6">
      {/* Шапка раздела */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <Database className="w-7 h-7 text-emerald-400" />
              Датасеты
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
              {rawDatasets.length} в базе
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Датасеты из Hugging Face и Kaggle — отобраны по трендам ИИ-агентом с описанием, метриками и тегами.
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
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-950/60 hover:bg-emerald-900/60 text-emerald-300 border border-emerald-700/50 transition-all shadow-sm disabled:opacity-50"
            title="Запустить сбор трендовых датасетов Hugging Face и Kaggle"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            Обновить датасеты
          </button>
        </div>
      </div>

      {/* Вкладки направлений */}
      <div className="flex items-center gap-2 border-b border-border/80 pb-1">
        <button
          onClick={() => setActiveTab('ru')}
          className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm font-medium transition-all ${
            activeTab === 'ru'
              ? 'bg-emerald-950/40 text-emerald-400 border-b-2 border-emerald-400 font-semibold'
              : 'text-muted-foreground hover:text-white hover:bg-secondary/40'
          }`}
        >
          <span>🇷🇺 Российские тренды (RU)</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-900/50 text-emerald-300">
            {ruCount}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('global')}
          className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm font-medium transition-all ${
            activeTab === 'global'
              ? 'bg-purple-950/40 text-purple-400 border-b-2 border-purple-400 font-semibold'
              : 'text-muted-foreground hover:text-white hover:bg-secondary/40'
          }`}
        >
          <span>🌍 Мировые тренды HF</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-purple-900/50 text-purple-300">
            {hfGlobalCount}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('kaggle')}
          className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm font-medium transition-all ${
            activeTab === 'kaggle'
              ? 'bg-amber-950/40 text-amber-400 border-b-2 border-amber-400 font-semibold'
              : 'text-muted-foreground hover:text-white hover:bg-secondary/40'
          }`}
        >
          <span>🏆 Kaggle Trending</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-900/50 text-amber-300">
            {kaggleCount}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('all')}
          className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm font-medium transition-all ${
            activeTab === 'all'
              ? 'bg-secondary text-white border-b-2 border-primary font-semibold'
              : 'text-muted-foreground hover:text-white hover:bg-secondary/40'
          }`}
        >
          <span>📋 Все датасеты</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
            {filteredDatasets.length}
          </span>
        </button>
      </div>

      {/* Панель фильтров */}
      <div className="p-4 rounded-xl bg-[#12121A] border border-[#2D1B4E] space-y-4 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {/* Поиск */}
          <div className="relative md:col-span-2">
            <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
            <input
              type="text"
              placeholder="Поиск по названию, описанию или тегам датасета..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 text-sm rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] focus:border-purple-500 focus:outline-none text-white placeholder-muted-foreground"
            />
          </div>

          {/* Источник */}
          <div>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value as any)}
              className="w-full px-3 py-2 text-sm rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="all">Все платформы</option>
              <option value="hf">Hugging Face</option>
              <option value="kaggle">Kaggle</option>
            </select>
          </div>

          {/* Сортировка */}
          <div>
            <select
              value={sortOption}
              onChange={(e) => setSortOption(e.target.value as any)}
              className="w-full px-3 py-2 text-sm rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="ru_rank">По российскому рейтингу (RU)</option>
              <option value="global_rank">По мировому рейтингу (Global)</option>
              <option value="likes">По лайкам / голосам</option>
              <option value="newest">Сначала новые</option>
            </select>
          </div>
        </div>

        {/* Дополнительные фильтры: Spaces, Язык, Тег */}
        <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-[#2D1B4E]/60 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Spaces:</span>
            <select
              value={spacesFilter}
              onChange={(e) => setSpacesFilter(e.target.value as any)}
              className="px-2.5 py-1 rounded bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="all">Все</option>
              <option value="has_spaces">Только со Spaces (True)</option>
              <option value="no_spaces">Без Spaces (False)</option>
            </select>
          </div>

          {availableLanguages.length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Язык:</span>
              <select
                value={selectedLanguage}
                onChange={(e) => setSelectedLanguage(e.target.value)}
                className="px-2.5 py-1 rounded bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="all">Все языки</option>
                {availableLanguages.map((lang) => (
                  <option key={lang} value={lang}>
                    {lang.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>
          )}

          {availableTags.length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Тег:</span>
              <select
                value={selectedTag}
                onChange={(e) => setSelectedTag(e.target.value)}
                className="px-2.5 py-1 rounded bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="all">Все теги</option>
                {availableTags.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          )}

          {(searchQuery ||
            sourceFilter !== 'all' ||
            spacesFilter !== 'all' ||
            selectedLanguage !== 'all' ||
            selectedTag !== 'all') && (
            <button
              onClick={() => {
                setSearchQuery('');
                setSourceFilter('all');
                setSpacesFilter('all');
                setSelectedLanguage('all');
                setSelectedTag('all');
              }}
              className="text-purple-400 hover:text-purple-300 underline ml-auto cursor-pointer"
            >
              Сбросить фильтры
            </button>
          )}
        </div>
      </div>

      {/* Список карточек датасетов */}
      <div className="space-y-4">
        {tabDatasets.length === 0 ? (
          <div className="p-8 text-center rounded-xl bg-[#12121A] border border-[#2D1B4E] text-muted-foreground">
            <Database className="w-10 h-10 mx-auto mb-3 opacity-40 text-emerald-400" />
            <p className="text-base font-medium text-white">Датасеты не найдены</p>
            <p className="text-xs text-muted-foreground mt-1">
              Попробуйте изменить поисковый запрос или сбросить активные фильтры.
            </p>
          </div>
        ) : (
          tabDatasets.map((d, idx) => {
            const rawTitle = d.title || d.repo_name || 'Без названия';
            const cleanTitle = rawTitle.replace(/^\[(HF|Kaggle)\]\s*/i, '');
            const sourceUrl = d.source_url || d.url || '';
            const isKaggle =
              sourceUrl.toLowerCase().includes('kaggle.com') || rawTitle.startsWith('[Kaggle');
            const isHF =
              sourceUrl.toLowerCase().includes('huggingface.co') || rawTitle.startsWith('[HF');
            const platformName = isKaggle ? 'Kaggle' : isHF ? 'Hugging Face' : 'Датасет';

            const rankRu = d.rank_ru || 0;
            const rankGlobal = d.rank_global || 0;
            const likesCount = d.stars || d.upvotes || 0;
            const language = (d.language || '').trim();

            const relatedLinks: RelatedLink[] = Array.isArray(d.related_links)
              ? d.related_links
              : [];

            // Ищем топ моделей, обученных на датасете
            let topModels: string[] = [];
            const modelsCatalogLink = relatedLinks.find(
              (r) => (r.type || '').toLowerCase() === 'models_catalog'
            );
            if (modelsCatalogLink && Array.isArray(modelsCatalogLink.top_items)) {
              topModels = modelsCatalogLink.top_items.slice(0, 3);
            }

            return (
              <div
                key={d.rowid || `${sourceUrl}-${idx}`}
                className="p-5 rounded-2xl bg-gradient-to-b from-[#1A0E2B] to-[#160A25] border border-[#6D28D9]/70 hover:border-[#A855F7] transition-all duration-200 shadow-md hover:shadow-purple-900/20 group"
              >
                {/* Верхняя строка бэйджей */}
                <div className="flex flex-wrap items-center gap-2 mb-3">
                  {/* Тип контента */}
                  <span className="text-[11px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-md bg-emerald-950/80 text-emerald-400 border border-emerald-600/50">
                    ДАТАСЕТ
                  </span>

                  {/* Платформа */}
                  <span
                    className={`text-[11px] font-bold px-2.5 py-0.5 rounded-md border ${
                      isKaggle
                        ? 'bg-sky-950/80 text-sky-400 border-sky-600/50'
                        : 'bg-amber-950/80 text-amber-300 border-amber-600/50'
                    }`}
                  >
                    {platformName}
                  </span>

                  {/* Язык */}
                  {language && (
                    <span className="text-[11px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-md bg-[#12121A] text-zinc-300 border border-[#2D1B4E]">
                      {language}
                    </span>
                  )}

                  {/* Лайки / голоса */}
                  {likesCount > 0 && (
                    <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-amber-950/60 text-amber-300 border border-amber-600/50 flex items-center gap-1">
                      <Heart className="w-3 h-3 fill-amber-400 text-amber-400" />
                      {likesCount.toLocaleString()}
                    </span>
                  )}

                  {/* Ранги */}
                  {rankRu > 0 && (
                    <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-emerald-950/80 text-emerald-300 border border-emerald-500/50">
                      🏆 RU ТОП #{rankRu}
                    </span>
                  )}

                  {rankGlobal > 0 && (
                    <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-purple-950/80 text-purple-300 border border-purple-500/50">
                      🌍 Мировой #{rankGlobal}
                    </span>
                  )}

                  {/* Статус Spaces */}
                  {d.has_spaces ? (
                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-fuchsia-950/60 text-fuchsia-300 border border-fuchsia-700/50 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3 text-fuchsia-400" />
                      Spaces Demo
                    </span>
                  ) : null}

                  {/* Теги */}
                  {Array.isArray(d.tags) &&
                    d.tags.slice(0, 4).map((tag, tIdx) => (
                      <span
                        key={tIdx}
                        className="text-[11px] px-2 py-0.5 rounded-md bg-[#1E1B4B] text-purple-300 border border-[#3B0764]"
                      >
                        {tag}
                      </span>
                    ))}
                </div>

                {/* Название датасета */}
                <h3 className="text-lg font-semibold text-white group-hover:text-purple-300 transition-colors">
                  <a
                    href={sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-2 hover:underline"
                  >
                    {cleanTitle}
                    <ExternalLink className="w-4 h-4 opacity-50 group-hover:opacity-100 transition-opacity" />
                  </a>
                </h3>

                {/* Описание / summary */}
                {d.summary && (
                  <p className="text-sm text-zinc-300 mt-2 leading-relaxed whitespace-pre-line line-clamp-4">
                    {d.summary}
                  </p>
                )}

                {/* Блок обученных моделей (ТЗ п.5) */}
                {topModels.length > 0 && (
                  <div className="mt-3 p-3 rounded-lg bg-[#0E071A] border border-[#3B156E]/60 text-xs">
                    <div className="font-semibold text-purple-300 mb-1.5 flex items-center gap-1.5">
                      <Bot className="w-3.5 h-3.5 text-purple-400" />
                      Топ моделей, обученных на этом датасете:
                    </div>
                    <div className="space-y-1 text-zinc-300">
                      {topModels.map((m, mIdx) => (
                        <div key={mIdx} className="flex items-center gap-1.5">
                          <span className="text-purple-400">•</span>
                          <span className="font-mono text-[11px]">{m}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Связанные кнопки и материалы (ТЗ п.5) */}
                {relatedLinks.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-[#2D1B4E]/60">
                    {relatedLinks.map((rel, rIdx) => {
                      const rType = (rel.type || 'link').toLowerCase();
                      const rUrl = rel.url || '#';
                      const rName = rel.name || rUrl;

                      if (rType === 'paper') {
                        return (
                          <a
                            key={rIdx}
                            href={rUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md bg-purple-950/70 text-purple-300 border border-purple-700/60 hover:bg-purple-900/80 transition-colors"
                          >
                            <FileText className="w-3 h-3 text-purple-400" />
                            Статья: {rName}
                          </a>
                        );
                      }

                      if (rType === 'models_catalog') {
                        return (
                          <a
                            key={rIdx}
                            href={rUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md bg-sky-950/70 text-sky-300 border border-sky-700/60 hover:bg-sky-900/80 transition-colors"
                          >
                            <Bot className="w-3 h-3 text-sky-400" />
                            Обученные модели ↗
                          </a>
                        );
                      }

                      if (rType === 'spaces_catalog') {
                        return (
                          <a
                            key={rIdx}
                            href={rUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md bg-fuchsia-950/70 text-fuchsia-300 border border-fuchsia-700/60 hover:bg-fuchsia-900/80 transition-colors"
                          >
                            <Layers className="w-3 h-3 text-fuchsia-400" />
                            Демо Spaces ↗
                          </a>
                        );
                      }

                      if (rType === 'kaggle_code') {
                        return (
                          <a
                            key={rIdx}
                            href={rUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md bg-amber-950/70 text-amber-300 border border-amber-700/60 hover:bg-amber-900/80 transition-colors"
                          >
                            <Code className="w-3 h-3 text-amber-400" />
                            Ноутбуки Kaggle ↗
                          </a>
                        );
                      }

                      return (
                        <a
                          key={rIdx}
                          href={rUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md bg-zinc-900 text-zinc-300 border border-zinc-700 hover:bg-zinc-800 transition-colors"
                        >
                          <ExternalLink className="w-3 h-3" />
                          {rName}
                        </a>
                      );
                    })}
                  </div>
                )}

                {/* Прямая ссылка на источник */}
                {sourceUrl && (
                  <div className="mt-3 pt-2 text-xs">
                    <a
                      href={sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-purple-400 hover:text-purple-300 font-medium inline-flex items-center gap-1"
                    >
                      Открыть на {platformName} →
                    </a>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
