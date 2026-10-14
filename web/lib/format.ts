import { arm } from "./ab";
import type { Deal, Shelf } from "./types";

export const money = (n: number) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const count = (n: number) => n.toLocaleString("en-US");

export function minutesSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Math.max(0, Math.round((now - t) / 60000));
}

/** "40 min ago", "3 h ago", "2 d ago". */
export function ago(min: number | null): string {
  if (min === null) return "";
  if (min < 60) return `${min} min ago`;
  if (min < 1440) return `${Math.round(min / 60)} h ago`;
  return `${Math.round(min / 1440)} d ago`;
}

/** The card's freshness line: "New 2 h ago" (good green) or "1 d ago". */
export function freshness(d: Deal, now = Date.now()): { text: string; isNew: boolean } {
  const a = ago(minutesSince(d.landed_at, now));
  if (!a) return { text: "", isNew: d.is_new };
  return d.is_new ? { text: `New ${a}`, isNew: true } : { text: a, isNew: false };
}

/** A duration in minutes: "20 min", "15 h", "3 days", "4 months", "a year". */
export function span(min: number): string {
  if (min < 60) return `${min} min`;
  if (min < 48 * 60) return `${Math.round(min / 60)} h`;
  const days = min / 1440;
  if (days < 60) return `${Math.round(days)} days`;
  const months = days / 30.4;
  if (months < 12) return `${Math.floor(months)} months`;
  const years = Math.floor(months / 12);
  return years === 1 ? "a year" : `${years} years`;
}

/** "up for 15 h" when we saw it land. When we found it already listed, the number is the listing's age, not the
 * deal's (QA 10-12: "over a year" for a deal that lasted 20 minutes), so nothing is said. */
export function upFor(min: number | null, lowerBound: boolean): string {
  if (min === null || lowerBound) return "";
  return `up for ${span(min)}`;
}

/** "3 SIZES" / "2 VERSIONS" when the card groups variants (its price reads "from"); "2 AVAILABLE" for several units
 * of the same thing; nothing for one (REPORT 12). */
export function variantTag(d: Deal): string {
  if (d.variants > 1) return `${d.variants} ${d.fit ? "SIZES" : "VERSIONS"}`;
  if (d.units > 1) return `${d.units} AVAILABLE`;
  return "";
}

/** ["usually $129.99", "save $64.00"] (D36 allows the usual price for now). Empty without a usual price. */
export function usualParts(d: Deal): string[] {
  if (!d.usual_price || d.usual_price <= d.price) return [];
  return [`usually ${money(d.usual_price)}`, `save ${money(d.usual_price - d.price)}`];
}

/** A shelf's display name from the shelves map, or the id made readable. */
export function shelfName(id: string, shelves: Map<string, Shelf> | null): string {
  return shelves?.get(id)?.name ?? id.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** A card's outbound link: our /d/ redirect, tagged with where on the site it was (`s`) and the A/B arm (`v`). */
export function outLink(d: Deal, source = "web"): string {
  const v = typeof window === "undefined" ? "" : arm();
  return `${d.url}${d.url.includes("?") ? "&" : "?"}s=${source}${v ? `&v=${v}` : ""}`;
}
/** Links that leave for Amazon open in a new tab, so the feed stays where it was. */
export const OUT = { target: "_blank", rel: "noopener" } as const;
