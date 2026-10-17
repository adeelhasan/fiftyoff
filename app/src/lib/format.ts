// Display helpers, after web/lib/format.ts. No price math: every number shown comes from the API as is (rule 7).
import { SITE, SURFACE } from './config';
import type { CondId, Deal } from './types';

export const money = (n: number) =>
  '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const count = (n: number) => n.toLocaleString('en-US');

export function minutesSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Math.max(0, Math.round((now - t) / 60000));
}

/** "40 min ago", "3 h ago", "2 d ago", "over a week ago" (D65). */
export function ago(min: number | null): string {
  if (min === null) return '';
  if (min < 60) return `${min} min ago`;
  if (min < 1440) return `${Math.round(min / 60)} h ago`;
  if (min < 7 * 1440) return `${Math.round(min / 1440)} d ago`;
  return 'over a week ago';
}

/** "3 SIZES" / "2 VERSIONS" when a card groups variants (D65). */
export function variantTag(d: Deal): string {
  if (d.variants > 1) return `${d.variants} ${d.fit ? 'SIZES' : 'VERSIONS'}`;
  return '';
}

/** The ASIN a deal slug starts with (as the web's DealView reads it). */
export const asinOf = (slug: string) => slug.slice(0, 10).toUpperCase();

/** Our /d/ redirect to Amazon, tagged s=ios (the server keeps only known surfaces; finer app surfaces are a
 * web-api-for-mobile item). Opened in Safari or the Amazon app, never a WebView. */
export function amazonUrl(d: Pick<Deal, 'url'>): string {
  return `${SITE}${d.url}${d.url.includes('?') ? '&' : '?'}s=${SURFACE}`;
}

export const GRADE_HINT: Record<string, string> = {
  'Like New': 'As new, may be open-box',
  'Very Good': 'Light signs of use',
  Good: 'Noticeable wear, works fully',
  Acceptable: 'Visible wear, may lack extras',
};

/** The condition preference (onboarding step 2, Settings) and what it asks the API for. */
export type CondPref = 'ln' | 'good' | 'any';
export const COND_OPTIONS: { id: CondPref; label: string; hint: string }[] = [
  { id: 'ln', label: 'Like New', hint: 'As new, may be open-box.' },
  { id: 'good', label: 'Up to Good', hint: 'Like New, Very Good and Good: may show wear, works fully.' },
  { id: 'any', label: 'Anything', hint: 'Includes Acceptable: visible wear, may lack extras.' },
];
export function condIds(p: CondPref): CondId[] {
  if (p === 'ln') return ['like-new'];
  if (p === 'good') return ['like-new', 'very-good', 'good'];
  return ['like-new', 'very-good', 'good', 'acceptable'];
}
export function condAllows(p: CondPref, condition: string): boolean {
  const id = condition.toLowerCase().replace(/ /g, '-') as CondId;
  return condIds(p).includes(id);
}
