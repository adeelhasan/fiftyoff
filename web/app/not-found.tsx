import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Not found" };

// REPORT 14: a styled 404. The export writes it as 404.html, which FastAPI's static mount serves for unknown paths.
export default function NotFound() {
  return (
    <section style={{ gap: 20, paddingTop: 24, paddingBottom: 48 }}>
      <div className="mono mono-13 ink2">404</div>
      <h1 className="page-title">Nothing on this shelf</h1>
      <p style={{ fontSize: 18, maxWidth: 560 }}>
        We couldn&apos;t find that page. It may have moved, or the link is mistyped.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        <Link className="btn btn-ink" href="/">
          Today
        </Link>
        <Link className="btn btn-outline" style={{ height: 48 }} href="/deals/">
          All deals
        </Link>
      </div>
    </section>
  );
}
