// The one client for /api/v1 (same origin in production). NEXT_PUBLIC_API=fixtures serves web/fixtures/
// (lib/fixtures.ts) instead, for `next dev`: beta sits behind Basic Auth and is cross-origin from localhost.
import type {
  DealsQuery,
  DealsResponse,
  GoneResponse,
  GoneWindow,
  ProductResponse,
  ShelfResponse,
  ShelvesResponse,
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
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  today: () => get<TodayResponse>("/api/v1/today"),
  deals: (q: DealsQuery = {}) => get<DealsResponse>(`/api/v1/deals${qs(q)}`),
  shelves: () => get<ShelvesResponse>("/api/v1/shelves"),
  shelf: (id: string) => get<ShelfResponse>(`/api/v1/shelves/${encodeURIComponent(id)}`),
  gone: (window: GoneWindow) => get<GoneResponse>(`/api/v1/gone?window=${window}`),
  product: (asin: string) => get<ProductResponse>(`/api/v1/product/${encodeURIComponent(asin)}`),
};
