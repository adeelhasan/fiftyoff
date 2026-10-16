"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { useSession } from "./Alert";

export function Wordmark({ framed }: { framed?: boolean }) {
  return (
    <Link href="/" className={`wordmark${framed ? " framed" : ""}`} aria-label="fiftyOff, Today">
      <span>fifty</span>
      <span className="off">Off</span>
    </Link>
  );
}

// D70: no "Today" item: it's the home page, and the wordmark links there
const NAV = [
  { href: "/deals/", label: "All deals" },
  { href: "/sizes/", label: "Clothes & Shoes" },
  { href: "/gone/", label: "Recently gone" },
];

// Search: trust-first §4.1. "My alerts · N" once signed in (alerts-beta.md); no "Sign in" for visitors.
export function Header() {
  const path = usePathname();
  const { me } = useSession();
  const watching = me?.alerts.filter((a) => a.state === "watching").length ?? 0;
  const [q, setQ] = useState("");
  useEffect(() => {
    if (path.startsWith("/deals")) setQ(new URLSearchParams(location.search).get("q") ?? "");
  }, [path]);
  const go = (e: FormEvent) => {
    e.preventDefault();
    const t = q.trim();
    // a full navigation, so All deals reads the new query from the URL whichever page we're on
    location.assign(t ? `/deals/?q=${encodeURIComponent(t)}` : "/deals/");
  };
  return (
    <header className="header">
      <div className="wrap">
        <Wordmark framed />
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={path === n.href || path === n.href.slice(0, -1) ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
          {me && (
            <Link href="/my-alerts/" aria-current={path.startsWith("/my-alerts") ? "page" : undefined}>
              My alerts · {watching}
            </Link>
          )}
        </nav>
        <form className="search" role="search" onSubmit={go}>
          <input
            type="search"
            aria-label="Search deals"
            placeholder="Search: brand or product"
            value={q}
            maxLength={80}
            onChange={(e) => setQ(e.target.value)}
          />
          <button type="submit" aria-label="Search">
            <span aria-hidden>⌕</span>
          </button>
        </form>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap">
        <Link href="/" className="wordmark">
          <span>fifty</span>
          <span className="off">Off</span>
        </Link>
        <span>
          Amazon Resale at about half price · Prices from{" "}
          <a className="keepa" href="https://keepa.com" rel="noopener">
            Data by Keepa
          </a>{" "}
          · No affiliate links
        </span>
        <span className="links">
          <Link href="/how-we-price/">How we price</Link>
          <Link href="/privacy/">Privacy</Link>
          <Link href="/contact/">Contact</Link>
        </span>
        <span style={{ whiteSpace: "nowrap" }}>© 2026 fiftyOff</span>
      </div>
    </footer>
  );
}
