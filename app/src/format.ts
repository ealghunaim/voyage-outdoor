// Display formatting. One place, because a distance rendered two ways in one
// app is a distance the user cannot compare against itself.

export type DistanceUnit = 'km' | 'mi';
export type WeightUnit = 'g' | 'oz';

const KM_PER_MI = 1.609344;
const G_PER_OZ = 28.3495;

/** Metres → the user's unit. Shoe mileage is the number this app is judged on,
 *  so it rounds to whole units above 10 and one decimal below — 284 km reads
 *  as a fact, 284.3 km reads as a measurement nobody made. */
export function distance(metres: number | null | undefined, unit: DistanceUnit = 'km'): string {
  if (metres === null || metres === undefined) return '—';
  const km = metres / 1000;
  const value = unit === 'mi' ? km / KM_PER_MI : km;
  if (value === 0) return `0 ${unit}`;
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${unit}`;
}

export function weight(grams: number | null | undefined, unit: WeightUnit = 'g'): string {
  if (grams === null || grams === undefined) return '—';
  if (unit === 'oz') return `${(grams / G_PER_OZ).toFixed(1)} oz`;
  return grams >= 1000 ? `${(grams / 1000).toFixed(2)} kg` : `${grams} g`;
}

/** Seconds → h/m. Ultra durations are hours; a training run is minutes. */
export function duration(seconds: number | null | undefined): string {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (h && m) return `${h}h ${m}m`;
  if (h) return `${h}h`;
  return `${m}m`;
}

export function money(cents: number | null | undefined, currency?: string | null): string {
  if (cents === null || cents === undefined) return '—';
  const amount = (cents / 100).toFixed(2);
  return currency ? `${amount} ${currency.toUpperCase()}` : amount;
}

/** An ISO date as something a person reads. Dates in this app are calendar
 *  days — a run happened on a day — so no time and no timezone maths. */
export function day(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${d} ${months[m - 1]} ${y}`;
}

/** "3 days ago" for the last-used line, where the exact date matters less than
 *  whether it was recent. */
export function since(iso: string | null | undefined): string {
  if (!iso) return 'never used';
  const then = new Date(`${iso.slice(0, 10)}T00:00:00Z`).getTime();
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (!Number.isFinite(days)) return day(iso);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  if (days < 365) return `${Math.round(days / 30)} months ago`;
  return `${Math.round(days / 365)} years ago`;
}

export function titleCase(key: string): string {
  return key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
}
