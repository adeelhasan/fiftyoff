"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

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
  { href: "/gone/", label: "Recently gone" },
];

// The design's header search, "Sign in" and watch status are left out until search and accounts exist (web.md).
export function Header() {
  const path = usePathname();
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
