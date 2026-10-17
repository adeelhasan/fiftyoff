// The app's one client for /api/v1 (docs/handoffs/api-v1.md). Server work it still waits for is stubbed here and
// listed in docs/handoffs/web-api-for-mobile.md.
import { API_BASE, SURFACE } from './config';
import type {
  DealsQuery,
  DealsResponse,
  MySizes,
  ProductResponse,
  ShelfResponse,
  ShelvesResponse,
  SizedResponse,
  SizesResponse,
  TodayResponse,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new ApiError(r.status, `${path}: ${r.status}`);
  return (await r.json()) as T;
}

function qs(q: DealsQuery): string {
  const p = new URLSearchParams();
  if (q.cond?.length) p.set('cond', q.cond.join(','));
  if (q.price && q.price !== 'any') p.set('price', q.price);
  if (q.aisle) p.set('aisle', q.aisle);
  if (q.nofit) p.set('nofit', 'true');
  if (q.sort && q.sort !== 'newest') p.set('sort', q.sort);
  if (q.limit) p.set('limit', String(q.limit));
  if (q.offset) p.set('offset', String(q.offset));
  if (q.q) p.set('q', q.q);
  const s = p.toString();
  return s ? `?${s}` : '';
}

export const api = {
  today: () => get<TodayResponse>('/today'),
  deals: (q: DealsQuery = {}) => get<DealsResponse>(`/deals${qs(q)}`),
  shelves: () => get<ShelvesResponse>('/shelves'),
  shelf: (id: string) => get<ShelfResponse>(`/shelves/${encodeURIComponent(id)}`),
  product: (asin: string) => get<ProductResponse>(`/product/${encodeURIComponent(asin)}`),
  sizes: () => get<SizesResponse>('/sizes'),
  sized: (m: MySizes, offset = 0) => {
    const p = new URLSearchParams();
    for (const k of ['letter', 'num', 'waist', 'length', 'shoe'] as const) if (m[k].length) p.set(k, m[k].join(','));
    if (offset) p.set('offset', String(offset));
    const s = p.toString();
    return get<SizedResponse>(`/sized${s ? `?${s}` : ''}`);
  },

  /** The weekly email sign-up (web-api-for-mobile §3). Until the endpoint exists the address is kept on the phone and
   * sent when it does: 'sent' = a confirm email is on its way; 'saved' = kept here for now. */
  weekly: async (email: string): Promise<'sent' | 'saved'> => {
    try {
      const r = await fetch(`${API_BASE}/weekly`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, s: SURFACE }),
      });
      if (r.ok) return 'sent';
      if (r.status === 404 || r.status === 405) return 'saved';
      throw new ApiError(r.status, `weekly: ${r.status}`);
    } catch (e) {
      if (e instanceof ApiError) throw e;
      return 'saved';
    }
  },
};

/** D64: a deal page opened. Fire and forget; counting never breaks a screen. */
export function countOpen(asin: string): void {
  try {
    const q = `id=${encodeURIComponent(asin)}&s=${SURFACE}`;
    void fetch(`${API_BASE}/open?${q}`, { method: 'POST' }).catch(() => {});
  } catch {
    /* ignore */
  }
}
