import type { LeaderboardRecord } from '../types/domain';

export const ALL_CATEGORIES = 'Все категории';

export function toNumber(value: any): number | null {
  if (typeof value === 'boolean' || value == null) return null;
  if (typeof value === 'string') {
    value = value.replace('%', '').trim();
  }
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

export function buildLatestRecords(snapshots: any[]): LeaderboardRecord[] {
  const records: LeaderboardRecord[] = [];
  const seenCategories = new Set<string>();

  const sortedSnaps = [...snapshots].sort((a, b) =>
    String(b.fetched_at || '').localeCompare(String(a.fetched_at || ''))
  );

  for (const snap of sortedSnaps) {
    const fetchedAt = snap.fetched_at;
    const categories = snap.categories || {};
    for (const [category, models] of Object.entries(categories)) {
      if (seenCategories.has(category)) continue;
      seenCategories.add(category);

      for (const m of models as any[]) {
        const name = m.name;
        const rating = toNumber(m.rating);
        if (!name || rating == null) continue;

        records.push({
          category,
          model_name: name,
          rating,
          fetched_at: fetchedAt,
          organization: m.organization || '',
          license: m.license || '',
          vote_count: Number(m.vote_count) || 0,
          summary: m.summary || '',
          url: m.url || '',
        });
      }
    }
  }

  return records;
}

export function aggregateAllCategories(
  records: LeaderboardRecord[],
  method: 'avg' | 'max' = 'avg'
): LeaderboardRecord[] {
  const byModel = new Map<string, { ratings: number[]; categories: string[]; orig: LeaderboardRecord }>();

  for (const r of records) {
    if (!byModel.has(r.model_name)) {
      byModel.set(r.model_name, { ratings: [], categories: [], orig: r });
    }
    const entry = byModel.get(r.model_name)!;
    entry.ratings.push(r.rating);
    if (!entry.categories.includes(r.category)) {
      entry.categories.push(r.category);
    }
  }

  const result: LeaderboardRecord[] = [];
  for (const [name, entry] of byModel.entries()) {
    let aggRating = 0;
    if (method === 'avg') {
      aggRating = Math.round(entry.ratings.reduce((a, b) => a + b, 0) / entry.ratings.length);
    } else {
      aggRating = Math.round(Math.max(...entry.ratings));
    }

    result.push({
      ...entry.orig,
      model_name: name,
      rating: aggRating,
      category: ALL_CATEGORIES,
      categories: entry.categories,
    });
  }

  result.sort((a, b) => b.rating - a.rating);
  return result;
}

export function formatRating(val: number | null | undefined): string {
  if (val == null) return '—';
  return Math.round(val).toString();
}

export function categoryCountLabel(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${n} категория`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return `${n} категории`;
  return `${n} категорий`;
}

export function formatTimestampRu(tsStr: string | null | undefined): string {
  if (!tsStr) return 'нет данных';
  try {
    let s = String(tsStr).trim();
    if (s.endsWith('Z')) s = s.slice(0, -1) + '+00:00';
    const dt = new Date(s);
    if (isNaN(dt.getTime())) return String(tsStr);

    const months = [
      'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
      'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
    ];

    const day = dt.getDate();
    const month = months[dt.getMonth()];
    const year = dt.getFullYear();
    const hours = String(dt.getHours()).padStart(2, '0');
    const minutes = String(dt.getMinutes()).padStart(2, '0');

    return `${day} ${month} ${year} г., ${hours}:${minutes} (МСК)`;
  } catch {
    return String(tsStr);
  }
}

/**
 * Формирует прямую валидную ссылку на модель или платформу разработчика.
 * Устраняет проблему битых ссылок при слепом поиске на Hugging Face для проприетарных
 * и коммерческих моделей LMSYS Arena (Gemini, Claude, GPT, Grok и др.).
 */
export function getLeaderboardModelUrl(rec: {
  model_name: string;
  organization?: string;
  license?: string;
  category?: string;
  url?: string;
  source_url?: string;
}): string {
  if (rec.url && rec.url.startsWith('http')) {
    return rec.url;
  }
  if (rec.source_url && rec.source_url.startsWith('http')) {
    return rec.source_url;
  }

  const name = (rec.model_name || '').trim();
  const org = (rec.organization || '').toLowerCase().trim();
  const lic = (rec.license || '').toLowerCase().trim();
  const nameLower = name.toLowerCase();

  // Если имя модели уже содержит репозиторий "org/repo"
  if (name.includes('/') && !name.includes(' ')) {
    return `https://huggingface.co/${name}`;
  }

  // Очищенное базовое имя без суффиксов тегов бенчмарка в скобках:
  // "Claude Opus 5.5 (Max)" -> "Claude Opus 5.5"
  // "Gemini 4 Argon (High)" -> "Gemini 4 Argon"
  // "DeepSeek-V4.1-Flash-20261017 (Max)" -> "DeepSeek-V4.1-Flash"
  const cleanName = name
    .replace(/\s*\([^)]*\)/g, '')
    .replace(/-\d{8}$/, '')
    .trim();

  // 1. По популярным организациям и семействам моделей
  if (org === 'anthropic' || nameLower.startsWith('claude')) {
    return 'https://claude.ai/';
  }
  if (
    org === 'openai' ||
    nameLower.startsWith('gpt') ||
    nameLower.startsWith('o1') ||
    nameLower.startsWith('o3') ||
    nameLower.startsWith('chatgpt')
  ) {
    return 'https://chatgpt.com/';
  }
  if (org === 'google' || nameLower.startsWith('gemini')) {
    if (nameLower.startsWith('gemma')) {
      return `https://huggingface.co/google/${encodeURIComponent(cleanName.toLowerCase())}`;
    }
    return 'https://gemini.google.com/';
  }
  if (org === 'xai' || nameLower.startsWith('grok')) {
    return 'https://x.ai/';
  }
  if (org === 'deepseek' || nameLower.includes('deepseek')) {
    if (lic.includes('mit') || lic.includes('apache') || lic.includes('open')) {
      return `https://huggingface.co/models?search=deepseek-ai+${encodeURIComponent(cleanName)}`;
    }
    return 'https://chat.deepseek.com/';
  }
  if (org === 'alibaba' || nameLower.startsWith('qwen')) {
    return `https://huggingface.co/models?search=Qwen+${encodeURIComponent(cleanName)}`;
  }
  if (org === 'meta' || nameLower.startsWith('llama')) {
    if (nameLower.startsWith('llama')) {
      return `https://huggingface.co/models?search=meta-llama+${encodeURIComponent(cleanName)}`;
    }
    return 'https://about.meta.com/';
  }
  if (
    org === 'mistral' ||
    nameLower.includes('mistral') ||
    nameLower.includes('mixtral') ||
    nameLower.includes('codestral') ||
    nameLower.includes('pixtral')
  ) {
    return `https://huggingface.co/models?search=mistralai+${encodeURIComponent(cleanName)}`;
  }
  if (org === 'bfl' || nameLower.startsWith('flux')) {
    return `https://huggingface.co/models?search=black-forest-labs+${encodeURIComponent(cleanName)}`;
  }
  if (org === 'moonshot' || nameLower.startsWith('kimi')) {
    return 'https://kimi.moonshot.cn/';
  }
  if (org === 'minimax') {
    return 'https://www.minimax.io/';
  }
  if (org === 'bytedance' || nameLower.startsWith('doubao') || nameLower.startsWith('seed')) {
    return 'https://www.doubao.com/';
  }
  if (org === 'stepfun') {
    return 'https://www.stepfun.com/';
  }
  if (org === 'kling') {
    return 'https://klingai.com/';
  }
  if (org === 'runway') {
    return 'https://runwayml.com/';
  }
  if (org === 'luma-ai' || org === 'luma') {
    return 'https://lumalabs.ai/';
  }
  if (org === 'ideogram') {
    return 'https://ideogram.ai/';
  }
  if (org === 'recraft') {
    return 'https://www.recraft.ai/';
  }
  if (org === 'pika') {
    return 'https://pika.art/';
  }
  if (org === 'baidu' || nameLower.startsWith('ernie')) {
    return 'https://yiyan.baidu.com/';
  }
  if (org === 'tencent' || nameLower.startsWith('hy') || nameLower.startsWith('hunyuan')) {
    return 'https://hunyuan.tencent.com/';
  }
  if (org === 'nvidia') {
    return `https://huggingface.co/models?search=nvidia+${encodeURIComponent(cleanName)}`;
  }
  if (org === 'microsoft-ai' || org === 'microsoft' || nameLower.startsWith('phi')) {
    return `https://huggingface.co/models?search=microsoft+${encodeURIComponent(cleanName)}`;
  }
  if (org === 'perplexity') {
    return 'https://www.perplexity.ai/';
  }
  if (org === 'zai' || org === 'zhipu' || nameLower.startsWith('glm')) {
    return 'https://chatglm.cn/';
  }

  // 2. Если модель имеет открытую лицензию
  const isOpen = lic && !['proprietary', 'commercial', 'closed', 'unknown', ''].includes(lic);
  if (isOpen) {
    return `https://huggingface.co/models?search=${encodeURIComponent(cleanName)}`;
  }

  // 3. Fallback: официальный лидерборд LMSYS Chatbot Arena
  return 'https://lmarena.ai/?leaderboard';
}
