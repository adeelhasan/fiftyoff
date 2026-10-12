// "New since your last look" (web.md): the device keeps last_seen_at in localStorage. A visit reads it once, uses
// it as `since` for the whole visit (so paging and filter changes don't move the line), and records "now" for the
// next visit. Rounded down to 10 minutes so the edge cache can still serve the request.

const KEY = "fo:last_seen_at";
const VISIT = "fo:visit_since"; // sessionStorage: this visit's `since`, kept across reloads in the tab
const TEN_MIN = 10 * 60 * 1000;

function round(ms: number): string {
  return new Date(Math.floor(ms / TEN_MIN) * TEN_MIN).toISOString().replace(".000Z", "Z");
}

/** This visit's `since`, or null on a first visit (then there's no "new" group). */
export function visitSince(): string | null {
  try {
    const kept = sessionStorage.getItem(VISIT);
    if (kept !== null) return kept || null;
    const prev = localStorage.getItem(KEY);
    const since = prev && !Number.isNaN(Date.parse(prev)) ? round(Date.parse(prev)) : "";
    sessionStorage.setItem(VISIT, since);
    return since || null;
  } catch {
    return null;
  }
}

/** Call after the feed loaded: the next visit counts from now. */
export function markSeen(): void {
  try {
    localStorage.setItem(KEY, new Date().toISOString());
  } catch {
    // private mode: no "new since" grouping, which is fine
  }
}
