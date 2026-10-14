"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { arm, type Arm } from "@/lib/ab";
import { api, countView } from "@/lib/api";
import { ago, count, freshness, minutesSince, money, OUT, outLink, shelfName } from "@/lib/format";
import { useApi, useNow, useShelves } from "@/lib/hooks";
import { visitSince } from "@/lib/lastLook";
import type { Deal, Shelf } from "@/lib/types";
import { DealCard, GoneMini, Grade, PctStamp, Photo, SkeletonGrid } from "../DealCard";
import { Empty, LoadError } from "../States";
import { Usual } from "../Usual";
import { WatchButton } from "../Watch";

export default function Today() {
  const { data, error, loading, retry } = useApi(api.today, "today");
  const shelves = useShelves();
  const now = useNow();
  const [ab, setAb] = useState<Arm | "">("");
  const [since, setSince] = useState<string | null>(null);
  useEffect(() => {
    const v = arm();
    setAb(v);
    setSince(visitSince());
    countView("today", v);
  }, []);
  // D56: shelves with a card new since this visitor's last look come first (stable otherwise)
  const rows = useMemo(() => {
    const list = data?.shelves ?? [];
    if (!since) return list;
    const fresh = (s: (typeof list)[number]) => s.deals.some((d) => (d.landed_at ?? "") > since);
    return [...list.filter(fresh), ...list.filter((s) => !fresh(s))];
  }, [data, since]);

  if (!data && error) return <LoadError retry={retry} />;
  if (!data) return <TodaySkeleton />;

  const lastMin = minutesSince(data.last_landed_at, now || undefined);
  const [feature, ...rest] = data.just_in;
  const label = (id: string) => shelfName(id, shelves);

  return (
    <>
      {error && !loading ? <LoadError retry={retry} kept /> : null}
      <section style={{ gap: 18 }}>
        <Tagline arm={ab} />
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

      {data.featured?.length > 0 && (
        <section>
          <div className="head">
            <h2 className="big">Worth a look</h2>
            <span className="mono mono-13 ink2">BRANDS YOU KNOW · 50–75% OFF · SEEN IN THE LAST 12 H</span>
          </div>
          <div className="grid today-row" role="list">
            {data.featured.map((d) => (
              <DealCard key={d.id} d={d} shelfLabel={label(d.shelf)} now={now} source="featured" />
            ))}
          </div>
        </section>
      )}

      <section>
        <div className="head">
          <h2 className="big">Just in</h2>
          {now > 0 && lastMin !== null && <span className="mono mono-13 ink2">LAST ONE LANDED {ago(lastMin).toUpperCase()}</span>}
          <span className="end">
            <Link className="linkbtn" href="/deals/">
              See all deals
            </Link>
          </span>
        </div>
        {feature ? (
          <div className="justin">
            <Feature d={feature} shelf={label(feature.shelf)} now={now} />
            <div className="jl">
              {rest.slice(0, 4).map((d) => (
                <JustInRow key={d.id} d={d} shelf={label(d.shelf)} now={now} />
              ))}
            </div>
          </div>
        ) : (
          <Empty>Nothing has landed for a while. Most shelves get a few new units a week.</Empty>
        )}
      </section>

      {rows.map((s, i) => (
        <ShelfRow key={s.id} shelf={s} deals={s.deals} now={now} phoneHidden={i >= PHONE_ROWS} />
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
              <GoneMini key={g.id} g={g} now={now} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function Feature({ d, shelf, now }: { d: Deal; shelf: string; now: number }) {
  const when = ago(minutesSince(d.landed_at, now || undefined));
  return (
    <a className="feature" href={outLink(d)} {...OUT}>
      <div className="photo pad12">
        <Photo src={d.image} alt="" eager />
        <PctStamp pct={d.pct_off} large muted={d.condition === "Acceptable"} />
      </div>
      <div className="info">
        {now > 0 && when && <span className="mono good">{when.toUpperCase()}</span>}
        <span className="mono ink2">{shelf}</span>
        <div className="title">{d.title}</div>
        <span className="price tnum">
          {d.from && <span style={{ fontSize: 17, fontWeight: 400 }}>from </span>}
          {money(d.price)}
        </span>
        <Usual d={d} />
        <Grade condition={d.condition} large />
        <span className="foot">
          {d.units > 1 ? `${d.units} available.` : "One unit."} Sold and shipped by Amazon, with its normal returns.
        </span>
      </div>
    </a>
  );
}

function JustInRow({ d, shelf, now }: { d: Deal; shelf: string; now: number }) {
  const when = ago(minutesSince(d.landed_at, now || undefined));
  const f = freshness(d, now || undefined);
  return (
    <a className="jrow" href={outLink(d)} {...OUT}>
      <div className="thumb">
        <Photo src={d.image} alt="" />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
        <div className="t">
          <b className="tnum">
            {d.from ? "from " : ""}
            {money(d.price)}
          </b>
          {d.title}
        </div>
        <span className="sub">
          {d.condition} · {shelf}
        </span>
      </div>
      <div className="right">
        <span className="pct tnum">{d.pct_off}%</span>
        {now > 0 && when && <span className="when" style={f.isNew ? undefined : { color: "var(--fo-ink-2)" }}>{when}</span>}
      </div>
    </a>
  );
}

// trust-first §1.3: phones get the first few shelf rows; the rest are in "Every shelf" below
const PHONE_ROWS = 5;

export function ShelfRow({ shelf, deals, now, phoneHidden }: { shelf: Shelf; deals: Deal[]; now: number; phoneHidden?: boolean }) {
  const href = `/shelf/${encodeURIComponent(shelf.id)}/`;
  return (
    <section className={phoneHidden ? "phone-hide" : undefined}>
      <div className="head center">
        <h2>
          <Link href={href} style={{ color: "inherit", textDecoration: "none" }}>
            {shelf.name}
          </Link>
        </h2>
        <span className="mono mono-13 ink2 tnum">
          {count(shelf.live)} LIVE{shelf.per_week ? ` · ~${count(shelf.per_week)} A WEEK` : ""}
        </span>
        <span className="end">
          <WatchButton shelf={shelf.name} />
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

// trust-first §1.1 (A/B, D56): "a" is the new tagline, "b" the line the site had before. "" (no storage) shows "a".
function Tagline({ arm }: { arm: Arm | "" }) {
  if (arm === "b") return <p style={{ fontSize: 22, lineHeight: 1.4 }}>Things worth having, at half off or better.</p>;
  return (
    <div className="tagline">
      <h1 className="lead">Deals like no other.</h1>
      <p className="sub">
        Open-box and used, sold and shipped by Amazon. Half off or better, and usually just one of each.
      </p>
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
          <h2 className="big">Just in</h2>
          <span className="mono mono-13 ink2">CHECKING THE SHELVES</span>
        </div>
        <SkeletonGrid n={5} />
      </section>
    </>
  );
}
