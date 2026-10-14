// The one client for /api/v1 (same origin in production). NEXT_PUBLIC_API=fixtures serves web/fixtures/
// (lib/fixtures.ts) instead, for `next dev`: beta sits behind Basic Auth and is cross-origin from localhost.
import type {
  AlmostResponse,
  DealsQuery,
  DealsResponse,
  GoneResponse,
  GoneWindow,
  MySizes,
  ProductResponse,
  ShelfResponse,
  ShelvesResponse,
  SizedResponse,
  SizesResponse,
  TodayResponse,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  // Inline env check, so the bundler drops the fixtures from production builds entirely.
  if (process.env.NEXT_PUBLIC_API === "fixtures") return (await (await import("./fixtures")).fixture(path)) as T;
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new ApiError(r.status, `${path}: ${r.status}`);
  return (await r.json()) as T;
}

function qs(q: DealsQuery): string {
  const p = new URLSearchParams();
  if (q.cond?.length) p.set("cond", q.cond.join(","));
  if (q.price && q.price !== "any") p.set("price", q.price);
  if (q.aisle) p.set("aisle", q.aisle);
  if (q.nofit) p.set("nofit", "true");
  if (q.sort && q.sort !== "newest") p.set("sort", q.sort);
  if (q.since) p.set("since", q.since);
  if (q.limit) p.set("limit", String(q.limit));
  if (q.offset) p.set("offset", String(q.offset));
  if (q.q) p.set("q", q.q);
  if (q.hide?.length) p.set("hide", q.hide.join(","));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  today: () => get<TodayResponse>("/api/v1/today"),
  deals: (q: DealsQuery = {}) => get<DealsResponse>(`/api/v1/deals${qs(q)}`),
  shelves: () => get<ShelvesResponse>("/api/v1/shelves"),
  shelf: (id: string) => get<ShelfResponse>(`/api/v1/shelves/${encodeURIComponent(id)}`),
  almost: () => get<AlmostResponse>("/api/v1/almost"),
  gone: (window: GoneWindow) => get<GoneResponse>(`/api/v1/gone?window=${window}`),
  product: (asin: string) => get<ProductResponse>(`/api/v1/product/${encodeURIComponent(asin)}`),
  sizes: () => get<SizesResponse>("/api/v1/sizes"),
  sized: (m: MySizes, offset = 0) => {
    const p = new URLSearchParams();
    for (const k of ["letter", "num", "waist", "length", "shoe"] as const) if (m[k].length) p.set(k, m[k].join(","));
    if (offset) p.set("offset", String(offset));
    const s = p.toString();
    return get<SizedResponse>(`/api/v1/sized${s ? `?${s}` : ""}`);
  },
};

/** Count a page view (D56): page and A/B arm only. Fire and forget; never in fixtures mode. */
export function countView(page: string, v: string): void {
  if (process.env.NEXT_PUBLIC_API === "fixtures") return;
  try {
    void fetch(`/api/v1/view?page=${page}${v ? `&v=${v}` : ""}`, { method: "POST", keepalive: true }).catch(() => {});
  } catch {
    /* counting never breaks a page */
  }
}
