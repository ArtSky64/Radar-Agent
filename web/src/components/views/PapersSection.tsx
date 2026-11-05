import React, { useState, useMemo } from 'react';
import {
  RotateCw,
  Search,
  ExternalLink,
  BookOpen,
  FileText,
  Code,
  Flame,
  CheckCircle2,
  XCircle,
  Link as LinkIcon,
} from 'lucide-react';
import type { ArticleItem, RelatedLink } from '../../types/domain';

interface PapersSectionProps {
  articles: ArticleItem[];
  onRefresh: () => void;
  isRefreshing?: boolean;
}

export const PapersSection: React.FC<PapersSectionProps> = ({
  articles,
  onRefresh,
  isRefreshing = false,
}) => {
  const [activeSubTab, setActiveSubTab] = useState<'week' | 'month'>('week');
  const [searchQuery, setSearchQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<string>('Все источники');
  const [hasCodeFilter, setHasCodeFilter] = useState<string>('Все');
  const [sortOption, setSortOption] = useState<string>('По трендовости (Upvotes 🔥)');
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);

  // Извлекаем только материалы с типом "статья"
  const rawPapers = useMemo(() => {
    return articles.filter(
      (a) =>
        (a.source_type === 'статья' || (!a.source_type && !a.repo_name)) &&
        !(a.summary || '').startsWith('Связанный материал к статье:')
    );
  }, [articles]);

  // Уникальные топики
  const availableTopics = useMemo(() => {
    const set = new Set<string>();
    for (const p of rawPapers) {
      if (p.topic_tag && p.topic_tag.trim()) {
        set.add(p.topic_tag.trim());
      }
    }
    return Array.from(set).sort();
  }, [rawPapers]);

  // Фильтрация
  const filteredPapers = useMemo(() => {
    return rawPapers.filter((p) => {
      // Поиск
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const title = (p.title || '').toLowerCase();
        const sum = (p.summary || '').toLowerCase();
        if (!title.includes(q) && !sum.includes(q)) return false;
      }

      // Источник
      if (sourceFilter === 'Hugging Face Papers') {
        const isHF =
          (p.title || '').startsWith('[HF') ||
          (p.source_url || '').includes('huggingface.co');
        if (!isHF) return false;
      } else if (sourceFilter === 'Papers with Code') {
        const isPwC =
          (p.title || '').includes('PwC') ||
          (p.source_url || '').includes('paperswithcode');
        if (!isPwC) return false;
      }

      // Наличие кода
      const relLinks = Array.isArray(p.related_links) ? p.related_links : [];
      const hasCode =
        Boolean(p.has_code) ||
        relLinks.some(
          (r) =>
            (r.type === 'github' || r.type === 'code' || (r.url && r.url.includes('github.com')))
        ) ||
        (p.summary || '').includes('github.com/') ||
        (p.source_url || '').includes('github.com/');

      if (hasCodeFilter === 'Только с кодом (True)' && !hasCode) return false;
      if (hasCodeFilter === 'Без кода (False)' && hasCode) return false;

      // Топики
      if (selectedTopics.length > 0) {
        if (!p.topic_tag || !selectedTopics.includes(p.topic_tag.trim())) return false;
      }

      return true;
    });
  }, [rawPapers, searchQuery, sourceFilter, hasCodeFilter, selectedTopics]);

  // Разбиение на неделю и месяц + сортировка
  const displayedPapers = useMemo(() => {
    let list = [...filteredPapers];

    if (activeSubTab === 'week') {
      list = list.filter((p) => p.period !== 'monthly');
    }

    if (sortOption === 'По трендовости (Upvotes 🔥)') {
      list.sort((a, b) => {
        const starsA = Number(a.stars || a.upvotes || 0);
        const starsB = Number(b.stars || b.upvotes || 0);
        return starsB - starsA;
      });
    } else if (sortOption === 'Сначала новые') {
      list.sort((a, b) => (b.rowid || 0) - (a.rowid || 0));
    }

    return list;
  }, [filteredPapers, activeSubTab, sortOption]);

  const pwcCount = useMemo(
    () => rawPapers.filter((p) => (p.title || '').includes('PwC')).length,
    [rawPapers]
  );
  const hfCount = useMemo(
    () => rawPapers.filter((p) => (p.title || '').startsWith('[HF')).length,
    [rawPapers]
  );

  const toggleTopic = (topic: string) => {
    setSelectedTopics((prev) =>
      prev.includes(topic) ? prev.filter((t) => t !== topic) : [...prev, topic]
    );
  };

  return (
    <div className="space-y-6">
      {/* Шапка раздела */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#2D1B4E]">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-pink-400" />
            Papers (Статьи)
          </h1>
          <p className="text-xs text-zinc-400 mt-1">
            Научные статьи и препринты из Hugging Face Papers и Papers with Code (PwC) — сквозной дедуп по arxiv_id, верификация ссылок на код и теги направлений ИИ.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold">
            <span className="px-2 py-0.5 rounded bg-sky-950/80 text-sky-300 border border-sky-600/50">
              HF: {hfCount}
            </span>
            <span className="px-2 py-0.5 rounded bg-purple-950/80 text-purple-300 border border-purple-600/50">
              PwC: {pwcCount}
            </span>
          </div>

          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-xl bg-purple-900/40 hover:bg-purple-800/40 text-purple-200 border border-purple-600/50 transition-all cursor-pointer disabled:opacity-50"
            title="Запустить балансированный сбор статей HF и PwC"
          >
            <RotateCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>Обновить статьи (HF + PwC)</span>
          </button>
        </div>
      </div>

      {/* Вкладки "Топ за неделю" / "Топ за месяц" */}
      <div className="flex gap-2 border-b border-[#2D1B4E] pb-2">
        <button
          onClick={() => setActiveSubTab('week')}
          className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeSubTab === 'week'
              ? 'bg-purple-600 text-white shadow-md'
              : 'bg-[#12121A] text-zinc-400 hover:text-white border border-[#2D1B4E]'
          }`}
        >
          🔥 Топ за неделю
        </button>
        <button
          onClick={() => setActiveSubTab('month')}
          className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeSubTab === 'month'
              ? 'bg-purple-600 text-white shadow-md'
              : 'bg-[#12121A] text-zinc-400 hover:text-white border border-[#2D1B4E]'
          }`}
        >
          📅 Топ за месяц
        </button>
      </div>

      {/* Панель фильтров */}
      <div className="p-4 rounded-xl bg-[#12121A] border border-[#2D1B4E] space-y-3.5 text-xs">
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          {/* Поиск */}
          <div className="sm:col-span-2 relative">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-zinc-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Поиск по названию или резюме статьи..."
              className="w-full bg-[#0A0A0F] border border-[#2D1B4E] rounded-lg pl-9 pr-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-purple-500"
            />
          </div>

          {/* Источник */}
          <div>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="w-full bg-[#0A0A0F] border border-[#2D1B4E] rounded-lg px-3 py-2 text-white focus:outline-none focus:border-purple-500"
            >
              <option value="Все источники">Все источники (HF + PwC)</option>
              <option value="Hugging Face Papers">Hugging Face Papers</option>
              <option value="Papers with Code">Papers with Code</option>
            </select>
          </div>

          {/* Наличие кода */}
          <div>
            <select
              value={hasCodeFilter}
              onChange={(e) => setHasCodeFilter(e.target.value)}
              className="w-full bg-[#0A0A0F] border border-[#2D1B4E] rounded-lg px-3 py-2 text-white focus:outline-none focus:border-purple-500"
            >
              <option value="Все">Код: Все статьи</option>
              <option value="Только с кодом (True)">Только с кодом (True)</option>
              <option value="Без кода (False)">Без кода (False)</option>
            </select>
          </div>
        </div>

        {/* Сортировка и выбор топиков */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <div className="flex items-center gap-2">
            <span className="text-zinc-400">Сортировка:</span>
            <select
              value={sortOption}
              onChange={(e) => setSortOption(e.target.value)}
              className="bg-[#0A0A0F] border border-[#2D1B4E] rounded-lg px-3 py-1.5 text-white focus:outline-none focus:border-purple-500"
            >
              <option value="По трендовости (Upvotes 🔥)">По трендовости (Upvotes 🔥)</option>
              <option value="Сначала новые">Сначала новые</option>
            </select>
          </div>

          <div className="text-zinc-400 font-mono">
            Найдено статей: <span className="text-white font-semibold">{displayedPapers.length}</span>
          </div>
        </div>

        {/* Топики */}
        {availableTopics.length > 0 && (
          <div>
            <div className="text-[11px] font-semibold text-zinc-400 mb-1.5">
              Тематические направления:
            </div>
            <div className="flex flex-wrap gap-1.5">
              {availableTopics.map((topic) => {
                const active = selectedTopics.includes(topic);
                return (
                  <button
                    key={topic}
                    onClick={() => toggleTopic(topic)}
                    className={`px-2.5 py-1 rounded-md text-[11px] border transition-all cursor-pointer ${
                      active
                        ? 'bg-pink-950/80 text-pink-300 border-pink-600 font-semibold'
                        : 'bg-[#0A0A0F] text-zinc-400 border-[#2D1B4E] hover:border-zinc-700'
                    }`}
                  >
                    #{topic}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Сброс фильтров */}
        {(searchQuery ||
          sourceFilter !== 'Все источники' ||
          hasCodeFilter !== 'Все' ||
          selectedTopics.length > 0) && (
          <div className="pt-1 flex justify-end">
            <button
              onClick={() => {
                setSearchQuery('');
                setSourceFilter('Все источники');
                setHasCodeFilter('Все');
                setSelectedTopics([]);
              }}
              className="text-[11px] text-purple-400 hover:text-purple-300 underline cursor-pointer"
            >
              Сбросить фильтры
            </button>
          </div>
        )}
      </div>

      {/* Список статей */}
      <div className="space-y-3">
        {displayedPapers.length === 0 ? (
          <div className="p-8 text-center rounded-xl bg-[#12121A] border border-[#2D1B4E] text-zinc-400 text-xs">
            Нет статей по выбранным фильтрам.
          </div>
        ) : (
          displayedPapers.map((paper, idx) => {
            const rawTitle = paper.title || 'Untitled Paper';
            const cleanTitle = rawTitle.replace(/^\[(HF|PwC)\]\s*/i, '');
            const sourceUrl = paper.source_url || paper.url || '#';
            const isPwC =
              rawTitle.includes('PwC') || sourceUrl.includes('paperswithcode');
            const isHF =
              rawTitle.startsWith('[HF') || sourceUrl.includes('huggingface.co');
            const platformName = isPwC ? 'Papers with Code' : isHF ? 'Hugging Face' : 'ArXiv';

            const relLinks: RelatedLink[] = Array.isArray(paper.related_links)
              ? paper.related_links
              : [];

            const hasCode =
              Boolean(paper.has_code) ||
              relLinks.some(
                (r) =>
                  r.type === 'github' ||
                  r.type === 'code' ||
                  (r.url && r.url.includes('github.com'))
              ) ||
              (paper.summary || '').includes('github.com/') ||
              sourceUrl.includes('github.com/');

            const upvotes = paper.stars || paper.upvotes || 0;

            return (
              <div
                key={paper.rowid || `${sourceUrl}-${idx}`}
                className="p-4 rounded-xl bg-gradient-to-b from-[#1A0E2B] to-[#160A25] border border-[#6D28D9]/70 hover:border-[#A855F7] transition-all duration-200 text-xs shadow-md"
              >
                {/* Бэйджи */}
                <div className="flex flex-wrap items-center gap-1.5 mb-2.5">
                  <span className="text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded bg-pink-950/80 text-pink-300 border border-pink-600">
                    СТАТЬЯ
                  </span>

                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                      isPwC
                        ? 'bg-purple-950/80 text-purple-300 border-purple-600'
                        : 'bg-sky-950/80 text-sky-300 border-sky-600'
                    }`}
                  >
                    {platformName}
                  </span>

                  {/* Наличие кода */}
                  {hasCode ? (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-500 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                      Код: True
                    </span>
                  ) : (
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-zinc-700 flex items-center gap-1">
                      <XCircle className="w-3 h-3 text-zinc-500" />
                      Код: False
                    </span>
                  )}

                  {/* Upvotes */}
                  {upvotes > 0 && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-950/80 text-amber-300 border border-amber-600 flex items-center gap-1">
                      <Flame className="w-3 h-3 fill-amber-400" />
                      {upvotes.toLocaleString()}
                    </span>
                  )}

                  {/* Топик */}
                  {paper.topic_tag && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-pink-950/40 text-pink-300 border border-pink-700/50">
                      #{paper.topic_tag}
                    </span>
                  )}
                </div>

                {/* Название статьи */}
                <h3 className="text-sm font-bold text-white hover:text-purple-300 transition-colors">
                  <a href={sourceUrl} target="_blank" rel="noreferrer" className="flex items-center gap-1.5">
                    {cleanTitle}
                    <ExternalLink className="w-3.5 h-3.5 opacity-50" />
                  </a>
                </h3>

                {/* Резюме / summary */}
                {paper.summary && (
                  <p className="text-zinc-300 mt-1.5 text-[11px] leading-relaxed line-clamp-3">
                    {paper.summary}
                  </p>
                )}

                {/* Связанные материалы: код, статья, демо */}
                {relLinks.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 mt-2.5 pt-2 border-t border-[#2D1B4E]/60">
                    {relLinks.map((rel, rIdx) => {
                      const rUrl = rel.url || '#';
                      const rName = rel.name || rUrl;
                      const isGit =
                        rel.type === 'github' ||
                        rel.type === 'code' ||
                        rUrl.includes('github.com');

                      return (
                        <a
                          key={rIdx}
                          href={rUrl}
                          target="_blank"
                          rel="noreferrer"
                          className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border transition-colors ${
                            isGit
                              ? 'bg-emerald-950/70 text-emerald-300 border-emerald-700/60 hover:bg-emerald-900/80'
                              : 'bg-zinc-900 text-zinc-300 border-zinc-700 hover:bg-zinc-800'
                          }`}
                        >
                          {isGit ? <Code className="w-3 h-3" /> : <LinkIcon className="w-3 h-3" />}
                          {isGit ? `Репозиторий кода ↗` : rName}
                        </a>
                      );
                    })}
                  </div>
                )}

                {/* Ссылка на источник */}
                <div className="mt-2.5 pt-1 flex justify-end">
                  <a
                    href={sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-purple-400 hover:text-purple-300 underline font-medium text-[11px]"
                  >
                    Читать на {platformName} →
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
