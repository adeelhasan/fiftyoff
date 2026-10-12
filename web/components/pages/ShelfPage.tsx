"use client";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import { useApi, useIdFromUrl, useNow } from "@/lib/hooks";
import { DealCard, SkeletonGrid } from "../DealCard";
import { Empty, LoadError } from "../States";
import { WatchPanel } from "../Watch";

// One exported page at /shelf/_/; FastAPI serves it for every /shelf/{id}/ and the id comes from the URL.
export default function ShelfPage() {
  const id = useIdFromUrl("shelf");
  const { data, error, retry } = useApi(() => (id ? api.shelf(id) : Promise.reject(new Error("no shelf"))), id ?? "");
  const now = useNow();

  useEffect(() => {
    if (data) document.title = `${data.shelf.name} · fiftyOff`;
  }, [data]);

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

  const { shelf, deals } = data;
  return (
    <section style={{ gap: 32 }}>
      <div className="shelf-top">
        <div className="left">
          <div className="mono mono-13 ink2">
            {shelf.aisle_name.toUpperCase()} › {shelf.name.toUpperCase()}
          </div>
          <h1 className="shelf-title">{shelf.name}</h1>
          {shelf.description && <p className="desc">{shelf.description}</p>}
          <div className="stats">
            <span>
              <b className="tnum">{count(shelf.live)}</b> live now
            </span>
            {shelf.per_week ? (
              <span>
                About <b className="tnum">{count(shelf.per_week)}</b> new a week
              </span>
            ) : null}
          </div>
        </div>
        <WatchPanel shelf={shelf.name} />
      </div>
      {deals.length ? (
        <div className="grid w210">
          {deals.map((d) => (
            <DealCard key={d.id} d={d} now={now} />
          ))}
        </div>
      ) : (
        <Empty>Every unit on this shelf has gone. New ones land most weeks.</Empty>
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
