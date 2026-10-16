"use client";
import { useEffect, useRef, type ReactNode } from "react";

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
