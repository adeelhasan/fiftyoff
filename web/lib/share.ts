import type { Deal } from "./types";

/** Our deal page for a card (trust-first §4.2). `share` tags it so the visit counts as arriving from a share. */
export function dealPath(d: Deal): string {
  return `/deal/${d.slug}/`;
}

export function shareUrl(d: Deal): string {
  return `${location.origin}${dealPath(d)}?s=share`;
}

/** The phone's share sheet, else copy the link. Resolves to what happened, for a short confirmation. */
export async function share(d: Deal): Promise<"shared" | "copied" | "failed"> {
  const url = shareUrl(d);
  const title = `${d.pct_off}% off: ${d.title}`;
  try {
    if (navigator.share) {
      await navigator.share({ title, url });
      return "shared";
    }
  } catch (e) {
    if ((e as Error)?.name === "AbortError") return "failed"; // the visitor closed the sheet
  }
  return (await copy(url)) ? "copied" : "failed";
}

/** A clean Amazon link plus a credit line, for deal communities that remove redirect links (REPORT 26). */
export function cleanText(d: Deal): string {
  return `https://www.amazon.com/dp/${d.id}?aod=1\nFound on fiftyOff: ${location.origin}${dealPath(d)}`;
}

export async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
