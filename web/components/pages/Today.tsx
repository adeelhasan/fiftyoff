"use client";
import Link from "next/link";
import { api } from "@/lib/api";
import { ago, count, freshness, minutesSince, money, outLink, shelfName } from "@/lib/format";
import { useApi, useNow, useShelves } from "@/lib/hooks";
import type { Deal, Shelf } from "@/lib/types";
import { DealCard, GoneMini, Grade, PctStamp, Photo, SkeletonGrid } from "../DealCard";
import { Empty, LoadError } from "../States";
import { WatchButton } from "../Watch";

export default function Today() {
  const { data, error, loading, retry } = useApi(api.today, "today");
  const shelves = useShelves();
  const now = useNow();

  if (!data && error) return <LoadError retry={retry} />;
  if (!data) return <TodaySkeleton />;

  const lastMin = minutesSince(data.last_landed_at, now || undefined);
  const [feature, ...rest] = data.just_in;
  const label = (id: string) => shelfName(id, shelves);

  return (
    <>
      {error && !loading ? <LoadError retry={retry} kept /> : null}
      <section style={{ gap: 18 }}>
        <p style={{ fontSize: 22, lineHeight: 1.4 }}>Things worth having, at half off or better.</p>
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

      {data.shelves.map((s) => (
        <ShelfRow key={s.id} shelf={s} deals={s.deals} now={now} />
      ))}

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
    <a className="feature" href={outLink(d)}>
      <div className="photo pad12">
        <Photo src={d.image} alt={d.title} eager />
        <PctStamp pct={d.pct_off} large muted={d.condition === "Acceptable"} />
      </div>
      <div className="info">
        {now > 0 && when && <span className="mono good">{when.toUpperCase()}</span>}
        <span className="mono ink2">{shelf}</span>
        <div className="title">{d.title}</div>
        <span className="price tnum">
          {d.from && <span style={{ fontSize: 17, fontWeight: 400, marginRight: 6 }}>from</span>}
          {money(d.price)}
        </span>
        <Grade condition={d.condition} large />
        <span className="foot">{d.units > 1 ? `${d.units} units.` : "One unit."} Usually sells within a day.</span>
      </div>
    </a>
  );
}

function JustInRow({ d, shelf, now }: { d: Deal; shelf: string; now: number }) {
  const when = ago(minutesSince(d.landed_at, now || undefined));
  const f = freshness(d, now || undefined);
  return (
    <a className="jrow" href={outLink(d)}>
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
          {count(shelf.live)} LIVE{shelf.per_week ? ` · ~${count(shelf.per_week)} A WEEK` : ""}
        </span>
        <span className="end">
          <WatchButton shelf={shelf.name} />
          <Link className="linkbtn" href={href}>
            See all {count(shelf.live)}
          </Link>
        </span>
      </div>
      <div className="grid">
        {deals.slice(0, 5).map((d) => (
          <DealCard key={d.id} d={d} now={now} />
        ))}
      </div>
    </section>
  );
}

function TodaySkeleton() {
  return (
    <>
      <section style={{ gap: 18 }}>
        <p style={{ fontSize: 22, lineHeight: 1.4 }}>Things worth having, at half off or better.</p>
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
