"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { arm } from "@/lib/ab";
import { api, countView } from "@/lib/api";
import { ago, minutesSince, money, OUT, outLink, shelfName } from "@/lib/format";
import { useApi, useIdFromUrl, useNow, useShelves } from "@/lib/hooks";
import { cleanText, copy, share } from "@/lib/share";
import type { Deal } from "@/lib/types";
import { DealCard, Grade, PctStamp, Photo } from "../DealCard";
import { Empty, LoadError } from "../States";
import { Usual } from "../Usual";
import { WatchButton } from "../Watch";

// trust-first §4.2: where a shared link lands. Live: the deal, a way to Amazon, share and copy. Gone: the last price
// (D27), the shelf watch and live alternatives.
export default function DealPage() {
  const slug = useIdFromUrl("deal");
  const asin = slug ? slug.slice(0, 10).toUpperCase() : null;
  const { data, error, retry } = useApi(
    () => (asin ? api.product(asin) : Promise.reject(Object.assign(new Error("no id"), { status: 404 }))),
    asin ?? "",
  );
  const shelves = useShelves();
  const now = useNow();
  const [note, setNote] = useState("");

  useEffect(() => {
    if (slug === undefined) return;
    countView(new URLSearchParams(location.search).get("s") === "share" ? "share" : "deal", arm());
  }, [slug]);
  const d: Deal | null = data?.deal ?? data?.gone ?? null;
  useEffect(() => {
    if (d) document.title = `${d.pct_off}% off: ${d.title} · fiftyOff`;
  }, [d]);

  if (slug === undefined || (!data && !error)) {
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
            {gone ? <span className="was-label">Last price </span> : d.from ? <span className="was-label">from </span> : null}
            {money(gone && data.gone ? data.gone.last_price : d.price)}
            <span className="pct"> · {d.pct_off}% off</span>
          </div>
          <Usual d={d} />
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
                Resale are usually one of a kind. We&apos;re still watching {shelf}.
              </p>
              <div>
                <WatchButton shelf={shelf} />
              </div>
            </>
          ) : (
            <>
              {now > 0 && seen && <p className="p">Price as of {seen}: last seen then. It may have sold since.</p>}
              <div className="actions">
                <a className="btn btn-stamp" href={outLink(d, "deal")} {...OUT}>
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
      {data.same_shelf.length > 0 && (
        <>
          <div className="head">
            <h2 className="sub-head">{gone ? `Still on ${shelf}` : `More on ${shelf}`}</h2>
            <span className="end">
              <Link className="linkbtn" href={`/shelf/${encodeURIComponent(d.shelf)}/`}>
                See the shelf
              </Link>
            </span>
          </div>
          <div className="grid three" role="list">
            {data.same_shelf.slice(0, 3).map((x) => (
              <DealCard key={x.id} d={x} now={now} source="deal" />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

const labels = { shared: "Shared", copied: "Link copied", failed: "" } as const;
