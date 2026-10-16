"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { arm, variant, type Arm } from "@/lib/ab";
import { api, countView } from "@/lib/api";
import { count, shelfName } from "@/lib/format";
import { useApi, useNow, useShelves } from "@/lib/hooks";
import { visitSince } from "@/lib/lastLook";
import type { Deal, Shelf } from "@/lib/types";
import { DealCard, GoneMini, SkeletonGrid } from "../DealCard";
import { LoadError } from "../States";
import { GoneAlert } from "../Alert";

export default function Today() {
  const { data, error, loading, retry } = useApi(api.today, "today");
  const shelves = useShelves();
  const now = useNow();
  const [ab, setAb] = useState<Arm | "">("");
  const [since, setSince] = useState<string | null>(null);
  useEffect(() => {
    setAb(arm());
    setSince(visitSince());
    countView("today", variant());
  }, []);
  // D56: shelves with a card new since this visitor's last look come first (dormant: LAST_LOOK is off, today-quality §5)
  const rows = useMemo(() => {
    const list = data?.shelves ?? [];
    if (!since) return list;
    const fresh = (s: (typeof list)[number]) => s.deals.some((d) => (d.landed_at ?? "") > since);
    return [...list.filter(fresh), ...list.filter((s) => !fresh(s))];
  }, [data, since]);

  if (!data && error) return <LoadError retry={retry} />;
  if (!data) return <TodaySkeleton />;

  const label = (id: string) => shelfName(id, shelves);

  return (
    <>
      {error && !loading ? <LoadError retry={retry} kept /> : null}
      <section style={{ gap: 18 }}>
        <Tagline arm={ab} />
        <p className="mono mono-13 ink2 tnum count-line">
          {count(data.count)} DEALS ON {count(data.shelf_count)} SHELVES ·{" "}
          <Link className="linkbtn" href="/deals/">
            See all →
          </Link>
        </p>
        {data.aisles.length > 0 && (
          <nav className="chips-scroll" aria-label="Aisles">
            {data.aisles.map((a) => (
              <Link key={a.id} className="chip aisle" href={`/deals/?aisle=${encodeURIComponent(a.id)}`}>
                {a.name}
                <span className="n tnum">{count(a.count)}</span>
              </Link>
            ))}
          </nav>
        )}
      </section>

      {/* D63: the best-rated deals lead the page, as a plain row of cards (D64's layout test, ended 10-15) */}
      {data.featured?.length > 0 && (
        <section>
          <div className="head">
            <h2 className="big">Worth a look</h2>
            <span className="mono mono-13 ink2">BRANDS YOU KNOW · 50–75% OFF · SEEN IN THE LAST 24 H</span>
          </div>
          <p className="ink2" style={{ fontSize: 16, marginTop: -8 }}>
            Sold and shipped by Amazon, with its normal returns.
          </p>
          <div className="grid today-row" role="list">
            {data.featured.map((d) => (
              <DealCard key={d.id} d={d} shelfLabel={label(d.shelf)} now={now} source="featured" />
            ))}
          </div>
        </section>
      )}

      {rows.map((s) => (
        <ShelfRow key={s.id} shelf={s} deals={s.deals} now={now} />
      ))}

      {shelves && shelves.size > 0 && <ShelfIndex shelves={shelves} />}

      {data.gone.length > 0 && (
        <section>
          <div className="head">
            <h2>Recently gone</h2>
            <span className="ink2" style={{ fontSize: 16 }}>
              Most sell within a day or two.
            </span>
            <span className="end">
              <Link className="linkbtn" href="/gone/">
                See what went
              </Link>
            </span>
          </div>
          <div className="grid minis">
            {data.gone.slice(0, 6).map((g) => (
              <GoneAlert key={g.id} g={g} now={now} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}

// today-quality §8: every front shelf gets a row, on phones too. Recently gone closes the page (the user, 10-14)

export function ShelfRow({ shelf, deals, now }: { shelf: Shelf; deals: Deal[]; now: number }) {
  const href = `/shelf/${encodeURIComponent(shelf.id)}/`;
  return (
    <section>
      <div className="head center">
        <h2>
          <Link href={href} style={{ color: "inherit", textDecoration: "none" }}>
            {shelf.name}
          </Link>
        </h2>
        <span className="mono mono-13 ink2 tnum">
          {count(shelf.live)} LIVE
        </span>
        <span className="end">
          <Link className="linkbtn" href={href}>
            See all {count(shelf.live)}
          </Link>
        </span>
      </div>
      <div className="grid today-row" role="list">
        {deals.slice(0, 5).map((d) => (
          <DealCard key={d.id} d={d} now={now} />
        ))}
      </div>
    </section>
  );
}

// trust-first §1.1 (A/B, D56; arm a's line from today-quality §7): "a" is the new tagline, "b" the line the site had before. "" (no storage) shows "a".
function Tagline({ arm }: { arm: Arm | "" }) {
  if (arm === "b") return <p style={{ fontSize: 22, lineHeight: 1.4 }}>Things worth having, at half off or better.</p>;
  return (
    <div className="tagline">
      <h1 className="lead">Deals like no other.</h1>
      <p className="sub">Amazon Resale, open-box and used, at half off or better. Sold and shipped by Amazon.</p>
    </div>
  );
}

/** Every public shelf, by aisle, so none is out of reach from Today (the user, 10-12). */
function ShelfIndex({ shelves }: { shelves: Map<string, Shelf> }) {
  const byAisle = new Map<string, { name: string; shelves: Shelf[] }>();
  for (const s of shelves.values()) {
    if (s.id === "just-in" || s.live === 0) continue;
    const a = byAisle.get(s.aisle) ?? { name: s.aisle_name, shelves: [] };
    a.shelves.push(s);
    byAisle.set(s.aisle, a);
  }
  const aisles = [...byAisle.values()].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <section>
      <div className="head">
        <h2>Every shelf</h2>
        <span className="mono mono-13 ink2">LIVE NOW, NOT COUNTING ACCEPTABLE</span>
        <span className="end">
          <Link className="linkbtn" href="/almost/">
            Almost half off →
          </Link>
        </span>
      </div>
      <nav className="shelf-index" aria-label="Every shelf">
        {aisles.map((a) => (
          <details className="aisle" key={a.name}>
            <summary>
              {a.name}
              <span className="n tnum">
                {a.shelves.length} {a.shelves.length === 1 ? "shelf" : "shelves"}
              </span>
            </summary>
            {a.shelves
              .sort((x, y) => x.name.localeCompare(y.name))
              .map((s) => (
                <Link key={s.id} href={`/shelf/${encodeURIComponent(s.id)}/`}>
                  {s.name}
                  <span className="n tnum">{count(s.live)}</span>
                </Link>
              ))}
          </details>
        ))}
      </nav>
    </section>
  );
}

function TodaySkeleton() {
  return (
    <>
      <section style={{ gap: 18 }}>
        <div className="tagline" aria-hidden>
          <div className="skel-line" style={{ height: 36, width: "50%" }} />
        </div>
        <div className="chips-scroll" aria-hidden>
          {Array.from({ length: 7 }, (_, i) => (
            <span key={i} className="chip aisle" style={{ width: 110 }} />
          ))}
        </div>
      </section>
      <section aria-busy="true">
        <div className="head">
          <h2 className="big">Worth a look</h2>
          <span className="mono mono-13 ink2">CHECKING THE SHELVES</span>
        </div>
        <SkeletonGrid n={5} />
      </section>
    </>
  );
}
