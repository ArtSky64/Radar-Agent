import React, { useState, useEffect, useRef } from 'react';
import {
  Bot,
  User,
  Send,
  Sparkles,
  RefreshCw,
  Database,
  Search,
  ExternalLink,
  Trash2,
  Sliders,
  Heart,
  Star,
  Download,
  ShieldAlert,
  Palette,
  HeartPulse,
  MessageSquare,
} from 'lucide-react';
import type { RAGCard } from '../../types/domain';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  cards?: RAGCard[];
  action?: string;
}

interface CatalogStats {
  всего?: number;
  датасеты?: number;
  модели?: number;
  репозитории?: number;
  статьи?: number;
}

export const RAGSection: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [topK, setTopK] = useState<number>(5);
  const [catalogStats, setCatalogStats] = useState<CatalogStats | null>(null);
  const [isReindexing, setIsReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  // Загружаем статистику каталога при монтировании
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
      // Игнорируем сетевые ошибки префлайта
    }
  };

  const handleReindex = async () => {
    setIsReindexing(true);
    setReindexMsg('Переиндексация базы данных...');
    try {
      const res = await fetch('/rag/reindex', { method: 'POST' });
      const json = await res.json();
      if (json.status === 'success') {
        setReindexMsg(`База переиндексирована (${json.indexed_count || 0} сущностей)`);
        await fetchStats();
      } else {
        setReindexMsg(`Ошибка: ${json.message || 'Сбой индексации'}`);
      }
    } catch {
      setReindexMsg('Ошибка связи с сервером');
    } finally {
      setIsReindexing(false);
      setTimeout(() => setReindexMsg(null), 4000);
    }
  };

  const sendMessage = async (text: string) => {
    if (!text.trim() || isLoading) return;

    const userMsg: Message = { role: 'user', content: text.trim() };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInputText('');
    setIsLoading(true);

    try {
      const res = await fetch('/rag/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: updatedMessages.map((m) => ({ role: m.role, content: m.content })),
          category: selectedCategory,
          top_k: topK,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP error ${res.status}`);
      }

      const json = await res.json();
      if (json.status === 'success' && json.data) {
        const assistantMsg: Message = {
          role: 'assistant',
          content: json.data.content || 'Ответ сформирован.',
          cards: json.data.cards || [],
          action: json.data.action,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `Ошибка формирования ответа: ${json.message || 'Неизвестная ошибка'}`,
          },
        ]);
      }
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Не удалось связаться с RAG-сервисом (${err.message || 'сетевая ошибка'}). Убедитесь, что сервер FastAPI запущен.`,
        },
      ]);
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

  const clearChat = () => {
    setMessages([]);
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

  return (
    <div className="space-y-6">
      {/* Шапка раздела */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <Bot className="w-7 h-7 text-purple-400" />
              ИИ-Рекомендации (RAG)
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-500/10 text-purple-300 border border-purple-500/30 flex items-center gap-1">
              <Sparkles className="w-3 h-3" />
              Семантический поиск
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1 max-w-4xl">
            Интеллектуальный диалоговый консультант по собранной базе данных. Ассистент уточняет требования, выполняет векторный поиск по эмбеддингам и формулирует обоснованный ответ со ссылками на первоисточники.
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
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-purple-950/60 hover:bg-purple-900/60 text-purple-300 border border-purple-700/50 transition-all shadow-sm disabled:opacity-50"
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
            className="px-3 py-1.5 text-xs rounded-lg bg-[#0A0A0F] border border-[#2D1B4E] text-white focus:border-purple-500 focus:outline-none"
          >
            <option value="all">Все материалы каталога</option>
            <option value="датасет">Только датасеты</option>
            <option value="модель">Только модели</option>
            <option value="репозиторий">Только репозитории</option>
            <option value="статья">Только статьи</option>
          </select>
        </div>

        {/* Слайдер Top-K */}
        <div className="p-4 rounded-xl bg-[#12121A] border border-[#2D1B4E] flex flex-col justify-center">
          <div className="flex items-center justify-between text-xs font-semibold text-muted-foreground mb-1.5">
            <span>Рекомендовать источников (Top-K):</span>
            <span className="text-purple-400 font-bold">{topK}</span>
          </div>
          <input
            type="range"
            min={1}
            max={10}
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            className="w-full accent-purple-500 h-1.5 bg-[#0A0A0F] rounded-lg cursor-pointer"
          />
        </div>
      </div>

      {/* Окно диалога */}
      <div className="rounded-2xl bg-[#0E071A] border border-[#2D1B4E] flex flex-col h-[650px] shadow-lg overflow-hidden">
        {/* Шапка чата */}
        <div className="px-5 py-3 border-b border-[#2D1B4E] bg-[#120B24] flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold text-white">
            <Bot className="w-4 h-4 text-purple-400" />
            <span>AI Radar Advisor</span>
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          </div>

          {messages.length > 0 && (
            <button
              onClick={clearChat}
              className="text-xs text-muted-foreground hover:text-red-400 flex items-center gap-1.5 transition-colors cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Очистить историю
            </button>
          )}
        </div>

        {/* Сообщения */}
        <div className="flex-1 p-5 overflow-y-auto space-y-5">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col justify-center items-center text-center p-6">
              <div className="w-14 h-14 rounded-2xl bg-purple-950/60 border border-purple-700/50 flex items-center justify-center text-purple-400 mb-4 shadow-inner">
                <Bot className="w-8 h-8" />
              </div>
              <h3 className="text-base font-semibold text-white mb-1">
                Привет! Чем помочь в исследованиях AI?
              </h3>
              <p className="text-xs text-muted-foreground max-w-md mb-6 leading-relaxed">
                Задайте вопрос по моделям LMSYS Arena, трендам Hugging Face, датасетам Kaggle или статьям ArXiv/PwC.
              </p>

              {/* Быстрые примеры запросов */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 w-full max-w-2xl text-left">
                <button
                  onClick={() => sendMessage('Привет! Что ты умеешь и какие данные у тебя есть?')}
                  className="p-3 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-xs text-zinc-300 hover:text-white transition-all flex items-start gap-2.5 text-left group"
                >
                  <MessageSquare className="w-4 h-4 text-purple-400 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <span>💬 «Привет! Что ты умеешь и какие данные у тебя есть?»</span>
                </button>

                <button
                  onClick={() =>
                    sendMessage('Найди датасеты для выявления кибератак и безопасности')
                  }
                  className="p-3 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-xs text-zinc-300 hover:text-white transition-all flex items-start gap-2.5 text-left group"
                >
                  <ShieldAlert className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <span>🛡️ «Найди датасеты для выявления кибератак и безопасности»</span>
                </button>

                <button
                  onClick={() =>
                    sendMessage('Посоветуй актуальные модели для генерации изображений')
                  }
                  className="p-3 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-xs text-zinc-300 hover:text-white transition-all flex items-start gap-2.5 text-left group"
                >
                  <Palette className="w-4 h-4 text-fuchsia-400 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <span>🎨 «Посоветуй актуальные модели для генерации изображений»</span>
                </button>

                <button
                  onClick={() => sendMessage('Мне нужны материалы для медицины и здравоохранения')}
                  className="p-3 rounded-xl bg-[#150D2E] hover:bg-[#1E1242] border border-[#3B156E] text-xs text-zinc-300 hover:text-white transition-all flex items-start gap-2.5 text-left group"
                >
                  <HeartPulse className="w-4 h-4 text-sky-400 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <span>🏥 «Мне нужны материалы для медицины и здравоохранения»</span>
                </button>
              </div>
            </div>
          ) : (
            messages.map((msg, idx) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={idx}
                  className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}
                >
                  {!isUser && (
                    <div className="w-8 h-8 rounded-full bg-purple-950 border border-purple-600 flex items-center justify-center shrink-0 text-purple-400 mt-1">
                      <Bot className="w-4 h-4" />
                    </div>
                  )}

                  <div
                    className={`max-w-2xl rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                      isUser
                        ? 'bg-purple-600 text-white shadow-md'
                        : 'bg-[#150D2E] text-zinc-200 border border-[#3B156E] shadow-sm'
                    }`}
                  >
                    <div className="whitespace-pre-line">{msg.content}</div>

                    {/* Карточки найденных сущностей */}
                    {msg.cards && msg.cards.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-[#3B156E]/60 space-y-3">
                        <div className="text-xs font-semibold text-purple-300 flex items-center gap-1.5">
                          <Sparkles className="w-3.5 h-3.5" />
                          Рекомендованные материалы из базы данных ({msg.cards.length}):
                        </div>

                        <div className="space-y-2.5">
                          {msg.cards.map((card, cIdx) => {
                            const badge = getCategoryBadge(card.category);
                            return (
                              <div
                                key={cIdx}
                                className="p-3 rounded-xl bg-[#0A0515] border border-[#4C1D95]/60 hover:border-purple-400 transition-colors"
                              >
                                <div className="flex flex-wrap items-center gap-2 mb-1.5">
                                  <span
                                    className={`text-[10px] font-bold tracking-wider px-2 py-0.5 rounded border ${badge.className}`}
                                  >
                                    {badge.label}
                                  </span>

                                  {card.metrics?.stars && (
                                    <span className="text-[10px] font-bold text-amber-300 flex items-center gap-1">
                                      <Star className="w-3 h-3 fill-amber-400" />
                                      {card.metrics.stars.toLocaleString()}
                                    </span>
                                  )}

                                  {card.metrics?.downloads && (
                                    <span className="text-[10px] font-bold text-sky-300 flex items-center gap-1">
                                      <Download className="w-3 h-3" />
                                      {card.metrics.downloads.toLocaleString()}
                                    </span>
                                  )}

                                  {card.metrics?.likes && (
                                    <span className="text-[10px] font-bold text-pink-300 flex items-center gap-1">
                                      <Heart className="w-3 h-3 fill-pink-400" />
                                      {card.metrics.likes.toLocaleString()}
                                    </span>
                                  )}
                                </div>

                                <h4 className="text-xs font-semibold text-white hover:text-purple-300">
                                  <a
                                    href={card.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="flex items-center gap-1.5 hover:underline"
                                  >
                                    {card.title}
                                    <ExternalLink className="w-3 h-3 opacity-60" />
                                  </a>
                                </h4>

                                {card.summary && (
                                  <p className="text-[11px] text-zinc-400 mt-1 line-clamp-2">
                                    {card.summary}
                                  </p>
                                )}

                                <div className="mt-2 text-[10px]">
                                  <a
                                    href={card.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-purple-400 hover:text-purple-300 underline"
                                  >
                                    Открыть первоисточник →
                                  </a>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>

                  {isUser && (
                    <div className="w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center shrink-0 text-zinc-300 mt-1">
                      <User className="w-4 h-4" />
                    </div>
                  )}
                </div>
              );
            })
          )}

          {isLoading && (
            <div className="flex gap-3 justify-start">
              <div className="w-8 h-8 rounded-full bg-purple-950 border border-purple-600 flex items-center justify-center shrink-0 text-purple-400 animate-pulse">
                <Bot className="w-4 h-4" />
              </div>
              <div className="bg-[#150D2E] rounded-2xl px-4 py-3 border border-[#3B156E] text-xs text-purple-300 flex items-center gap-2">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Ассистент анализирует контекст диалога и сверяется с векторным индексом...
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Поле ввода */}
        <div className="p-4 border-t border-[#2D1B4E] bg-[#120B24]">
          <div className="relative flex items-center">
            <textarea
              rows={2}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Напишите ваш запрос, например: «Найди датасеты для анализа кибератак»..."
              className="w-full pl-4 pr-12 py-2.5 text-xs rounded-xl bg-[#0A0515] border border-[#2D1B4E] focus:border-purple-500 focus:outline-none text-white placeholder-zinc-500 resize-none"
            />
            <button
              onClick={() => sendMessage(inputText)}
              disabled={!inputText.trim() || isLoading}
              className="absolute right-3 p-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-40 disabled:hover:bg-purple-600 transition-colors cursor-pointer"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
          <div className="mt-1.5 flex justify-between items-center text-[10px] text-muted-foreground px-1">
            <span>Enter для отправки, Shift+Enter для новой строки</span>
            <span>Семантический порог сходства: 0.59 cos</span>
          </div>
        </div>
      </div>
    </div>
  );
};
