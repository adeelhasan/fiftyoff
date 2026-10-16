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
  size: string | null; // D59: the quoted unit's size ("M", "Men's 10.5 Wide", "32×30"), on size-dependent cards
  landed_at: string | null; // ISO, when we first priced it
  is_new: boolean;
  url: string; // always our /d/{slug}, never Amazon directly
  confirmed_at: string | null; // ISO, our (or Keepa's feed's) last sighting of the quoted unit
  brand: string | null; // alerts-beta: prefills a keyword alert
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
  gone?: Gone[]; // with a search (q): matching deals that went in the last 7 days (D54)
  generated_at: string;
  attribution: Attribution;
}

export interface TodayResponse {
  featured: Deal[]; // today-quality §1: the best passing card of each shelf row, in row order
  just_in: Deal[]; // today-quality §4: gated, newest first; may be empty
  last_landed_at: string | null;
  count: number; // today-quality §9: live deals (All deals' default count)
  shelf_count: number; // shelves with live deals
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
  gone: Gone[]; // D66: this shelf's units gone in the last 7 days, newest first
}

export interface AlmostResponse {
  deals: Deal[]; // trust-first §4.4: under 50%, branded, well rated, seen within a day
}

export interface GoneResponse {
  gone: Gone[];
  count: number;
}

export interface ProductResponse {
  deal: Deal | null;
  gone: Gone | null;
  same_shelf: Deal[];
  same_size: string | null; // D69: the related cards are in this size (a sized deal), else null
}

export type CondId = "like-new" | "very-good" | "good" | "acceptable";
export type PriceBand = "any" | "under-100" | "100-300" | "300-plus";
export type Sort = "mixed" | "newest" | "discount" | "price-asc" | "price-desc" | "saved";
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
  q?: string; // search: title and brand words
  hide?: string[]; // aisles to leave out
}

/** D59: the size picker. Groups: letter, num, waist, length, shoe-men, shoe-women, shoe-kids. n = cards. */
export interface SizesResponse {
  groups: { id: string; name: string; values: { v: string; n: number }[] }[];
  sized: number; // size-dependent cards with a readable size
  unsized: number; // size-dependent cards whose size we can't read
  generated_at: string;
  attribution: Attribution;
}

/** D59: the visitor's sizes, kept on their device. Shoes are "men-10.5", "women-8", "kids-3". */
export interface MySizes {
  letter: string[];
  num: string[];
  waist: string[];
  length: string[];
  shoe: string[];
}

export interface SizedResponse {
  deals: Deal[];
  count: number;
  generated_at: string;
  attribution: Attribution;
}
