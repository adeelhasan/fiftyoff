"use client";
// Keyword alerts (alerts-beta.md; the design's Watch flow with a keyword where it says a shelf). The provider loads
// who's signed in once per page load and owns the one alert sheet; entry points call open(keyword, source).
// Entry points show only when alerts are open to everyone (ALERTS_OPEN) or this browser visited ?alerts=on.
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";
import { alertsApi, loadSession, readFlag, setMe, snapshot, subscribe, suggestKeyword, type AlertSource, type Full, type Me } from "@/lib/alerts";
import type { Gone } from "@/lib/types";
import { GoneMini } from "./DealCard";
import { Sheet } from "./Sheet";

type Open = (keyword: string, source: AlertSource) => void;
const Ctx = createContext<{ open: Open; enabled: boolean }>({ open: () => {}, enabled: false });

export function useAlert() {
  return useContext(Ctx);
}

/** The signed-in subscriber (null when signed out) and the alert config, shared by every component. */
export function useSession() {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

export function AlertProvider({ children }: { children: ReactNode }) {
  const [ask, setAsk] = useState<{ keyword: string; source: AlertSource } | null>(null);
  const [flag, setFlag] = useState(false);
  const { config, me } = useSession();
  useEffect(() => {
    setFlag(readFlag());
    void loadSession();
  }, []);
  const open = useCallback<Open>((keyword, source) => setAsk({ keyword, source }), []);
  const enabled = flag || !!config?.open || !!me;
  return (
    <Ctx.Provider value={{ open, enabled }}>
      {children}
      {ask && <AlertSheet {...ask} onClose={() => setAsk(null)} />}
    </Ctx.Provider>
  );
}

type Step = { at: "form" } | { at: "inbox"; email: string } | { at: "full"; full: Full } | { at: "done"; me: Me };

function AlertSheet({ keyword, source, onClose }: { keyword: string; source: AlertSource; onClose: () => void }) {
  const { me, config } = useSession();
  const [kw, setKw] = useState(keyword);
  const [email, setEmail] = useState("");
  const [step, setStep] = useState<Step>({ at: "form" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const delay = config?.delay_minutes ?? 30;

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setErr("");
    if (me) {
      const r = await alertsApi.add(kw, source);
      if (r.data) {
        setMe(r.data);
        setStep({ at: "done", me: r.data });
      } else if (r.full) setStep({ at: "full", full: r.full });
      else setErr(r.error === "keyword" ? "Use 2 to 40 letters or numbers." : "That didn't work. Try again in a moment.");
    } else {
      const r = await alertsApi.watch(email, kw, source);
      if (r.data) setStep({ at: "inbox", email: email.trim().toLowerCase() });
      else
        setErr(
          r.error === "keyword"
            ? "Use 2 to 40 letters or numbers."
            : r.error === "email"
              ? "That email address doesn't look right."
              : r.status === 429
                ? "Too many tries from here. Try again in an hour."
                : "That didn't work. Try again in a moment.",
        );
    }
    setBusy(false);
  };

  const swap = async (full: Full) => {
    setBusy(true);
    for (const c of full.current) await alertsApi.change(c.id, "stop");
    const r = await alertsApi.add(full.keyword, source);
    setBusy(false);
    if (r.data) {
      setMe(r.data);
      setStep({ at: "done", me: r.data });
    } else setErr("That didn't work. Try again in a moment.");
  };

  if (step.at === "inbox")
    return (
      <Sheet label="Check your inbox" onClose={onClose}>
        <div className="name">Check your inbox</div>
        <div className="lead">
          We sent a link to <b>{step.email}</b>. Tap it to start watching <b>&lsquo;{kw}&rsquo;</b>. It works for 24 hours.
        </div>
        <div className="soon" role="status">
          Waiting for you to confirm
        </div>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <button className="linkbtn" onClick={() => void submit()} disabled={busy}>
            {busy ? "Sending…" : "Send it again"}
          </button>
          <button className="linkbtn" onClick={() => setStep({ at: "form" })}>
            Use a different address
          </button>
        </div>
        <div className="fine">Nothing there? Check spam for an email from deals@alerts.fiftyoff.app.</div>
      </Sheet>
    );

  if (step.at === "full") {
    const cur = step.full.current[0]?.keyword;
    return (
      <Sheet label="Swap your alert" onClose={onClose}>
        <div className="name">You&apos;re already watching &lsquo;{cur}&rsquo;</div>
        <div className="lead">A free alert watches one keyword at a time.</div>
        <button className="btn btn-stamp" onClick={() => void swap(step.full)} disabled={busy}>
          Swap to &lsquo;{step.full.keyword}&rsquo;
        </button>
        <button className="btn btn-outline tall" disabled>
          More keywords · coming soon
        </button>
        <button className="linkbtn" onClick={onClose} style={{ alignSelf: "flex-start" }}>
          Keep &lsquo;{cur}&rsquo;
        </button>
        {err && <p className="form-err">{err}</p>}
      </Sheet>
    );
  }

  if (step.at === "done")
    return (
      <Sheet label="Watching" onClose={onClose}>
        <div className="watching-stamp">WATCHING</div>
        <div className="name">&lsquo;{kw}&rsquo;</div>
        <div className="lead">
          We&apos;ll email <b>{step.me.email}</b> when a deal matching &lsquo;{kw}&rsquo; lands at half off or better.
        </div>
        <Link className="btn btn-ink" href="/my-alerts/" onClick={onClose}>
          My alerts
        </Link>
      </Sheet>
    );

  return (
    <Sheet label="Set an alert" onClose={onClose}>
      <div className="name">Tell me when it lands</div>
      <div className="lead">
        We&apos;ll email you when a deal matching your keyword lands at half off or better: Amazon Resale, sold and shipped by
        Amazon.
      </div>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <label className="field">
          Keyword
          <input value={kw} onChange={(e) => setKw(e.target.value)} required minLength={2} maxLength={40} placeholder="dyson, kate spade, galaxy ring" />
        </label>
        {!me && (
          <label className="field">
            Email address
            <input type="email" required autoComplete="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
        )}
        {err && <p className="form-err">{err}</p>}
        <button className="btn btn-stamp" type="submit" disabled={busy}>
          {busy ? "One moment…" : "Start watching"}
        </button>
      </form>
      <div className="fine">
        Free: 1 keyword. We email you once, about {delay} minutes after a match lands, then you can set it again. No
        password; stop any time. By setting an alert you agree to our <Link href="/privacy/">Privacy policy</Link>.
      </div>
    </Sheet>
  );
}

/** A text button that opens the alert sheet. Renders nothing while alerts are hidden. */
export function AlertLink({ keyword, source, children, className = "linkbtn" }: { keyword: string; source: AlertSource; children: ReactNode; className?: string }) {
  const { open, enabled } = useAlert();
  if (!enabled || !keyword) return null;
  return (
    <button className={className} onClick={() => open(keyword, source)} style={{ whiteSpace: "normal", textAlign: "left" }}>
      {children}
    </button>
  );
}

/** Search results: "Alert me when 'q' lands at half off". Stronger (a panel) when nothing live matches. */
export function AlertPrompt({ q, strong }: { q: string; strong?: boolean }) {
  const { open, enabled } = useAlert();
  if (!enabled || q.trim().length < 2) return null;
  return (
    <div className={`alert-prompt${strong ? " strong" : ""}`}>
      <span>
        {strong ? "Most deals here sell within a day. " : ""}Want to know when &lsquo;{q.trim()}&rsquo; lands at half off?
      </span>
      <button className={strong ? "btn btn-stamp" : "btn-outline"} onClick={() => open(q.trim(), "search")}>
        Alert me
      </button>
    </div>
  );
}

/** A gone mini with "Tell me when one lands" under it (Today's strip, a shelf's recently gone, search). */
export function GoneAlert({ g, now }: { g: Gone; now: number }) {
  return (
    <div className="gone-item">
      <GoneMini g={g} now={now} />
      <AlertLink keyword={suggestKeyword(g.title, g.brand)} source="gone">
        Tell me when one lands
      </AlertLink>
    </div>
  );
}
