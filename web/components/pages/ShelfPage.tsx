"use client";
import { useEffect } from "react";
import { variant } from "@/lib/ab";
import { api, countView } from "@/lib/api";
import { count } from "@/lib/format";
import { useApi, useIdFromUrl, useNow } from "@/lib/hooks";
import { DealCard, GoneMini, SkeletonGrid } from "../DealCard";
import { Empty, LoadError } from "../States";
import { GoneAlert } from "../Alert";

// trust-first §2.2: shelves where "was it worn? is it genuine?" comes up get a line on the grades
const WORN = new Set(["jewelry", "watches", "rings", "handbags-sunglasses"]);

// One exported page at /shelf/_/; FastAPI serves it for every /shelf/{id}/ and the id comes from the URL.
export default function ShelfPage() {
  const id = useIdFromUrl("shelf");
  const { data, error, retry } = useApi(() => (id ? api.shelf(id) : Promise.reject(new Error("no shelf"))), id ?? "");
  const now = useNow();

  useEffect(() => {
    if (data) document.title = `${data.shelf.name} · fiftyOff`;
  }, [data]);
  useEffect(() => countView("shelf", variant()), []);

  if (id === undefined || (!data && !error)) return <ShelfSkeleton />;
  if (!data) {
    const missing = id === null || (error as { status?: number })?.status === 404;
    return missing ? (
      <Empty title="We don't have that shelf">
        <a href="/deals/">See all deals</a> instead.
      </Empty>
    ) : (
      <LoadError retry={retry} />
    );
  }

  // Acceptable units go last, under their own label, so "N live" (which leaves them out, like everywhere) matches
  const { shelf } = data;
  const prime = data.deals.filter((d) => d.condition !== "Acceptable");
  const worn = data.deals.filter((d) => d.condition === "Acceptable");
  const deals = prime;
  return (
    <section style={{ gap: 32 }}>
      <div className="shelf-top">
        <div className="left">
          <div className="mono mono-13 ink2">
            {shelf.aisle_name.toUpperCase()} › {shelf.name.toUpperCase()}
          </div>
          <h1 className="shelf-title">{shelf.name}</h1>
          {shelf.description && <p className="desc">{shelf.description}</p>}
          {WORN.has(shelf.id) && (
            <p className="cond-line">
              Returns graded by Amazon: Like New may have been tried on. <a href="/how-we-price/#conditions">What the grades mean</a>.
            </p>
          )}
          <div className="stats">
            <span>
              <b className="tnum">{count(shelf.live)}</b> live now{worn.length ? `, plus ${count(worn.length)} Acceptable` : ""}
            </span>
          </div>
        </div>
      </div>
      {deals.length ? (
        <>
          <div className="grid w210" role="list">
            {deals.map((d) => (
              <DealCard key={d.id} d={d} now={now} />
            ))}
          </div>
        </>
      ) : worn.length ? null : (
        <Empty>Every unit on this shelf has gone. New ones land most weeks.</Empty>
      )}
      {worn.length > 0 && (
        <>
          <div className="group-label later">ACCEPTABLE · VISIBLE WEAR</div>
          <div className="grid w210" role="list">
            {worn.map((d) => (
              <DealCard key={d.id} d={d} now={now} />
            ))}
          </div>
        </>
      )}
      {data.gone?.length > 0 && (
        // D66: what this shelf had and lost lately, so a thin shelf still shows what turns up here (not links)
        <section>
          <div className="head">
            <h2>Recently gone from {shelf.name.toLowerCase()}</h2>
            <span className="ink2" style={{ fontSize: 16 }}>
              The last 7 days.
            </span>
          </div>
          <div className="grid minis">
            {data.gone.map((g) => (
              <GoneAlert key={g.id} g={g} now={now} />
            ))}
          </div>
        </section>
      )}
    </section>
  );
}

function ShelfSkeleton() {
  return (
    <section style={{ gap: 32 }} aria-busy="true">
      <div className="shelf-top">
        <div className="left">
          <div className="mono mono-13 ink2">CHECKING THE SHELF</div>
          <div className="skel-line" style={{ height: 72, width: "60%" }} />
        </div>
      </div>
      <SkeletonGrid n={8} className="grid w210" />
    </section>
  );
}
