import React, { useState, useEffect, useRef } from 'react';
import {
  Bot,
  User,
  Send,
  Sparkles,
  RefreshCw,
  Database,
  ExternalLink,
  Trash2,
  Sliders,
  Star,
  Download,
  Heart,
  ShieldAlert,
  Palette,
  MessageSquare,
  Plus,
  X,
} from 'lucide-react';
import type { RAGCard, CardContext } from '../../types/domain';
import { MarkdownRenderer } from '../ui/MarkdownRenderer';

export interface RAGMessage {
  role: 'user' | 'assistant';
  content: string;
  cards?: RAGCard[];
  action?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: RAGMessage[];
  createdAt: number;
  activeCard?: CardContext;
}

interface CatalogStats {
  всего?: number;
  датасеты?: number;
  модели?: number;
  репозитории?: number;
  статьи?: number;
}

export interface RAGSectionProps {
  sessions?: ChatSession[];
  setSessions?: React.Dispatch<React.SetStateAction<ChatSession[]>>;
  activeSessionId?: string;
  setActiveSessionId?: (id: string) => void;
  isSidePanel?: boolean;
  onClose?: () => void;
  pendingPrompt?: { text: string; cardContext?: CardContext } | string | null;
  onClearPendingPrompt?: () => void;
}

export const RAGSection: React.FC<RAGSectionProps> = ({
  sessions: externalSessions,
  setSessions: externalSetSessions,
  activeSessionId: externalActiveId,
  setActiveSessionId: externalSetActiveId,
  isSidePanel = false,
  onClose,
  pendingPrompt,
  onClearPendingPrompt,
}) => {
  // Локальный фолбек для сессий, если не переданы извне
  const [internalSessions, setInternalSessions] = useState<ChatSession[]>(() => [
    {
      id: 'session_' + Date.now(),
      title: 'Диалог 1',
      messages: [],
      createdAt: Date.now(),
    },
  ]);
  const [internalActiveId, setInternalActiveId] = useState<string>(
    () => internalSessions[0]?.id || 'default'
  );

  const sessions = externalSessions !== undefined ? externalSessions : internalSessions;
  const setSessions = externalSetSessions || setInternalSessions;
  const activeSessionId = externalActiveId !== undefined ? externalActiveId : internalActiveId;
  const setActiveSessionId = externalSetActiveId || setInternalActiveId;

  // Текущая активная сессия
  const activeSession =
    sessions.find((s) => s.id === activeSessionId) ||
    sessions[0] || {
      id: 'default',
      title: 'Диалог 1',
      messages: [],
      createdAt: Date.now(),
    };

  const messages = activeSession.messages;

  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [maxSources, setMaxSources] = useState<number>(5);
  const [catalogStats, setCatalogStats] = useState<CatalogStats | null>(null);
  const [isReindexing, setIsReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, activeSessionId]);

  useEffect(() => {
    if (pendingPrompt) {
      if (typeof pendingPrompt === 'string' && pendingPrompt.trim()) {
        sendMessage(pendingPrompt.trim());
        onClearPendingPrompt?.();
      } else if (typeof pendingPrompt === 'object' && pendingPrompt.text && pendingPrompt.text.trim()) {
        sendMessage(pendingPrompt.text.trim(), pendingPrompt.cardContext);
        onClearPendingPrompt?.();
      }
    }
  }, [pendingPrompt]);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch('/rag/stats');
      if (res.ok) {
        const json = await res.json();
        if (json.status === 'success' && json.data) {
          setCatalogStats(json.data);
        }
      }
    } catch {
      // Игнорируем сетевые сбои префлайта
    }
  };

  const handleReindex = async () => {
    setIsReindexing(true);
    setReindexMsg('Переиндексация базы...');
    try {
      const res = await fetch('/rag/reindex', { method: 'POST' });
      const json = await res.json();
      if (json.status === 'success') {
        setReindexMsg(`Готово (${json.indexed_count || 0} сущностей)`);
        await fetchStats();
      } else {
        setReindexMsg(`Ошибка: ${json.message || 'Сбой'}`);
      }
    } catch {
      setReindexMsg('Ошибка связи с сервером');
    } finally {
      setIsReindexing(false);
      setTimeout(() => setReindexMsg(null), 4000);
    }
  };

  // Создать новую независимую вкладку диалога
  const handleCreateNewSession = () => {
    const newNum = sessions.length + 1;
    const newSession: ChatSession = {
      id: `session_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      title: `Диалог ${newNum}`,
      messages: [],
      createdAt: Date.now(),
    };
    setSessions((prev) => [...prev, newSession]);
    setActiveSessionId(newSession.id);
  };

  // Закрыть вкладку диалога
  const handleCloseSession = (sessionIdToClose: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (sessions.length <= 1) {
      // Если это единственная вкладка — очищаем её сообщения
      const resetSession: ChatSession = {
        id: `session_${Date.now()}`,
        title: 'Диалог 1',
        messages: [],
        createdAt: Date.now(),
      };
      setSessions([resetSession]);
      setActiveSessionId(resetSession.id);
      return;
    }

    const remaining = sessions.filter((s) => s.id !== sessionIdToClose);
    setSessions(remaining);
    if (activeSessionId === sessionIdToClose) {
      setActiveSessionId(remaining[remaining.length - 1].id);
    }
  };

  // Отправка сообщения в текущую вкладку
  const sendMessage = async (text: string, cardContext?: CardContext) => {
    if (!text.trim() || isLoading) return;

    const userMsg: RAGMessage = { role: 'user', content: text.trim() };
    const currentSessionId = activeSession.id;
    const updatedMessages = [...messages, userMsg];
    const effectiveCardContext = cardContext || activeSession.activeCard;
    const isInitialCardBreakdown = !!cardContext && messages.length === 0;

    // Обновляем состояние сообщений текущей вкладки и присваиваем ей осмысленное название
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id === currentSessionId) {
          let title = s.title;
          if (s.messages.length === 0 || /^Диалог \d+$/.test(title) || title === 'Новый чат') {
            title = text.trim().slice(0, 28) + (text.trim().length > 28 ? '...' : '');
          }
          return {
            ...s,
            title,
            activeCard: cardContext || s.activeCard,
            messages: updatedMessages,
          };
        }
        return s;
      })
    );

    setInputText('');
    setIsLoading(true);

    try {
      const res = await fetch('/rag/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // Передаем строго историю ТЕКУЩЕЙ вкладки!
          messages: updatedMessages.map((m) => ({ role: m.role, content: m.content })),
          category: selectedCategory,
          max_sources: isInitialCardBreakdown ? 1 : maxSources,
          top_k: isInitialCardBreakdown ? 1 : maxSources,
          card_context: effectiveCardContext || null,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP error ${res.status}`);
      }

      const json = await res.json();
      if (json.status === 'success' && json.data) {
        const assistantMsg: RAGMessage = {
          role: 'assistant',
          content: json.data.content || 'Ответ сформирован.',
          cards: json.data.cards || [],
          action: json.data.action,
        };
        setSessions((prev) =>
          prev.map((s) =>
            s.id === currentSessionId
              ? { ...s, messages: [...s.messages, assistantMsg] }
              : s
          )
        );
      } else {
        setSessions((prev) =>
          prev.map((s) =>
            s.id === currentSessionId
              ? {
                  ...s,
                  messages: [
                    ...s.messages,
                    {
                      role: 'assistant',
                      content: `Ошибка: ${json.message || 'Не удалось сформировать ответ.'}`,
                    },
                  ],
                }
              : s
          )
        );
      }
    } catch (err: any) {
      setSessions((prev) =>
        prev.map((s) =>
          s.id === currentSessionId
            ? {
                ...s,
                messages: [
                  ...s.messages,
                  {
                    role: 'assistant',
                    content: `Не удалось связаться с сервером (${err.message || 'сетевая ошибка'}). Убедитесь, что бэкенд запущен.`,
                  },
                ],
              }
            : s
        )
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputText);
    }
  };

  const getCategoryBadge = (cat: string) => {
    const c = (cat || '').toLowerCase();
    if (c === 'модель') {
      return {
        label: 'МОДЕЛЬ',
        className: 'bg-purple-950/80 text-purple-300 border-purple-600/60',
      };
    }
    if (c === 'датасет') {
      return {
        label: 'ДАТАСЕТ',
        className: 'bg-emerald-950/80 text-emerald-300 border-emerald-600/60',
      };
    }
    if (c === 'репозиторий') {
      return {
        label: 'РЕПОЗИТОРИЙ',
        className: 'bg-sky-950/80 text-sky-300 border-sky-600/60',
      };
    }
    return {
      label: 'СТАТЬЯ',
      className: 'bg-amber-950/80 text-amber-300 border-amber-600/60',
    };
  };

  // =========================================================================
  // РЕЖИМ 1: БОКОВАЯ ДОК-ПАНЕЛЬ (SIDE PANEL / DRAWER)
  // =========================================================================
  if (isSidePanel) {
    return (
      <div className="h-full flex flex-col justify-between overflow-hidden bg-[#0c0c14] text-zinc-300 font-sans select-none">
        {/* Шапка боковой панели */}
        <div className="px-4 py-2.5 border-b border-[#2D1B4E] bg-[#120B24] flex items-center justify-between shrink-0 shadow-sm">
          <div className="flex items-center gap-2">
            <Bot className="w-4 h-4 text-purple-400" />
            <span className="text-xs font-bold text-white tracking-wide">AI Ассистент</span>
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          </div>

          <div className="flex items-center gap-1.5">
            <button
              onClick={handleCreateNewSession}
              className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-purple-600 hover:bg-purple-500 text-white shadow-sm transition-all cursor-pointer"
              title="Открыть новую независимую вкладку диалога (+)"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Новый чат</span>
            </button>

            {onClose && (
              <button
                onClick={onClose}
                className="p-1 rounded-lg hover:bg-white/10 text-zinc-400 hover:text-white transition-colors cursor-pointer"
                title="Скрыть боковую панель (все вкладки и история сохраняются)"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Полоса вкладок диалогов (Multi-chat Tabs) */}
        <div className="px-3 py-1.5 border-b border-[#2D1B4E]/60 bg-[#0E071A]/80 flex items-center gap-1.5 overflow-x-auto shrink-0 select-none scrollbar-thin">
          {sessions.map((s) => {
            const isActive = s.id === activeSession.id;
            return (
              <div
                key={s.id}
                onClick={() => setActiveSessionId(s.id)}
                className={`group flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium cursor-pointer transition-all shrink-0 border ${
                  isActive
                    ? 'bg-purple-600/40 text-white border-purple-500/80 shadow-sm'
                    : 'bg-black/30 text-zinc-400 hover:text-zinc-200 hover:bg-[#150D2E] border-transparent'
                }`}
                title={s.title}
              >
                <MessageSquare className={`w-3 h-3 ${isActive ? 'text-purple-300' : 'text-zinc-500'}`} />
                <span className="truncate max-w-[100px]">{s.title}</span>
                {s.messages.length > 0 && (
                  <span
                    className={`text-[9px] px-1 rounded-full font-mono ${
                      isActive ? 'bg-purple-800/80 text-purple-200' : 'bg-black/40 text-zinc-500'
                    }`}
                  >
                    {s.messages.length}
                  </span>
                )}
                {sessions.length > 1 && (
                  <button
                    onClick={(e) => handleCloseSession(s.id, e)}
                    className="p-0.5 rounded hover:bg-black/40 text-zinc-400 hover:text-red-300 transition-colors opacity-70 group-hover:opacity-100 ml-0.5"
                    title="Закрыть этот чат"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            );
          })}

          <button
            onClick={handleCreateNewSession}
            className="p-1 rounded-md bg-[#150D2E] hover:bg-purple-900/40 border border-purple-500/30 text-purple-300 hover:text-white shrink-0 transition-colors cursor-pointer"
            title="Добавить новый чат"
          >
            <Plus className="w-3 h-3" />
          </button>
        </div>

        {/* Компактная полоса настроек (категория + количество источников) */}
        <div className="px-4 py-2 border-b border-[#2D1B4E]/60 bg-[#0E071A]/70 flex items-center justify-between gap-2 text-[11px] text-zinc-400 shrink-0">
          <div className="flex items-center gap-1.5">
            <Sliders className="w-3 h-3 text-purple-400" />
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="bg-[#0A0515] border border-[#2D1B4E] rounded-md px-2 py-0.5 text-zinc-200 text-[11px] focus:outline-none"
            >
              <option value="all">Все типы</option>
              <option value="датасет">Датасеты</option>
              <option value="модель">Модели</option>
              <option value="репозиторий">Репозитории</option>
              <option value="статья">Статьи</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <span>Источников:</span>
            <span className="text-purple-300 font-bold font-mono">{maxSources}</span>
            <input
              type="range"
              min={1}
              max={10}
              value={maxSources}
              onChange={(e) => setMaxSources(Number(e.target.value))}
              className="w-16 accent-purple-500 h-1 bg-[#0A0515] rounded cursor-pointer"
              title="Количество источников контекста в ответе"
            />
          </div>
        </div>

        {/* Лента сообщений активной вкладки */}
        <div className="flex-1 p-3.5 overflow-y-auto space-y-3.5 text-xs">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col justify-center items-center text-center p-4">
              <div className="w-12 h-12 rounded-2xl bg-purple-950/60 border border-purple-700/50 flex items-center justify-center text-purple-400 mb-3 shadow-inner">
                <Bot className="w-6 h-6" />
              </div>
              <h4 className="text-xs font-semibold text-white mb-1">
                {activeSession.title} (Новый диалог)
              </h4>
              <p className="text-[11px] text-muted-foreground mb-4 max-w-xs leading-relaxed">
                Это отдельный независимый чат. Задайте вопрос по моделям, статьям или датасетам.
              </p>
              <div className="space-y-1.5 w-full text-left">
                <button
                  onClick={() => sendMessage('Привет! Что ты умеешь и какие данные у тебя есть?')}
                  className="w-full p-2.5 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-[11px] text-zinc-300 hover:text-white transition-all text-left flex items-start gap-2 cursor-pointer"
                >
                  <MessageSquare className="w-3.5 h-3.5 text-purple-400 mt-0.5 shrink-0" />
                  <span>💬 «Привет! Что ты умеешь и какие данные у тебя есть?»</span>
                </button>
                <button
                  onClick={() => sendMessage('Найди датасеты для анализа кибератак и безопасности')}
                  className="w-full p-2.5 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-[11px] text-zinc-300 hover:text-white transition-all text-left flex items-start gap-2 cursor-pointer"
                >
                  <ShieldAlert className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
                  <span>🛡️ «Найди датасеты для анализа кибератак»</span>
                </button>
                <button
                  onClick={() => sendMessage('Посоветуй актуальные модели для генерации изображений')}
                  className="w-full p-2.5 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-[11px] text-zinc-300 hover:text-white transition-all text-left flex items-start gap-2 cursor-pointer"
                >
                  <Palette className="w-3.5 h-3.5 text-fuchsia-400 mt-0.5 shrink-0" />
                  <span>🎨 «Посоветуй модели для генерации изображений»</span>
                </button>
              </div>
            </div>
          ) : (
            messages.map((msg, idx) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={idx}
                  className={`flex gap-2.5 ${isUser ? 'justify-end' : 'justify-start'} min-w-0 max-w-full`}
                >
                  {!isUser && (
                    <div className="w-6 h-6 rounded-full bg-purple-950 border border-purple-600 flex items-center justify-center shrink-0 text-purple-400 mt-1">
                      <Bot className="w-3 h-3" />
                    </div>
                  )}

                  <div
                    className={`max-w-[88%] min-w-0 rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed break-words [overflow-wrap:anywhere] ${
                      isUser
                        ? 'bg-purple-600 text-white shadow-md'
                        : 'bg-[#150D2E] text-zinc-200 border border-[#3B156E] shadow-sm'
                    }`}
                  >
                    {isUser ? (
                      <div className="whitespace-pre-line break-words [overflow-wrap:anywhere]">{msg.content}</div>
                    ) : (
                      <div className="min-w-0 max-w-full overflow-hidden">
                        <MarkdownRenderer content={msg.content} />
                      </div>
                    )}

                    {/* Карточки найденных сущностей */}
                    {msg.cards && msg.cards.length > 0 && (
                      <div className="mt-3 pt-2.5 border-t border-[#3B156E]/60 space-y-2 min-w-0 max-w-full">
                        <div className="text-[11px] font-semibold text-purple-300 flex items-center gap-1">
                          <Sparkles className="w-3 h-3 shrink-0" />
                          <span>{msg.cards.length === 1 ? 'Карточка материала:' : `Источники (${msg.cards.length}):`}</span>
                        </div>

                        <div className="space-y-1.5 min-w-0 max-w-full">
                          {msg.cards.map((card, cIdx) => {
                            const badge = getCategoryBadge(card.category);
                            return (
                              <div
                                key={cIdx}
                                className="p-2.5 rounded-lg bg-[#0A0515] border border-[#4C1D95]/60 hover:border-purple-400 transition-colors min-w-0 max-w-full overflow-hidden"
                              >
                                <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                                  <span
                                    className={`text-[9px] font-bold px-1.5 py-0.5 rounded border shrink-0 ${badge.className}`}
                                  >
                                    {badge.label}
                                  </span>
                                  {card.metrics?.stars ? (
                                    <span className="text-[9px] text-amber-300 flex items-center gap-0.5 shrink-0">
                                      <Star className="w-2.5 h-2.5 fill-amber-400" />
                                      {card.metrics.stars.toLocaleString()}
                                    </span>
                                  ) : null}
                                  {card.metrics?.downloads ? (
                                    <span className="text-[9px] text-sky-300 flex items-center gap-0.5 shrink-0">
                                      <Download className="w-2.5 h-2.5" />
                                      {card.metrics.downloads.toLocaleString()}
                                    </span>
                                  ) : null}
                                  {card.metrics?.likes ? (
                                    <span className="text-[9px] text-rose-300 flex items-center gap-0.5 shrink-0">
                                      <Heart className="w-2.5 h-2.5 fill-rose-400" />
                                      {card.metrics.likes.toLocaleString()}
                                    </span>
                                  ) : null}
                                  {card.metrics?.rating ? (
                                    <span className="text-[9px] text-amber-300 font-mono flex items-center gap-0.5 shrink-0">
                                      ★ Elo {card.metrics.rating}
                                    </span>
                                  ) : null}
                                </div>
                                <a
                                  href={card.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-[11px] font-semibold text-white hover:text-purple-300 flex items-center gap-1 break-words [overflow-wrap:anywhere]"
                                >
                                  <span className="break-words">{card.title}</span>
                                  <ExternalLink className="w-2.5 h-2.5 opacity-70 shrink-0" />
                                </a>
                                {card.summary && (
                                  <p className="text-[10px] text-zinc-300 mt-1 leading-relaxed whitespace-pre-line break-words [overflow-wrap:anywhere]">
                                    {card.summary}
                                  </p>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>

                  {isUser && (
                    <div className="w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center shrink-0 text-zinc-300 mt-1">
                      <User className="w-3 h-3" />
                    </div>
                  )}
                </div>
              );
            })
          )}

          {isLoading && (
            <div className="flex gap-2 items-center text-xs text-purple-300 bg-[#150D2E] p-2.5 rounded-xl border border-[#3B156E]">
              <RefreshCw className="w-3 h-3 animate-spin" />
              <span>Ассистент анализирует контекст и формирует подробный ответ...</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Поле ввода в док-панели */}
        <div className="p-3 border-t border-[#2D1B4E] bg-[#120B24] shrink-0">
          <div className="relative flex items-center">
            <textarea
              rows={2}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Задайте вопрос ассистенту (Enter)..."
              className="w-full pl-3 pr-10 py-2 text-xs rounded-xl bg-[#0A0515] border border-[#2D1B4E] focus:border-purple-500 focus:outline-none text-white placeholder-zinc-500 resize-none"
            />
            <button
              onClick={() => sendMessage(inputText)}
              disabled={!inputText.trim() || isLoading}
              className="absolute right-2 p-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-40 transition-colors cursor-pointer"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  // =========================================================================
  // РЕЖИМ 2: ПОЛНОРАЗМЕРНЫЙ РАЗДЕЛ (FULL VIEW)
  // =========================================================================
  return (
    <div className="space-y-6">
      {/* Шапка раздела */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <Bot className="w-7 h-7 text-purple-400" />
              AI Ассистент & RAG
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-500/10 text-purple-300 border border-purple-500/30 flex items-center gap-1">
              <Sparkles className="w-3 h-3" />
              Мультидиалог и память
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1 max-w-4xl">
            Интеллектуальный диалоговый консультант по каталогу AI-ресурсов. Поддерживает несколько параллельных независимых диалогов во вкладках, сохраняет полный контекст общения и формирует обоснованные ответы со ссылками на первоисточники.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {reindexMsg && (
            <span className="text-xs px-2.5 py-1 rounded bg-accent/30 text-accent-foreground border border-border">
              {reindexMsg}
            </span>
          )}
          <button
            onClick={handleReindex}
            disabled={isReindexing}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-purple-950/60 hover:bg-purple-900/60 text-purple-300 border border-purple-700/50 transition-all shadow-sm disabled:opacity-50 cursor-pointer"
            title="Принудительно перестроить векторный индекс эмбеддингов"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isReindexing ? 'animate-spin' : ''}`} />
            Переиндексировать базу
          </button>
        </div>
      </div>

      {/* Панель параметров RAG и статистика */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Статистика вектора */}
        <div className="p-4 rounded-xl bg-[#12121A] border border-[#2D1B4E] flex items-center gap-3">
          <Database className="w-8 h-8 text-emerald-400 shrink-0" />
          <div className="text-xs space-y-0.5">
            <div className="font-semibold text-white">Векторный индекс каталога</div>
            {catalogStats ? (
              <div className="text-muted-foreground">
                <span className="text-emerald-400 font-bold">{catalogStats.всего || 0}</span> карточек
                ({catalogStats.датасеты || 0} датасетов, {catalogStats.модели || 0} моделей,{' '}
                {catalogStats.репозитории || 0} репо, {catalogStats.статьи || 0} статей)
              </div>
            ) : (
              <div className="text-zinc-500">Загрузка телеметрии индекса...</div>
            )}
          </div>
        </div>

        {/* Фильтр категории */}
        <div className="p-4 rounded-xl bg-[#12121A] border border-[#2D1B4E] flex flex-col justify-center">
          <label className="text-xs font-semibold text-muted-foreground mb-1.5 flex items-center gap-1.5">
            <Sliders className="w-3.5 h-3.5 text-purple-400" />
            Искать в категориях:
          </label>
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="px-3 py-1.5 text-xs rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none cursor-pointer"
          >
            <option value="all">Все материалы каталога</option>
            <option value="датасет">Только датасеты</option>
            <option value="модель">Только модели</option>
            <option value="репозиторий">Только репозитории</option>
            <option value="статья">Только статьи</option>
          </select>
        </div>

        {/* Количество источников */}
        <div className="p-4 rounded-xl bg-[#12121A] border border-[#2D1B4E] flex flex-col justify-center">
          <div className="flex items-center justify-between text-xs font-semibold text-muted-foreground mb-1.5">
            <span>Количество источников в ответе:</span>
            <span className="text-purple-400 font-bold">{maxSources}</span>
          </div>
          <input
            type="range"
            min={1}
            max={10}
            value={maxSources}
            onChange={(e) => setMaxSources(Number(e.target.value))}
            className="w-full accent-purple-500 h-1.5 bg-[#0A0A0F] rounded-lg cursor-pointer"
          />
        </div>
      </div>

      {/* Окно диалога с вкладками */}
      <div className="rounded-2xl bg-[#0E071A] border border-[#2D1B4E] flex flex-col h-[700px] shadow-lg overflow-hidden">
        {/* Шапка чата */}
        <div className="px-5 py-3 border-b border-[#2D1B4E] bg-[#120B24] flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold text-white">
            <Bot className="w-4 h-4 text-purple-400" />
            <span>AI Radar Исследователь</span>
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCreateNewSession}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-purple-600 hover:bg-purple-500 text-white shadow-md shadow-purple-600/30 transition-all cursor-pointer"
              title="Создать новую независимую вкладку диалога"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Новый чат</span>
            </button>

            {messages.length > 0 && (
              <button
                onClick={() => handleCloseSession(activeSession.id)}
                className="text-xs text-muted-foreground hover:text-red-400 flex items-center gap-1.5 transition-colors cursor-pointer px-2 py-1"
                title="Очистить или закрыть текущую вкладку"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Очистить диалог</span>
              </button>
            )}
          </div>
        </div>

        {/* Полоса вкладок диалогов (Full view) */}
        <div className="px-4 py-2 border-b border-[#2D1B4E]/60 bg-[#0A0515]/80 flex items-center gap-2 overflow-x-auto shrink-0 select-none scrollbar-thin">
          {sessions.map((s) => {
            const isActive = s.id === activeSession.id;
            return (
              <div
                key={s.id}
                onClick={() => setActiveSessionId(s.id)}
                className={`group flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium cursor-pointer transition-all shrink-0 border ${
                  isActive
                    ? 'bg-purple-600 text-white border-purple-400 shadow-md shadow-purple-600/30 font-semibold'
                    : 'bg-[#150D2E]/60 text-zinc-400 hover:text-zinc-200 hover:bg-[#1E1242] border-[#2D1B4E]'
                }`}
                title={s.title}
              >
                <MessageSquare className={`w-3.5 h-3.5 ${isActive ? 'text-white' : 'text-purple-400'}`} />
                <span className="truncate max-w-[130px]">{s.title}</span>
                {s.messages.length > 0 && (
                  <span
                    className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
                      isActive ? 'bg-black/30 text-white' : 'bg-black/40 text-zinc-400'
                    }`}
                  >
                    {s.messages.length}
                  </span>
                )}
                {sessions.length > 1 && (
                  <button
                    onClick={(e) => handleCloseSession(s.id, e)}
                    className="p-0.5 rounded hover:bg-black/40 text-zinc-300 hover:text-red-300 transition-colors opacity-70 group-hover:opacity-100 ml-1"
                    title="Закрыть эту вкладку"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            );
          })}

          <button
            onClick={handleCreateNewSession}
            className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-[#150D2E] hover:bg-purple-900/40 border border-purple-500/30 text-purple-300 hover:text-white text-xs font-semibold shrink-0 transition-all cursor-pointer shadow-sm"
            title="Открыть новую независимую вкладку диалога"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Новый чат</span>
          </button>
        </div>

        {/* Сообщения активной вкладки */}
        <div className="flex-1 p-5 overflow-y-auto space-y-5">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col justify-center items-center text-center p-6">
              <div className="w-14 h-14 rounded-2xl bg-purple-950/60 border border-purple-700/50 flex items-center justify-center text-purple-400 mb-4 shadow-inner">
                <Bot className="w-8 h-8" />
              </div>
              <h3 className="text-base font-semibold text-white mb-1">
                {activeSession.title} — новый независимый диалог
              </h3>
              <p className="text-xs text-muted-foreground max-w-md mb-6 leading-relaxed">
                Задайте вопрос по моделям LMSYS Arena, трендам Hugging Face, датасетам Kaggle или статьям ArXiv/PwC.
              </p>

              {/* Быстрые примеры запросов */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 w-full max-w-2xl text-left">
                <button
                  onClick={() => sendMessage('Привет! Что ты умеешь и какие данные у тебя есть?')}
                  className="p-3 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-xs text-zinc-300 hover:text-white transition-all flex items-start gap-2.5 text-left group cursor-pointer"
                >
                  <MessageSquare className="w-4 h-4 text-purple-400 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <span>💬 «Привет! Что ты умеешь и какие данные у тебя есть?»</span>
                </button>

                <button
                  onClick={() =>
                    sendMessage('Найди датасеты для выявления кибератак и безопасности')
                  }
                  className="p-3 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-xs text-zinc-300 hover:text-white transition-all flex items-start gap-2.5 text-left group cursor-pointer"
                >
                  <ShieldAlert className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <span>🛡️ «Найди датасеты для выявления кибератак и безопасности»</span>
                </button>

                <button
                  onClick={() =>
                    sendMessage('Посоветуй актуальные модели для генерации изображений')
                  }
                  className="p-3 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-xs text-zinc-300 hover:text-white transition-all flex items-start gap-2.5 text-left group cursor-pointer"
                >
                  <Palette className="w-4 h-4 text-fuchsia-400 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <span>🎨 «Посоветуй актуальные модели для генерации изображений»</span>
                </button>

                <button
                  onClick={() =>
                    sendMessage('Сравни топ-модели в LMSYS Arena для русского языка')
                  }
                  className="p-3 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-xs text-zinc-300 hover:text-white transition-all flex items-start gap-2.5 text-left group cursor-pointer"
                >
                  <Sparkles className="w-4 h-4 text-amber-400 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <span>⚡ «Сравни топ-модели в LMSYS Arena для русского языка»</span>
                </button>
              </div>
            </div>
          ) : (
            messages.map((msg, idx) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={idx}
                  className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'} min-w-0 max-w-full`}
                >
                  {!isUser && (
                    <div className="w-8 h-8 rounded-full bg-purple-950 border border-purple-600 flex items-center justify-center shrink-0 text-purple-400 mt-1 shadow-sm">
                      <Bot className="w-4 h-4" />
                    </div>
                  )}

                  <div
                    className={`max-w-[85%] min-w-0 rounded-2xl p-4 text-xs leading-relaxed break-words [overflow-wrap:anywhere] ${
                      isUser
                        ? 'bg-purple-600 text-white shadow-md'
                        : 'bg-[#150D2E] text-zinc-200 border border-[#3B156E] shadow-sm'
                    }`}
                  >
                    {isUser ? (
                      <div className="whitespace-pre-line text-sm break-words [overflow-wrap:anywhere]">{msg.content}</div>
                    ) : (
                      <div className="min-w-0 max-w-full overflow-hidden">
                        <MarkdownRenderer content={msg.content} />
                      </div>
                    )}

                    {/* Карточки найденных сущностей */}
                    {msg.cards && msg.cards.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-[#3B156E]/60 space-y-2 min-w-0 max-w-full">
                        <div className="text-xs font-semibold text-purple-300 flex items-center gap-1.5">
                          <Sparkles className="w-3.5 h-3.5 shrink-0" />
                          <span>{msg.cards.length === 1 ? 'Карточка материала:' : `Релевантные первоисточники (${msg.cards.length}):`}</span>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2 min-w-0 max-w-full">
                          {msg.cards.map((card, cIdx) => {
                            const badge = getCategoryBadge(card.category);
                            return (
                              <div
                                key={cIdx}
                                className="p-2.5 rounded-xl bg-[#0A0515] border border-[#4C1D95]/60 hover:border-purple-400 transition-colors min-w-0 max-w-full overflow-hidden"
                              >
                                <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                  <span
                                    className={`text-[9px] font-bold px-1.5 py-0.5 rounded border shrink-0 ${badge.className}`}
                                  >
                                    {badge.label}
                                  </span>
                                  {card.metrics?.stars ? (
                                    <span className="text-[10px] text-amber-300 flex items-center gap-0.5 shrink-0">
                                      <Star className="w-2.5 h-2.5 fill-amber-400" />
                                      {card.metrics.stars.toLocaleString()}
                                    </span>
                                  ) : null}
                                  {card.metrics?.downloads ? (
                                    <span className="text-[10px] text-sky-300 flex items-center gap-0.5 shrink-0">
                                      <Download className="w-2.5 h-2.5" />
                                      {card.metrics.downloads.toLocaleString()}
                                    </span>
                                  ) : null}
                                  {card.metrics?.likes ? (
                                    <span className="text-[10px] text-rose-300 flex items-center gap-0.5 shrink-0">
                                      <Heart className="w-2.5 h-2.5 fill-rose-400" />
                                      {card.metrics.likes.toLocaleString()}
                                    </span>
                                  ) : null}
                                  {card.metrics?.rating ? (
                                    <span className="text-[10px] text-amber-300 font-mono flex items-center gap-0.5 shrink-0">
                                      ★ Elo {card.metrics.rating}
                                    </span>
                                  ) : null}
                                </div>
                                <a
                                  href={card.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-xs font-semibold text-white hover:text-purple-300 flex items-center gap-1 break-words [overflow-wrap:anywhere]"
                                >
                                  <span className="break-words">{card.title}</span>
                                  <ExternalLink className="w-3 h-3 opacity-70 shrink-0" />
                                </a>
                                {card.summary && (
                                  <p className="text-[11px] text-zinc-300 mt-1.5 leading-relaxed whitespace-pre-line break-words [overflow-wrap:anywhere]">
                                    {card.summary}
                                  </p>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>

                  {isUser && (
                    <div className="w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center shrink-0 text-zinc-300 mt-1 shadow-sm">
                      <User className="w-4 h-4" />
                    </div>
                  )}
                </div>
              );
            })
          )}

          {isLoading && (
            <div className="flex gap-2 items-center text-xs text-purple-300 bg-[#150D2E] p-3 rounded-xl border border-[#3B156E] w-fit">
              <RefreshCw className="w-4 h-4 animate-spin text-purple-400" />
              <span>Ассистент анализирует контекст и формулирует подробный ответ...</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Поле ввода сообщения */}
        <div className="p-4 border-t border-[#2D1B4E] bg-[#120B24]">
          {activeSession.activeCard && (
            <div className="flex items-center justify-between px-3 py-1.5 mb-2.5 rounded-xl bg-[#1B0F33] border border-purple-500/30 text-xs text-purple-200 shadow-sm animate-in fade-in duration-200">
              <div className="flex items-center gap-1.5 min-w-0">
                <Sparkles className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                <span className="text-zinc-400 shrink-0">Контекст карточки:</span>
                <span className="font-medium text-white truncate">{activeSession.activeCard.title}</span>
              </div>
              <button
                onClick={() => {
                  setSessions((prev) =>
                    prev.map((s) => (s.id === activeSession.id ? { ...s, activeCard: undefined } : s))
                  );
                }}
                className="text-zinc-400 hover:text-white ml-2 text-[11px] px-1.5 py-0.5 rounded hover:bg-purple-900/40 shrink-0 transition-colors cursor-pointer"
                title="Открепить контекст этой карточки"
              >
                ✕ Открепить
              </button>
            </div>
          )}
          <div className="relative flex items-center">
            <textarea
              rows={3}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Задайте вопрос ассистенту по материалам каталога (Enter для отправки)..."
              className="w-full pl-4 pr-12 py-3 text-xs rounded-xl bg-[#0A0515] border border-[#2D1B4E] focus:border-purple-500 focus:outline-none text-white placeholder-zinc-500 resize-none leading-relaxed"
            />
            <button
              onClick={() => sendMessage(inputText)}
              disabled={!inputText.trim() || isLoading}
              className="absolute right-3 p-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-40 transition-colors shadow-md cursor-pointer"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
