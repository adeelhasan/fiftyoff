// Keyword alerts (docs/handoffs/alerts-beta.md): the client for the alert routes, the signed-in state shared by the
// header and the pages, and the keyword a gone row or a deal suggests. Plain TS, no React.

export type AlertState = "pending" | "watching" | "fired" | "expired" | "stopped";
export type AlertSource = "search" | "deal" | "gone" | "sold" | "my-alerts";

export interface AlertRow {
  id: number;
  keyword: string;
  state: AlertState;
  armed_at: string | null;
  ends_at: string | null; // a free alert's lifetime end, while it's watching
  ended_at: string | null;
}

export interface Caught {
  alert: number;
  status: "missed" | "sent"; // missed: the unit went before the send window closed
  title: string;
  id: string; // ASIN
  at: string; // when the deal landed
}

export interface Me {
  email: string;
  tier: string;
  paused: boolean;
  max: number;
  delay_minutes: number;
  one_shot: boolean;
  lifetime_days: number;
  alerts: AlertRow[];
  caught: Caught[];
}

export interface AlertConfig {
  open: boolean;
  delay_minutes: number;
  lifetime_days: number;
  max_free: number;
}

export interface Full {
  error: "full";
  keyword: string;
  current: { id: number; keyword: string }[];
}

export interface Reply<T> {
  status: number;
  data: T | null;
  error?: string;
  full?: Full;
}

const off = () => process.env.NEXT_PUBLIC_API === "fixtures";

async function call<T>(path: string, body?: unknown): Promise<Reply<T>> {
  if (off()) return { status: 503, data: null, error: "alerts need the live API" };
  try {
    const r = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
    });
    const j = await r.json().catch(() => null);
    if (r.ok) return { status: r.status, data: j as T };
    return { status: r.status, data: null, error: j?.error ?? `HTTP ${r.status}`, full: j?.error === "full" ? (j as Full) : undefined };
  } catch {
    return { status: 0, data: null, error: "network" };
  }
}

export const alertsApi = {
  config: () => call<AlertConfig>("/api/v1/alerts/config"),
  me: () => call<Me>("/api/v1/me"),
  watch: (email: string, keyword: string, source: AlertSource) => call<{ ok: true }>("/api/v1/watch", { email, keyword, source }),
  signin: (email: string) => call<{ ok: true }>("/api/v1/signin", { email }),
  add: (keyword: string, source: AlertSource) => call<Me>("/api/v1/me/alerts", { keyword, source }),
  change: (id: number, action: "edit" | "stop" | "undo" | "rearm" | "swap", keyword?: string) =>
    call<Me>(`/api/v1/me/alerts/${id}`, { action, keyword }),
  pause: (paused: boolean) => call<Me>("/api/v1/me/pause", { paused }),
  stopAll: () => call<Me>("/api/v1/me/stop-all", {}),
  signout: () => call<{ ok: true }>("/api/v1/signout", {}),
};

// ---- the signed-in state: one copy per page load, shared by every component that asks

type Session = { me: Me | null; config: AlertConfig | null; loaded: boolean };
let session: Session = { me: null, config: null, loaded: false };
const listeners = new Set<() => void>();
let loading: Promise<void> | null = null;

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function snapshot(): Session {
  return session;
}

export function setMe(me: Me | null): void {
  session = { ...session, me };
  listeners.forEach((f) => f());
}

export function loadSession(force = false): Promise<void> {
  if (loading && !force) return loading;
  loading = Promise.all([alertsApi.config(), alertsApi.me()]).then(([c, m]) => {
    session = { config: c.data, me: m.data, loaded: true };
    listeners.forEach((f) => f());
  });
  return loading;
}

// ---- who sees the sign-up buttons: everyone once ALERTS_OPEN is set; before that, a browser that visited ?alerts=on

const FLAG = "fo:alerts";

export function readFlag(): boolean {
  try {
    const q = new URLSearchParams(location.search).get("alerts");
    if (q === "on") localStorage.setItem(FLAG, "on");
    if (q === "off") localStorage.removeItem(FLAG);
    return localStorage.getItem(FLAG) === "on";
  } catch {
    return false;
  }
}

// ---- the keyword a deal suggests

const WORD = /[A-Za-z0-9][A-Za-z0-9'&+.-]*/g;

/** The prefill for "Tell me when one lands": the brand, plus a model word (one with a digit, like "V15") when
 * `model` is set. Without a brand, the first two title words. Always editable in the sheet. */
export function suggestKeyword(title: string, brand: string | null | undefined, model = false): string {
  const words = title.match(WORD) ?? [];
  const b = (brand ?? "").trim();
  if (!b) return words.slice(0, 2).join(" ").toLowerCase();
  const inBrand = new Set((b.match(WORD) ?? []).map((w) => w.toLowerCase()));
  const m = model ? words.slice(0, 8).find((w) => /\d/.test(w) && /[a-z]/i.test(w) && w.length <= 12 && !inBrand.has(w.toLowerCase())) : undefined;
  return (m ? `${b} ${m}` : b).toLowerCase().slice(0, 40);
}

/** "Nov 14" in the visitor's locale. */
export function day(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
}
