import type { IntelItem, TabType } from '../types/intel';

export interface ItemTypeGrammar {
  type: 'model' | 'paper' | 'dataset' | 'repo' | 'benchmark';
  nominative: string;
  prepositional: string;
  genitive: string;
  accusative: string;
  actionPrompt: string;
}

/**
 * Возвращает грамматически корректные русские формы для конкретного типа контента:
 * модель, статья, датасет, репозиторий, бенчмарк.
 */
export function getItemGrammar(item?: IntelItem | null): ItemTypeGrammar {
  if (!item) {
    return {
      type: 'model',
      nominative: 'материал',
      prepositional: 'об этом материале',
      genitive: 'материала',
      accusative: 'материал',
      actionPrompt: 'об этом материале',
    };
  }

  const cat = (item.category || '').toLowerCase();
  const title = (item.title || '').toLowerCase();
  const src = item.source;

  // Датасеты
  if (cat.includes('dataset') || cat.includes('датасет') || title.includes('dataset')) {
    return {
      type: 'dataset',
      nominative: 'датасет',
      prepositional: 'об этом датасете',
      genitive: 'датасета',
      accusative: 'датасет',
      actionPrompt: 'об этом датасете',
    };
  }

  // Научные статьи (ArXiv)
  if (src === 'ArXiv' || cat.includes('paper') || cat.includes('research') || cat.includes('preprint')) {
    return {
      type: 'paper',
      nominative: 'статья',
      prepositional: 'об этой статье',
      genitive: 'статьи',
      accusative: 'статью',
      actionPrompt: 'об этой статье',
    };
  }

  // Репозитории GitHub / исходный код
  if (src === 'GitHub' || cat.includes('repo') || cat.includes('engine') || cat.includes('framework')) {
    return {
      type: 'repo',
      nominative: 'репозиторий',
      prepositional: 'об этом репозитории',
      genitive: 'репозитория',
      accusative: 'репозиторий',
      actionPrompt: 'об этом репозитории',
    };
  }

  // Бенчмарки и лидерборд LMSys Arena
  if (src === 'LMSys Arena' || cat.includes('benchmark') || cat.includes('arena')) {
    return {
      type: 'benchmark',
      nominative: 'бенчмарк',
      prepositional: 'о результатах этого бенчмарка',
      genitive: 'бенчмарка',
      accusative: 'бенчмарк',
      actionPrompt: 'о результатах этого бенчмарка',
    };
  }

  // По умолчанию: AI/ML модель (Hugging Face / веса)
  return {
    type: 'model',
    nominative: 'модель',
    prepositional: 'об этой модели',
    genitive: 'модели',
    accusative: 'модель',
    actionPrompt: 'об этой модели',
  };
}

/**
 * Возвращает название потока данных для заголовка ленты
 */
export function getTabHeaderCountLabel(tab: TabType, count: number): string {
  switch (tab) {
    case 'Models':
      return `${count} проверенных моделей`;
    case 'Research':
      return `${count} научных статей`;
    case 'GitHub':
      return `${count} трендовых репозиториев`;
    case 'Arena':
      return `${count} моделей в рейтинге LMSys`;
    case 'All Stream':
    default:
      return `${count} актуальных материалов`;
  }
}
