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
