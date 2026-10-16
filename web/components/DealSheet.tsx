"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Deal } from "@/lib/types";
import { dealLink } from "@/lib/share";
import { EVENT, type Open } from "@/lib/sheet";
import { DealView } from "./pages/DealPage";

// D71: a card opens its deal in a sheet over the page, so the list underneath (scroll, loaded pages, filters) stays
// put. The address bar still shows /deal/{slug}/ (share, copy and a refresh work), and back closes the sheet. The
// entry is a native pushState, which Next keeps in step with its router (no reload); our part of the state is
// `foDeal`. Cmd/ctrl/shift/middle clicks are left alone, so a card still opens the full page in a new tab.

export function DealSheet() {
  const [open, setOpen] = useState<Open | null>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const back = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const title = useRef("");

  useEffect(() => {
    (window as { foSheet?: boolean }).foSheet = true;
    const onOpen = (e: Event) => {
      const o = (e as CustomEvent<Open>).detail;
      if (!history.state?.foDeal) {
        opener.current = document.activeElement; // the first deal: remember where focus and the title were
        title.current = document.title;
      }
      history.pushState({ foDeal: o }, "", dealLink({ slug: o.slug } as Deal, o.src));
      setOpen(o);
    };
    const onPop = (e: PopStateEvent) => setOpen(e.state?.foDeal ?? null);
    window.addEventListener(EVENT, onOpen);
    window.addEventListener("popstate", onPop);
    return () => {
      (window as { foSheet?: boolean }).foSheet = false;
      window.removeEventListener(EVENT, onOpen);
      window.removeEventListener("popstate", onPop);
    };
  }, []);

  const close = useCallback(() => history.back(), []); // popstate then clears `open`

  useEffect(() => {
    if (!open) {
      if (title.current) document.title = title.current;
      (opener.current as HTMLElement | null)?.focus?.({ preventScroll: true });
      opener.current = null;
      return;
    }
    const root = document.documentElement;
    const was = root.style.overflow;
    root.style.overflow = "hidden"; // the page underneath keeps its scroll position
    back.current?.scrollTo(0, 0); // a related deal opens at its top
    closeBtn.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => {
      root.style.overflow = was;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  if (!open) return null;
  return (
    <div className="dsheet-back" ref={back} onClick={close}>
      <div className="dsheet" role="dialog" aria-modal="true" aria-label="Deal" onClick={(e) => e.stopPropagation()}>
        <div className="dsheet-top">
          <button ref={closeBtn} className="btn btn-outline dsheet-close" onClick={close}>
            <span aria-hidden>←</span> Back
          </button>
        </div>
        {/* a new key per deal: related cards open in the same sheet with fresh state */}
        <DealView key={open.slug} slug={open.slug} src={open.src} />
      </div>
    </div>
  );
}
