// D71: how a card asks the deal sheet (components/DealSheet.tsx) to open. Kept apart so cards don't import the sheet.
import type { Deal } from "./types";

export type Open = { slug: string; src: string };
export const EVENT = "fo:open-deal";

/** Open a deal in the sheet. Returns false when no sheet is mounted (the caller then lets the link navigate). */
export function openDeal(d: Deal, source = "web"): boolean {
  if (typeof window === "undefined" || !(window as { foSheet?: boolean }).foSheet) return false;
  window.dispatchEvent(new CustomEvent<Open>(EVENT, { detail: { slug: d.slug, src: source } }));
  return true;
}

/** For a card's onClick: open the sheet on a plain left click, else let the browser do its thing (new tab etc.). */
export function onCardClick(e: React.MouseEvent, d: Deal, source?: string): void {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  if (openDeal(d, source)) e.preventDefault();
}
