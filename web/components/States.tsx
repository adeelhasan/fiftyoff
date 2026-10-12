"use client";
import type { ReactNode } from "react";

/** "Nothing here right now" with the CHECKED stamp (design: Empty and error). */
export function Empty({
  title = "Nothing here right now",
  children,
  action,
}: {
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const t = new Date();
  const when = t
    .toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })
    .replace(",", " ·")
    .toUpperCase();
  return (
    <div className="panel" role="status">
      <div className="checked-stamp">
        CHECKED<small suppressHydrationWarning>{when}</small>
      </div>
      <div className="big">{title}</div>
      {children && <div className="txt">{children}</div>}
      {action}
    </div>
  );
}

/** "COULDN'T LOAD" with "Try again". */
export function LoadError({ retry, kept }: { retry: () => void; kept?: boolean }) {
  return (
    <div className="panel" role="alert">
      <div className="warn-tag">COULDN&apos;T LOAD</div>
      <div className="big">We couldn&apos;t reach the shelves</div>
      <div className="txt">
        Check your connection and try again.{kept ? " The deals you already saw are still listed below." : ""}
      </div>
      <button className="btn btn-ink" onClick={retry}>
        Try again
      </button>
    </div>
  );
}
