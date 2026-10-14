"use client";
// Watch buttons, for now (web.md): they open the design's email sheet, and submitting shows "Alerts start soon"
// and sends nothing. The address isn't stored or sent anywhere. Alerts and accounts are the next handoff.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

export const SOON = "Alerts start soon. We'll let you know here.";

const Ctx = createContext<(shelfName: string) => void>(() => {});

export function useWatch() {
  return useContext(Ctx);
}

export function WatchProvider({ children }: { children: ReactNode }) {
  const [shelf, setShelf] = useState<string | null>(null);
  const open = useCallback((name: string) => setShelf(name), []);
  return (
    <Ctx.Provider value={open}>
      {children}
      {shelf !== null && <WatchSheet shelf={shelf} onClose={() => setShelf(null)} />}
    </Ctx.Provider>
  );
}

/** The modal sheet. Closes on the scrim, on Escape, and on "Done". */
export function Sheet({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); // callers pass inline functions; the mount effect must not re-run on each render
  close.current = onClose;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, button:not(.x)")?.focus();
    const key = (e: KeyboardEvent) => e.key === "Escape" && close.current();
    document.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = overflow;
      prev?.focus();
    };
  }, []);
  return (
    <div className="scrim" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={label} ref={ref} onClick={(e) => e.stopPropagation()}>
        <button className="x" onClick={onClose} aria-label="Close">
          ×
        </button>
        {children}
      </div>
    </div>
  );
}

function WatchSheet({ shelf, onClose }: { shelf: string; onClose: () => void }) {
  const [done, setDone] = useState(false);
  return (
    <Sheet label={`Watch ${shelf}`} onClose={onClose}>
      <div className="name">{shelf}</div>
      {done ? (
        <>
          <div className="soon" role="status">
            {SOON}
          </div>
          <button className="btn btn-ink" onClick={onClose}>
            Done
          </button>
        </>
      ) : (
        <>
          <div className="lead">
            Soon you&apos;ll be able to get an email when one lands on this shelf at about half its usual price. Only Amazon
            Resale units, checked against what they usually sell for.
          </div>
          <EmailForm onDone={() => setDone(true)} />
          <div className="fine">Free: 1 shelf. No password, and you can stop any email with one tap.</div>
        </>
      )}
    </Sheet>
  );
}

/** Email field + "Start watching". Sends nothing for now. */
export function EmailForm({ onDone }: { onDone: () => void }) {
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onDone();
  };
  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <label className="field">
        Email address
        <input type="email" required autoComplete="email" placeholder="you@example.com" />
      </label>
      <button className="btn btn-stamp" type="submit">
        Start watching
      </button>
    </form>
  );
}

/** The outline "Watch this shelf" button on shelf rows. */
export function WatchButton({ shelf }: { shelf: string }) {
  const open = useWatch();
  return (
    <button className="btn-outline" onClick={() => open(shelf)}>
      Watch this shelf
    </button>
  );
}

/** The shelf page's panel: "Tell me when one lands". */
export function WatchPanel({ shelf }: { shelf: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="watch-panel">
      <div className="h">Tell me when one lands</div>
      {done ? (
        <div className="soon" role="status">
          {SOON}
        </div>
      ) : (
        <>
          <div className="p">Most units here sell within a day. Soon you&apos;ll be able to get an email as soon as a new one on {shelf} is listed.</div>
          <EmailForm onDone={() => setDone(true)} />
        </>
      )}
      <div className="fine">Free: 1 shelf. No password.</div>
    </div>
  );
}
