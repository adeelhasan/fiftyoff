"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

export function Wordmark({ framed }: { framed?: boolean }) {
  return (
    <Link href="/" className={`wordmark${framed ? " framed" : ""}`} aria-label="fiftyOff, Today">
      <span>fifty</span>
      <span className="off">Off</span>
    </Link>
  );
}

const NAV = [
  { href: "/", label: "Today" },
  { href: "/deals/", label: "All deals" },
  { href: "/sizes/", label: "By size" },
  { href: "/gone/", label: "Recently gone" },
];

// "Sign in" and watch status are left out until accounts exist (web.md). Search: trust-first §4.1.
export function Header() {
  const path = usePathname();
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
