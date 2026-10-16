"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { variant } from "@/lib/ab";
import { api, countOpen, countView } from "@/lib/api";
import { ago, minutesSince, money, OUT, outLink, shelfName } from "@/lib/format";
import { useApi, useIdFromUrl, useNow, useShelves } from "@/lib/hooks";
import { cleanText, copy, share } from "@/lib/share";
import type { Deal } from "@/lib/types";
import { DealCard, Grade, PctStamp, Photo } from "../DealCard";
import { Empty, LoadError } from "../States";
import { Usual } from "../Usual";
import { suggestKeyword } from "@/lib/alerts";
import { AlertLink } from "../Alert";

// trust-first §4.2: where a shared link lands. Live: the deal, a way to Amazon, share and copy. Gone: the last price
// (D27), a keyword alert (alerts-beta.md) and live alternatives. D71: the same view opens in a sheet over a list (DealSheet), so a
// visitor keeps their place; this page is what a shared link, a refresh or a new tab shows.
export default function DealPage() {
  const slug = useIdFromUrl("deal");
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => setSrc(new URLSearchParams(location.search).get("s") || "deal"), []);
  if (slug === undefined || src === null) return <DealSkeleton />;
  return <DealView slug={slug} src={src} />;
}

function DealSkeleton() {
  return (
    <section aria-busy="true">
      <div className="deal-page">
        <div className="photo skel" />
        <div className="info">
          <div className="skel-line" />
          <div className="skel-line" style={{ width: "60%" }} />
        </div>
      </div>
    </section>
  );
}

/** One deal: the page body, shared by the full page and the sheet. `src` is the surface the card was on (a card's
 * s=); the Amazon button passes it on, so a click row says where the deal was found. Logs one open per mount. */
export function DealView({ slug, src }: { slug: string | null; src: string }) {
  const asin = slug ? slug.slice(0, 10).toUpperCase() : null;
  const { data, error, retry } = useApi(
    () => (asin ? api.product(asin) : Promise.reject(Object.assign(new Error("no id"), { status: 404 }))),
    asin ?? "",
  );
  const shelves = useShelves();
  const now = useNow();
  const [note, setNote] = useState("");

  useEffect(() => {
    countView(src === "share" ? "share" : "deal", variant());
    if (asin) countOpen(asin, src, variant());
  }, [asin, src]);
  const d: Deal | null = data?.deal ?? data?.gone ?? null;
  useEffect(() => {
    if (d) document.title = `${d.pct_off}% off: ${d.title} · fiftyOff`;
  }, [d]);

  if (!data && !error) return <DealSkeleton />;
  if (!data || !d) {
    if (!data && (error as { status?: number })?.status !== 404) return <LoadError retry={retry} />;
    return (
      <Empty title="We can't find that deal" action={<Link className="btn btn-ink" href="/deals/">See all deals</Link>}>
        It isn&apos;t one we&apos;ve listed in the last week, or the link is mistyped.
      </Empty>
    );
  }

  const gone = !data.deal;
  const shelf = shelfName(d.shelf, shelves);
  const seen = ago(minutesSince(d.confirmed_at, now || undefined));
  const flash = (t: string) => {
    setNote(t);
    setTimeout(() => setNote(""), 2500);
  };
  return (
    <section style={{ gap: 28 }}>
      <div className="mono mono-13 ink2">
        <Link href={`/shelf/${encodeURIComponent(d.shelf)}/`} style={{ color: "inherit" }}>
          {shelf.toUpperCase()}
        </Link>
      </div>
      <div className={`deal-page${gone ? " is-gone" : ""}`}>
        <div className="photo pad12">
          <Photo src={d.image} alt="" eager />
          {gone ? (
            <div className="gone-stamp lg" aria-hidden>
              GONE
            </div>
          ) : (
            <PctStamp pct={d.pct_off} large muted={d.condition === "Acceptable"} />
          )}
        </div>
        <div className="info">
          <h1 className="title">{d.title}</h1>
          <div className="price tnum">
            {gone ? <span className="was-label">Last price </span> : null}
            {money(gone && data.gone ? data.gone.last_price : d.price)}
            <span className="pct"> · {d.pct_off}% off</span>
          </div>
          <Usual d={d} />
          {!gone && (d.variants > 1 || d.units > 1) && (
            // the card only says "N VERSIONS" (a heads-up that it's grouped); the counts and "from" are explained here
            <p className="p">
              {d.variants > 1 ? `Comes in ${d.variants} ${d.fit ? "sizes" : "versions"}; the price is the lowest. ` : ""}
              {d.units > 1 ? `${d.units} units listed.` : ""}
            </p>
          )}
          <div>
            <Grade condition={d.condition} large />{" "}
            <Link className="linkbtn" href="/how-we-price/#conditions">
              What the grades mean
            </Link>
          </div>
          {gone ? (
            <>
              <p className="p">
                This one has gone{now > 0 && data.gone ? ` (${ago(minutesSince(data.gone.gone_at, now))})` : ""}. Units on
                Resale are usually one of a kind.
              </p>
              <div>
                <AlertLink keyword={suggestKeyword(d.title, d.brand, true)} source="deal" className="btn btn-stamp">
                  Tell me when the next one lands
                </AlertLink>
              </div>
            </>
          ) : (
            <>
              {now > 0 && seen && <p className="p">Last checked {seen}. It may have sold since.</p>}
              <div className="actions">
                <a className="btn btn-stamp" href={outLink(d, src)} {...OUT}>
                  On Amazon <span aria-hidden>↗</span>
                </a>
                <button className="btn btn-outline tall" onClick={async () => flash(labels[await share(d)])}>
                  Share
                </button>
                <button
                  className="btn btn-outline tall"
                  onClick={async () => flash((await copy(cleanText(d))) ? "Amazon link copied, with a credit line" : "Couldn't copy")}
                >
                  Copy Amazon link
                </button>
              </div>
              <span className="mono mono-13 ink2" role="status" aria-live="polite">
                {note}
              </span>
              <AlertLink keyword={suggestKeyword(d.title, d.brand, true)} source="deal">
                Alert me for more like this
              </AlertLink>
              <p className="fine">
                Sold and shipped by Amazon, with its normal returns. Prices from{" "}
                <a href="https://keepa.com" rel="noopener">
                  Data by Keepa
                </a>
                . No affiliate links.
              </p>
            </>
          )}
        </div>
      </div>
      {!gone && (
        // phones: the photo and title fill the first screen, so the way to Amazon stays pinned to the bottom (10-15)
        <div className="buybar" aria-hidden>
          <span className="tnum">
            <b>{money(d.price)}</b> · {d.pct_off}% off
          </span>
          <a className="btn btn-stamp" href={outLink(d, src)} {...OUT} tabIndex={-1}>
            On Amazon <span aria-hidden>↗</span>
          </a>
        </div>
      )}
      {data.same_shelf.length > 0 && (
        <>
          <div className="head">
            <h2 className="sub-head">
              {data.same_size ? `More in size ${data.same_size} on ${shelf}` : gone ? `Still on ${shelf}` : `More on ${shelf}`}
            </h2>
            <span className="end">
              <Link className="linkbtn" href={`/shelf/${encodeURIComponent(d.shelf)}/`}>
                See the shelf
              </Link>
            </span>
          </div>
          <div className="grid three" role="list">
            {data.same_shelf.slice(0, 3).map((x) => (
              <DealCard key={x.id} d={x} now={now} source="related" />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

const labels = { shared: "Shared", copied: "Link copied", failed: "" } as const;
