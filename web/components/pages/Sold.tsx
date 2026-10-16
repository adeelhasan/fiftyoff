"use client";
import Link from "next/link";
import { api } from "@/lib/api";
import { money, shelfName, span } from "@/lib/format";
import { useApi, useIdFromUrl, useNow, useShelves } from "@/lib/hooks";
import { DealCard, Photo } from "../DealCard";
import { Empty, LoadError } from "../States";
import { suggestKeyword } from "@/lib/alerts";
import { AlertLink } from "../Alert";

// Where /d/{slug} sends a click whose unit is no longer live (Watch Flow step 7).
export default function Sold() {
  const id = useIdFromUrl("sold");
  const { data, error, retry } = useApi(
    () => (id ? api.product(id) : Promise.reject(Object.assign(new Error("no id"), { status: 404 }))),
    id ?? "",
  );
  const shelves = useShelves();
  const now = useNow();

  if (id === undefined || (!data && !error)) {
    return (
      <section aria-busy="true">
        <div className="sold">
          <div className="photo skel" />
          <div className="info">
            <div className="skel-line" />
            <div className="skel-line" style={{ width: "60%" }} />
          </div>
        </div>
      </section>
    );
  }
  if (!data) {
    if ((error as { status?: number })?.status === 404) return <Gone404 />;
    return <LoadError retry={retry} />;
  }

  // Still live (the redirect raced a new sighting): show it as a normal card.
  if (data.deal) {
    const d = data.deal;
    return (
      <section style={{ gap: 20 }}>
        <div className="head">
          <h1 className="page-title">Still there</h1>
        </div>
        <p style={{ fontSize: 18 }}>This one is still listed on Amazon.</p>
        <div className="grid three" role="list" style={{ maxWidth: 260, gridTemplateColumns: "minmax(0,1fr)" }}>
          <DealCard d={d} shelfLabel={shelfName(d.shelf, shelves)} now={now} />
        </div>
      </section>
    );
  }

  const g = data.gone;
  if (!g) return <Gone404 />;
  const shelf = shelfName(g.shelf, shelves);
  // How long it was up comes from the unit's sightings (up_for_*), not landed_at: we may have priced it long after
  // it was listed. When we found it already listed, we only know a lower bound.
  const up = g.up_for_min !== null && !g.up_for_is_lower_bound ? span(g.up_for_min) : null;
  return (
    <section style={{ gap: 20 }}>
      <div className="sold">
        <div className="photo">
          <Photo src={g.image} alt={g.title} />
          <div className="gone-stamp lg" aria-hidden>
            GONE
          </div>
        </div>
        <div className="info">
          <h1 className="h">{up ? `This one went ${up} after it was listed` : "This one has gone"}</h1>
          <div className="p">
            {g.title}, last price <span className="tnum">{money(g.last_price)}</span>, {g.pct_off}% off.
          </div>
          <div style={{ marginTop: 4 }}>
            <AlertLink keyword={suggestKeyword(g.title, g.brand)} source="sold" className="btn btn-stamp">
              Tell me when the next one lands
            </AlertLink>
          </div>
        </div>
      </div>
      {data.same_shelf.length > 0 && (
        <>
          <div className="head" style={{ maxWidth: 760 }}>
            <h2 className="sub-head">Still on {shelf}</h2>
            <span className="end">
              <Link className="linkbtn" href={`/shelf/${encodeURIComponent(g.shelf)}/`}>
                See the shelf
              </Link>
            </span>
          </div>
          <div className="grid three" role="list">
            {data.same_shelf.slice(0, 3).map((d) => (
              <DealCard key={d.id} d={d} now={now} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Gone404() {
  return (
    <Empty title="We can't find that deal" action={<Link className="btn btn-ink" href="/deals/">See all deals</Link>}>
      It isn&apos;t one we&apos;ve listed in the last week, or the link is mistyped. Deals that went more than 7 days ago
      drop off.
    </Empty>
  );
}
