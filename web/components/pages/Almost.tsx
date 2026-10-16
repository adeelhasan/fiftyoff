"use client";
import Link from "next/link";
import { useEffect } from "react";
import { variant } from "@/lib/ab";
import { api, countView } from "@/lib/api";
import { count, shelfName } from "@/lib/format";
import { useApi, useNow, useShelves } from "@/lib/hooks";
import { DealCard, SkeletonGrid } from "../DealCard";
import { Empty, LoadError } from "../States";

// trust-first §4.4: deals we already track that sit just under half off. Kept apart from the 50%+ feed, on its own
// page, with its own click tag (s=almost). Branded, well-rated and recently seen only; no extra Keepa spend.
export default function Almost() {
  const { data, error, retry } = useApi(api.almost, "almost");
  const shelves = useShelves();
  const now = useNow();
  useEffect(() => countView("almost", variant()), []);

  return (
    <section style={{ gap: 28 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <h1 className="page-title">Almost half off</h1>
        <p className="explainer">
          Brands you know at 30–49% off: not quite our usual line, but worth a look. Same rules otherwise: Amazon Resale units,
          sold and shipped by Amazon, seen in the last day. The full feed stays at{" "}
          <Link href="/deals/">half off or better</Link>.
        </p>
        {data && <span className="mono mono-13 ink2 tnum">{count(data.deals.length)} LIVE</span>}
      </div>
      {!data && error ? <LoadError retry={retry} /> : null}
      {!data && !error && <SkeletonGrid n={8} className="grid w200" />}
      {data && data.deals.length === 0 && <Empty>Nothing just under half off right now. Most days a few turn up.</Empty>}
      {data && data.deals.length > 0 && (
        <div className="grid w200" role="list">
          {data.deals.map((d) => (
            <DealCard key={d.id} d={d} shelfLabel={shelfName(d.shelf, shelves)} now={now} source="almost" />
          ))}
        </div>
      )}
    </section>
  );
}
