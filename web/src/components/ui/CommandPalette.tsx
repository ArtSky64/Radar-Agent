import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Database, BookOpen, GitFork, Flame, RotateCw, Bot, ArrowRight, CornerDownLeft, X, Layers, Cpu, Compass } from 'lucide-react';
import type { TabType, TopicFilter, IntelItem } from '../../types/intel';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectTab: (tab: TabType) => void;
  onSelectTopic: (topic: TopicFilter) => void;
  onForceScan: () => void;
  onGoToStart: () => void;
  onToggleChat: () => void;
  items: IntelItem[];
  onSelectItem: (item: IntelItem) => void;
}

interface CommandItem {
  id: string;
  category: 'Sources' | 'Topics' | 'Actions' | 'Signals';
  label: string;
  subtitle?: string;
  icon: React.ReactNode;
  action: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onSelectTab,
  onSelectTopic,
  onForceScan,
  onGoToStart,
  onToggleChat,
  items,
  onSelectItem,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Список всех возможных команд
  const staticCommands: CommandItem[] = [
    // Источники
    {
      id: 'src-all',
      category: 'Sources',
      label: 'Все источники данных',
      subtitle: 'Общий поток всех моделей, статей и репозиториев',
      icon: <Layers className="w-4 h-4 text-zinc-300" />,
      action: () => { onSelectTab('All Stream'); onClose(); },
    },
    {
      id: 'src-hf',
      category: 'Sources',
      label: 'Модели Hugging Face',
      subtitle: 'Открытые веса, чекпоинты и загрузки',
      icon: <Database className="w-4 h-4 text-amber-400" />,
      action: () => { onSelectTab('Models'); onClose(); },
    },
    {
      id: 'src-arxiv',
      category: 'Sources',
      label: 'Статьи ArXiv',
      subtitle: 'Научные препринты и исследования',
      icon: <BookOpen className="w-4 h-4 text-purple-400" />,
      action: () => { onSelectTab('Research'); onClose(); },
    },
    {
      id: 'src-gh',
      category: 'Sources',
      label: 'Тренды GitHub',
      subtitle: 'Трендовые репозитории и движки инференса',
      icon: <GitFork className="w-4 h-4 text-emerald-400" />,
      action: () => { onSelectTab('GitHub'); onClose(); },
    },
    {
      id: 'src-arena',
      category: 'Sources',
      label: 'Лидерборд LMSys Arena',
      subtitle: 'Человеческие блайнд-тесты и рейтинг Elo',
      icon: <Flame className="w-4 h-4 text-sky-400" />,
      action: () => { onSelectTab('Arena'); onClose(); },
    },
    // Направления
    {
      id: 'top-reasoning',
      category: 'Topics',
      label: 'Направление: Рассуждения и логика',
      subtitle: 'Chain-of-thought, рассуждающие модели и RL',
      icon: <span className="text-sm">🧠</span>,
      action: () => { onSelectTopic('Reasoning'); onClose(); },
    },
    {
      id: 'top-coding',
      category: 'Topics',
      label: 'Направление: Кодинг и AI-агенты',
      subtitle: 'Генерация кода, SWE-bench, архитектуры агентов',
      icon: <span className="text-sm">💻</span>,
      action: () => { onSelectTopic('Coding'); onClose(); },
    },
    {
      id: 'top-inference',
      category: 'Topics',
      label: 'Направление: Инференс и оптимизация',
      subtitle: 'vLLM, SGLang, FlashAttention, квантование',
      icon: <span className="text-sm">⚡</span>,
      action: () => { onSelectTopic('Inference'); onClose(); },
    },
    {
      id: 'top-vision',
      category: 'Topics',
      label: 'Направление: Мультимодальность',
      subtitle: 'VLM, пространственная компрессия токенов',
      icon: <span className="text-sm">👁️</span>,
      action: () => { onSelectTopic('Vision'); onClose(); },
    },
    // Системные действия
    {
      id: 'act-sync',
      category: 'Actions',
      label: 'Обновить радар / Собрать свежие данные',
      subtitle: 'Собрать свежие релизы с HF, GitHub, ArXiv и LMSys',
      icon: <RotateCw className="w-4 h-4 text-indigo-400" />,
      action: () => { onForceScan(); onClose(); },
    },
    {
      id: 'act-copilot',
      category: 'Actions',
      label: 'Свернуть / развернуть AI Ассистента',
      subtitle: 'Управление боковой панелью аналитика',
      icon: <Bot className="w-4 h-4 text-indigo-400" />,
      action: () => { onToggleChat(); onClose(); },
    },
    {
      id: 'act-start',
      category: 'Actions',
      label: 'Вернуться к экрану приветствия',
      subtitle: 'Начальный экран с раскрытым диалогом',
      icon: <Compass className="w-4 h-4 text-zinc-400" />,
      action: () => { onGoToStart(); onClose(); },
    },
  ];

  // Динамические сигналы по поисковому запросу
  const signalCommands: CommandItem[] = items.slice(0, 6).map((item) => ({
    id: `item-${item.id}`,
    category: 'Signals',
    label: item.title,
    subtitle: `${item.source} · ${item.organization} · ${item.metricValue} ${item.metricLabel}`,
    icon: <span className="text-xs font-mono font-bold text-indigo-400">✦</span>,
    action: () => {
      onSelectItem(item);
      onClose();
    },
  }));

  const allAvailable = [...staticCommands, ...signalCommands];

  const filteredCommands = query.trim() === ''
    ? allAvailable
    : allAvailable.filter(
        (c) =>
          c.label.toLowerCase().includes(query.toLowerCase()) ||
          (c.subtitle && c.subtitle.toLowerCase().includes(query.toLowerCase())) ||
          c.category.toLowerCase().includes(query.toLowerCase())
      );

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Обработка клавиатуры в модалке
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % Math.max(1, filteredCommands.length));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredCommands.length) % Math.max(1, filteredCommands.length));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filteredCommands[selectedIndex]) {
          filteredCommands[selectedIndex].action();
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, filteredCommands, selectedIndex, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4 bg-black/60 backdrop-blur-md">
      {/* Клик мимо для закрытия */}
      <div className="fixed inset-0" onClick={onClose} />

      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: -12 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: -12 }}
        transition={{ type: 'spring', damping: 25, stiffness: 350 }}
        className="relative z-10 w-full max-w-xl rounded-2xl bg-[#0e0e14]/95 border border-white/12 shadow-[0_24px_80px_rgba(0,0,0,0.9),inset_0_1px_0_0_rgba(255,255,255,0.1)] overflow-hidden"
      >
        {/* Поле ввода команды */}
        <div className="flex items-center px-4 py-3.5 border-b border-white/[0.08]">
          <Search className="w-4 h-4 text-zinc-400 mr-3 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Быстрый поиск моделей, статей, репозиториев или действий..."
            className="w-full bg-transparent text-sm text-white placeholder-zinc-500 focus:outline-none font-sans"
          />
          <button
            onClick={onClose}
            className="p-1 rounded-md text-zinc-500 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Список команд */}
        <div className="max-h-96 overflow-y-auto p-2 space-y-0.5">
          {filteredCommands.length === 0 ? (
            <div className="py-12 text-center text-xs text-zinc-500 font-mono">
              Ничего не найдено по запросу «{query}»
            </div>
          ) : (
            filteredCommands.map((cmd, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={cmd.id}
                  onClick={() => cmd.action()}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-colors ${
                    isSelected
                      ? 'bg-indigo-600/25 text-white border border-indigo-500/30'
                      : 'hover:bg-white/[0.04] text-zinc-300 border border-transparent'
                  }`}
                >
                  <div className="flex items-center space-x-3 min-w-0 pr-2">
                    <div className="shrink-0 w-6 h-6 rounded-lg bg-white/[0.04] flex items-center justify-center">
                      {cmd.icon}
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-white truncate">
                        {cmd.label}
                      </div>
                      {cmd.subtitle && (
                        <div className="text-[11px] text-zinc-500 truncate">
                          {cmd.subtitle}
                        </div>
                      )}
                    </div>
                  </div>

                  {isSelected && (
                    <div className="flex items-center space-x-1 shrink-0 text-[10px] font-mono text-indigo-300">
                      <span>Выбрать</span>
                      <CornerDownLeft className="w-3 h-3" />
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Подвал с подсказками клавиш */}
        <div className="px-4 py-2 border-t border-white/[0.06] bg-[#09090d]/80 flex items-center justify-between text-[11px] font-mono text-zinc-500">
          <div className="flex items-center space-x-3">
            <span><kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-300 border border-white/[0.08]">↑↓</kbd> Навигация</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-300 border border-white/[0.08]">Enter</kbd> Выбор</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-300 border border-white/[0.08]">Esc</kbd> Закрыть</span>
          </div>
          <span className="text-zinc-500 font-sans">Ctrl + K</span>
        </div>
      </motion.div>
    </div>
  );
};
