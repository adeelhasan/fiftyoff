// The public API v1 contract (docs/handoffs/api-v1.md). Plain types with no React or Next imports, so the
// future React Native app can import this file as is.

export type Condition = "Like New" | "Very Good" | "Good" | "Acceptable";

/** One card = one parent product. It quotes its cheapest unit; `from` says other variants cost more. */
export interface Deal {
  id: string; // the ASIN of the unit the card quotes
  slug: string;
  title: string;
  image: string | null;
  shelf: string; // shelf id
  aisle: string; // aisle id
  pct_off: number;
  price: number;
  from: boolean;
  usual_price: number | null;
  condition: Condition | string;
  variants: number;
  units: number;
  fit: boolean; // depends on size
  landed_at: string | null; // ISO, when we first priced it
  is_new: boolean;
  url: string; // always our /d/{slug}, never Amazon directly
}

export interface Gone extends Deal {
  gone_at: string;
  last_price: number;
  up_for_min: number | null;
  up_for_is_lower_bound: boolean;
}

export interface Shelf {
  id: string;
  name: string;
  aisle: string;
  aisle_name: string;
  description: string | null;
  live: number;
  per_week: number | null;
}

export interface AisleCount {
  id: string;
  name: string;
  count: number;
}

export interface Attribution {
  text: string;
  url: string;
}

export interface DealsResponse {
  deals: Deal[];
  count: number; // matches under the filters
  total: number; // every live public deal
  new_count: number | null; // cards that landed after `since` (they come first); null without `since`
  aisles: AisleCount[]; // counts under every filter except the aisle
  generated_at: string;
  attribution: Attribution;
}

export interface TodayResponse {
  just_in: Deal[];
  last_landed_at: string | null;
  aisles: AisleCount[];
  shelves: (Shelf & { deals: Deal[] })[];
  gone: Gone[];
}

export interface ShelvesResponse {
  shelves: Shelf[];
}

export interface ShelfResponse {
  shelf: Shelf;
  deals: Deal[];
}

export interface GoneResponse {
  gone: Gone[];
  count: number;
}

export interface ProductResponse {
  deal: Deal | null;
  gone: Gone | null;
  same_shelf: Deal[];
}

export type CondId = "like-new" | "very-good" | "good" | "acceptable";
export type PriceBand = "any" | "under-100" | "100-300" | "300-plus";
export type Sort = "newest" | "discount" | "price-asc" | "price-desc";
export type GoneWindow = "24h" | "3d" | "7d";

export interface DealsQuery {
  cond?: CondId[];
  price?: PriceBand;
  aisle?: string;
  nofit?: boolean;
  sort?: Sort;
  since?: string;
  limit?: number;
  offset?: number;
}
