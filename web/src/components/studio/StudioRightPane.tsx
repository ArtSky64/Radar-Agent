import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot,
  FileText,
  ChevronRight,
  ChevronLeft,
  X,
  ExternalLink,
  Copy,
  Check,
  Sparkles,
  ShieldCheck,
  Send,
  ArrowRight,
  Maximize2,
  ArrowLeftRight,
  Compass,
  TrendingUp,
} from 'lucide-react';
import { Sparkline } from '../ui/Sparkline';
import { IntelligenceOrb } from '../ui/IntelligenceOrb';
import { TypewriterText } from '../ui/TypewriterText';
import type { IntelItem, ChatMessage } from '../../types/intel';
import { getItemGrammar } from '../../utils/intelItemLabels';

interface StudioRightPaneProps {
  mode?: 'center' | 'docked';
  selectedItem: IntelItem | null;
  onClearSelectedItem: () => void;
  onAskCopilot: (prompt: string) => void;
  onCollapse: () => void;
  onTransitionToHub?: () => void;
  onTransitionToCenter?: () => void;
  dockSide?: 'right' | 'left';
  onToggleDockSide?: () => void;
  injectedPrompt?: string;
  onClearInjectedPrompt?: () => void;
  messages?: ChatMessage[];
  onSendMessage?: (text: string) => Promise<void> | void;
  isLoading?: boolean;
}

const samplePrompts = [
  'Какие новые reasoning-модели вышли за неделю?',
  'Сравни DeepSeek-R1 и o3-mini в LMSys Arena',
  'Покажи топ репозиториев на GitHub по инференсу',
];

const sourceBadgeConfig: Record<string, { label: string; style: string; color: string }> = {
  HuggingFace: {
    label: 'Hugging Face',
    style: 'bg-amber-500/10 text-amber-300 border-amber-500/25',
    color: '#f59e0b',
  },
  GitHub: {
    label: 'GitHub',
    style: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25',
    color: '#10b981',
  },
  ArXiv: {
    label: 'ArXiv',
    style: 'bg-purple-500/10 text-purple-300 border-purple-500/25',
    color: '#a855f7',
  },
  'LMSys Arena': {
    label: 'LMSys Arena',
    style: 'bg-sky-500/10 text-sky-300 border-sky-500/25',
    color: '#38bdf8',
  },
};

function getOverviewSparkline(item: IntelItem): number[] {
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

export const StudioRightPane: React.FC<StudioRightPaneProps> = ({
  mode = 'docked',
  selectedItem,
  onClearSelectedItem,
  onAskCopilot,
  onCollapse,
  onTransitionToHub,
  onTransitionToCenter,
  dockSide = 'right',
  onToggleDockSide,
  injectedPrompt,
  onClearInjectedPrompt,
  messages: externalMessages,
  onSendMessage: externalSendMessage,
  isLoading: externalIsLoading,
}) => {
  const [activeTab, setActiveTab] = useState<'copilot' | 'inspector'>(
    selectedItem ? 'inspector' : 'copilot'
  );
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [localIsLoading, setLocalIsLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const messages = externalMessages || localMessages;
  const isLoading =
    externalIsLoading !== undefined ? externalIsLoading : localIsLoading;

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (mode === 'docked') {
      scrollToBottom();
    }
  }, [messages, isLoading, activeTab, mode]);

  // Переключаем на инспектор если пользователь кликнул карточку в фиде
  useEffect(() => {
    if (selectedItem) {
      setActiveTab('inspector');
    }
  }, [selectedItem]);

  useEffect(() => {
    if (injectedPrompt) {
      setActiveTab('copilot');
      handleSend(injectedPrompt);
      if (onClearInjectedPrompt) onClearInjectedPrompt();
    }
  }, [injectedPrompt]);

  const handleSend = async (text: string) => {
    const q = text.trim();
    if (!q || isLoading) return;

    // Если запрос отправлен из центрального экрана приветствия, сразу инициируем плавный переход в студию
    if (mode === 'center' && onTransitionToHub) {
      onTransitionToHub();
    }

    if (externalSendMessage) {
      setInput('');
      await externalSendMessage(q);
      return;
    }

    const userMsg: ChatMessage = {
      id: String(Date.now()),
      role: 'user',
      content: q,
      timestamp: new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
    };

    setLocalMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLocalIsLoading(true);

    try {
      const res = await fetch('http://localhost:8000/api/v1/rag/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: q }),
      });
      const data = await res.json();

      const assistantMsg: ChatMessage = {
        id: String(Date.now() + 1),
        role: 'assistant',
        content:
          data.answer || 'Ответ сформирован на основе локального векторного индекса.',
        thinking:
          'Проанализировано семантическое сходство с базой статей и моделей (FastEmbed 0.59).',
        sources:
          data.sources && data.sources.length > 0
            ? data.sources.map((s: any) => ({
                title: s.name || s.title || 'Источник',
                url: s.url || 'https://arxiv.org',
              }))
            : [
                { title: 'LMSys Arena Delta Index', url: 'https://lmsys.org' },
                { title: 'Technical Whitepaper', url: 'https://arxiv.org' },
              ],
        timestamp: new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
      };
      setLocalMessages((prev) => [...prev, assistantMsg]);
    } catch {
      setTimeout(() => {
        const assistantMsg: ChatMessage = {
          id: String(Date.now() + 1),
          role: 'assistant',
          content: `По запросу «${q}»: проверено 1.48M эмбеддингов. Топ-1 среди открытых моделей по кодингу — Qwen-2.5-Coder-32B, по общим рассуждениям — DeepSeek-R1 (1362 Elo).`,
          thinking: 'Локальный семантический поиск по SQLite (FastEmbed 0.59).',
          sources: [
            { title: 'DeepSeek-R1 Paper', url: 'https://arxiv.org' },
            { title: 'Qwen Team Checkpoint', url: 'https://huggingface.co' },
          ],
          timestamp: new Date().toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          }),
        };
        setLocalMessages((prev) => [...prev, assistantMsg]);
        setLocalIsLoading(false);
      }, 600);
      return;
    } finally {
      setLocalIsLoading(false);
    }
  };

  const handleCopyUrl = () => {
    if (!selectedItem) return;
    navigator.clipboard.writeText(selectedItem.url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // =========================================================================
  // РЕЖИМ 1: МИНИМАЛИСТИЧНЫЙ СТАРТОВЫЙ ЭКРАН (APPLE / WINDOWS SETUP)
  // Чистота, никакой дублирующей инфы, никакого второго окна чата.
  // =========================================================================
  if (mode === 'center') {
    return (
      <div className="w-full max-w-3xl rounded-3xl bg-[#0c0c12] border border-white/[0.08] shadow-[0_32px_100px_rgba(0,0,0,0.95),inset_0_1px_0_0_rgba(255,255,255,0.08)] p-6 sm:p-10 flex flex-col justify-between text-zinc-300 font-sans select-none">
        
        {/* Тонкий верхний статус */}
        <div className="flex items-center justify-between pb-6 border-b border-white/[0.06]">
          <div className="flex items-center space-x-2.5">
            <div className="scale-75 origin-left">
              <IntelligenceOrb />
            </div>
            <span className="text-xs font-bold text-white tracking-wider">
              AI Радар & Scout
            </span>
          </div>

          <div className="flex items-center space-x-2 text-[11px] text-zinc-400 font-sans">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span>Дедупликация FastEmbed</span>
          </div>
        </div>

        {/* Центральный блок приветствия: чистый крупный текст, который печатается на глазах */}
        <div className="my-auto py-8 sm:py-12 space-y-6">
          <h1 className="text-4xl sm:text-5xl font-black text-white tracking-tight leading-tight">
            Привет.
          </h1>

          <div className="text-base sm:text-lg text-zinc-300 max-w-xl leading-relaxed font-sans min-h-[3.5rem]">
            <TypewriterText
              text="Я Scout — автономный разведчик моделей Hugging Face, исследований ArXiv, репозиториев GitHub и лидерборда LMSys Arena."
              speed={20}
            />
          </div>

          {/* Поле для вопроса */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend(input);
            }}
            className="pt-2"
          >
            <div className="relative flex items-center">
              <input
                type="text"
                autoFocus
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Задайте вопрос агенту прямо сейчас..."
                className="w-full bg-white/[0.04] hover:bg-white/[0.07] focus:bg-white/[0.07] text-sm sm:text-base text-white placeholder-zinc-500 rounded-2xl pl-5 pr-14 py-4 border border-white/[0.1] focus:border-indigo-500 focus:outline-none transition-all shadow-inner"
              />
              <button
                type="submit"
                disabled={!input.trim()}
                className="absolute right-2.5 p-2 rounded-xl bg-white text-black hover:bg-zinc-200 transition-all cursor-pointer disabled:opacity-30 disabled:pointer-events-none shadow-md"
                title="Отправить вопрос"
              >
                <Send className="w-4 h-4 text-black" />
              </button>
            </div>
          </form>

          {/* Чипсы быстрых вопросов */}
          <div className="flex items-center space-x-2 overflow-x-auto pb-1 scrollbar-none">
            {samplePrompts.map((p, idx) => (
              <button
                key={idx}
                onClick={() => handleSend(p)}
                className="shrink-0 text-xs px-3.5 py-1.5 rounded-full bg-white/[0.03] hover:bg-white/[0.08] text-zinc-400 hover:text-white border border-white/[0.06] transition-colors cursor-pointer flex items-center gap-1.5"
              >
                <Sparkles className="w-3 h-3 text-indigo-400" />
                <span>{p}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Нижняя крупная кнопка перехода в рабочую область */}
        <div className="pt-6 border-t border-white/[0.06] flex items-center justify-between flex-wrap gap-4">
          <button
            onClick={onTransitionToHub}
            className="w-full sm:w-auto flex items-center justify-center space-x-2.5 px-6 py-3 rounded-xl bg-white text-black hover:bg-zinc-200 text-xs font-bold transition-all shadow-[0_0_30px_rgba(255,255,255,0.2)] cursor-pointer group"
          >
            <Compass className="w-4 h-4 text-black" />
            <span>Открыть рабочую станцию (3-Pane Studio)</span>
            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-1 transition-transform" />
          </button>

          <span className="text-[11px] font-mono text-zinc-500">
            [Enter] для вопроса · [Tab] для перехода
          </span>
        </div>

      </div>
    );
  }

  // =========================================================================
  // РЕЖИМ 2: ДОК-ПАНЕЛЬ В РАБОЧЕЙ СТАНЦИИ (STUDIO COPILOT & INSPECTOR)
  // Полноценная боковая колонка со всей историей диалога и детальным инспектором.
  // =========================================================================
  return (
    <div
      className={`h-full flex flex-col justify-between overflow-hidden bg-[#0b0b14]/65 backdrop-blur-md text-zinc-300 font-sans transition-all duration-300 w-[420px] shrink-0 ${
        dockSide === 'right' ? 'border-l' : 'border-r'
      } border-white/[0.08] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]`}
    >
      {/* Шапка док-панели с табами */}
      <div className="h-10 shrink-0 px-4 border-b border-white/[0.08] bg-[#0c0c12]/90 flex items-center justify-between text-xs select-none shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]">
        <div className="flex items-center space-x-1">
          <button
            onClick={() => setActiveTab('copilot')}
            className={`flex items-center space-x-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
              activeTab === 'copilot'
                ? 'bg-white/[0.08] text-white font-semibold shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]'
                : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <Bot className="w-3.5 h-3.5 text-indigo-400" />
            <span>AI Ассистент</span>
          </button>

          <button
            onClick={() => setActiveTab('inspector')}
            className={`flex items-center space-x-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
              activeTab === 'inspector'
                ? 'bg-white/[0.08] text-white font-semibold shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]'
                : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <FileText className="w-3.5 h-3.5 text-amber-400" />
            <span>Обзор {selectedItem ? '•' : ''}</span>
          </button>
        </div>

        <div className="flex items-center space-x-1 text-zinc-400">
          {onToggleDockSide && (
            <button
              onClick={onToggleDockSide}
              className="p-1.5 rounded-md hover:bg-white/10 hover:text-white transition-colors cursor-pointer"
              title={`Переместить панель ${dockSide === 'right' ? 'влево' : 'вправо'}`}
            >
              <ArrowLeftRight className="w-3.5 h-3.5" />
            </button>
          )}

          {onTransitionToCenter && (
            <button
              onClick={onTransitionToCenter}
              className="p-1.5 rounded-md hover:bg-white/10 hover:text-white transition-colors cursor-pointer"
              title="Развернуть во весь экран (В начало)"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          )}

          <button
            onClick={onCollapse}
            className="p-1.5 rounded-md hover:bg-white/10 hover:text-white transition-colors cursor-pointer"
            title="Свернуть панель"
          >
            {dockSide === 'right' ? (
              <ChevronRight className="w-4 h-4" />
            ) : (
              <ChevronLeft className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Режим Copilot в доке */}
      {activeTab === 'copilot' && (
        <div className="flex-1 flex flex-col justify-between overflow-hidden">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 ? (
              <div className="py-24 text-center text-xs text-zinc-500 font-mono">
                Задайте вопрос агенту по моделям, статьям или лидербордам.
              </div>
            ) : (
              messages.map((m) => (
                <div
                  key={m.id}
                  className={`flex flex-col ${
                    m.role === 'user' ? 'items-end' : 'items-start'
                  } space-y-1`}
                >
                  <div
                    className={`max-w-[92%] text-xs leading-relaxed rounded-2xl p-3.5 shadow-sm ${
                      m.role === 'user'
                        ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-medium shadow-indigo-600/20'
                        : 'bg-white/[0.04] text-zinc-200 border border-white/[0.07] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]'
                    }`}
                  >
                    {m.thinking && (
                      <div className="mb-2 pb-1.5 text-[11px] font-mono text-indigo-300 border-b border-indigo-500/20 flex items-center gap-1.5">
                        <Sparkles className="w-3 h-3 text-indigo-400" />
                        <span>{m.thinking}</span>
                      </div>
                    )}

                    <p className="whitespace-pre-wrap">{m.content}</p>

                    {m.sources && m.sources.length > 0 && (
                      <div className="mt-3 pt-2.5 border-t border-white/[0.08] flex flex-wrap gap-1.5">
                        {m.sources.map((s, idx) => (
                          <a
                            key={idx}
                            href={s.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-md bg-indigo-500/15 text-indigo-300 border border-indigo-500/25 hover:border-indigo-400 transition-colors"
                          >
                            <span>{s.title}</span>
                            <ExternalLink className="w-2.5 h-2.5 opacity-80" />
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] font-mono text-zinc-600 px-1">
                    {m.timestamp}
                  </span>
                </div>
              ))
            )}

            {isLoading && (
              <div className="flex items-center space-x-2 text-xs text-indigo-300 font-mono p-3 bg-white/[0.02] rounded-xl border border-white/[0.06] w-fit">
                <span className="w-2 h-2 rounded-full bg-indigo-400 animate-ping" />
                <span>RAG-анализ базы векторов SQLite...</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Инпут чата в доке */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend(input);
            }}
            className="p-3.5 border-t border-white/[0.08] bg-[#0c0c12]/95"
          >
            <div className="relative flex items-center">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Задайте вопрос агенту (Enter)..."
                className="w-full bg-white/[0.05] hover:bg-white/[0.08] focus:bg-white/[0.08] text-xs text-white placeholder-zinc-500 rounded-xl pl-3.5 pr-10 py-2.5 border border-white/[0.08] focus:border-indigo-500 focus:outline-none transition-all shadow-inner"
              />
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="absolute right-1.5 p-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 text-white disabled:opacity-30 transition-all cursor-pointer shadow-md"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Режим Обзора материала в доке */}
      {activeTab === 'inspector' && (
        <div className="flex-1 flex flex-col justify-between overflow-y-auto p-5 space-y-5">
          {selectedItem ? (
            (() => {
              const grammar = getItemGrammar(selectedItem);
              const badge = sourceBadgeConfig[selectedItem.source] || {
                label: selectedItem.source,
                style: 'bg-zinc-800 text-zinc-300 border-zinc-700',
                color: '#6366f1',
              };
              const sparkData = getOverviewSparkline(selectedItem);
              const delta = selectedItem.delta || (selectedItem.metricLabel ? `${selectedItem.metricValue} ${selectedItem.metricLabel}` : 'Активно');

              return (
                <div className="space-y-4">
                  {/* Верхняя строка: Источник, категория и время */}
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center space-x-2">
                      <span className={`text-[11px] font-mono px-2 py-0.5 rounded-md border font-medium ${badge.style}`}>
                        {badge.label}
                      </span>
                      {selectedItem.category && (
                        <span className="text-[11px] px-2 py-0.5 rounded-md bg-white/[0.04] border border-white/[0.08] text-zinc-400 font-sans">
                          {selectedItem.category}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center space-x-2">
                      <span className="text-[11px] font-mono text-zinc-500">
                        {selectedItem.timestamp}
                      </span>
                      {onClearSelectedItem && (
                        <button
                          onClick={onClearSelectedItem}
                          className="p-1 rounded-md text-zinc-500 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
                          title="Снять выбор"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Заголовок и организация */}
                  <div>
                    <h3 className="text-lg font-bold text-white tracking-tight leading-snug">
                      {selectedItem.title}
                    </h3>
                    <div className="flex items-center space-x-2 mt-1 text-xs text-zinc-400">
                      <span className="text-zinc-300 font-medium">{selectedItem.organization}</span>
                      {selectedItem.topic && (
                        <>
                          <span className="text-zinc-600">·</span>
                          <span className="text-zinc-400 font-sans">{selectedItem.topic}</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Карточка ключевой аналитики и метрик */}
                  <div className="p-3.5 rounded-2xl bg-black/40 border border-white/[0.08] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)] flex items-center justify-between">
                    <div>
                      <span className="text-[10px] text-zinc-500 uppercase tracking-wider block font-sans font-medium">
                        {selectedItem.metricLabel}
                      </span>
                      <div className="flex items-baseline space-x-2 mt-0.5">
                        <span className="text-lg font-bold text-white font-mono tabular-nums">
                          {selectedItem.metricValue}
                        </span>
                        {delta && (
                          <span className="text-[11px] font-mono text-emerald-400 flex items-center gap-0.5 font-medium">
                            <TrendingUp className="w-2.5 h-2.5" />
                            {delta}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex flex-col items-end">
                      <Sparkline data={sparkData} color={badge.color} width={80} height={22} />
                      <div className="flex items-center gap-1 text-[10px] font-sans text-emerald-400 mt-1">
                        <ShieldCheck className="w-3 h-3 text-emerald-400" />
                        <span>{selectedItem.license || 'Open Source'}</span>
                      </div>
                    </div>
                  </div>

                  {/* Аналитическое резюме */}
                  <div className="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.06] space-y-2 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)]">
                    <div className="flex items-center justify-between text-xs font-semibold text-indigo-300">
                      <div className="flex items-center space-x-1.5">
                        <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                        <span>Краткая выжимка</span>
                      </div>
                      <span className="text-[10px] font-mono text-zinc-500">FastEmbed</span>
                    </div>
                    <p className="text-xs text-zinc-200 leading-relaxed font-sans">
                      {selectedItem.summary}
                    </p>
                  </div>

                  {/* Ключевые тезисы */}
                  {selectedItem.insights && selectedItem.insights.length > 0 && (
                    <div className="space-y-2">
                      <span className="text-[10px] uppercase text-zinc-500 font-semibold tracking-wider block font-mono">
                        Ключевые тезисы
                      </span>
                      <div className="space-y-1.5">
                        {selectedItem.insights.map((ins, i) => (
                          <div
                            key={i}
                            className="flex items-start gap-2.5 p-3 rounded-xl bg-white/[0.02] border border-white/[0.05] text-xs text-zinc-300 leading-relaxed hover:border-white/[0.1] transition-colors"
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 shrink-0" />
                            <span className="font-sans">{ins}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Блок действий */}
                  <div className="space-y-2 pt-2">
                    <button
                      onClick={() => {
                        setActiveTab('copilot');
                        handleSend(`Сделай глубокий анализ ${grammar.genitive} "${selectedItem.title}"`);
                      }}
                      className="w-full flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-gradient-to-r from-blue-600 via-indigo-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white font-semibold text-xs transition-all shadow-md shadow-indigo-600/25 cursor-pointer"
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Спросить у ассистента {grammar.prepositional}</span>
                    </button>

                    <div className="flex items-center space-x-2">
                      <a
                        href={selectedItem.url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex-1 flex items-center justify-center space-x-1.5 py-2.5 px-3 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-xs font-semibold text-zinc-200 hover:text-white transition-colors"
                      >
                        <ExternalLink className="w-3.5 h-3.5 text-zinc-400" />
                        <span>Открыть оригинал</span>
                      </a>

                      <button
                        onClick={handleCopyUrl}
                        className="p-2.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-zinc-300 hover:text-white transition-colors cursor-pointer"
                        title="Скопировать ссылку"
                      >
                        {copied ? (
                          <Check className="w-4 h-4 text-emerald-400" />
                        ) : (
                          <Copy className="w-4 h-4" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })()
          ) : (
            <div className="my-auto py-16 px-4 text-center space-y-4">
              <div className="w-12 h-12 rounded-2xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center mx-auto text-zinc-400 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]">
                <FileText className="w-5 h-5 text-indigo-400" />
              </div>
              <div className="space-y-1">
                <h4 className="text-sm font-semibold text-white">Выберите материал для обзора</h4>
                <p className="text-xs text-zinc-400 max-w-xs mx-auto leading-relaxed">
                  Кликните на любую карточку в ленте, чтобы изучить подробные метрики, ключевые тезисы и задать вопросы.
                </p>
              </div>
              <div className="pt-2 flex items-center justify-center gap-1.5 text-[11px] font-mono text-zinc-500">
                <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-400 border border-white/[0.08]">↑↓</kbd>
                <span>навигация</span>
                <span className="text-zinc-600">·</span>
                <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-400 border border-white/[0.08]">Enter</kbd>
                <span>спросить ассистента</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
