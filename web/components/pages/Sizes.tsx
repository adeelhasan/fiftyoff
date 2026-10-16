"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { variant } from "@/lib/ab";
import { api, countView } from "@/lib/api";
import { count, shelfName } from "@/lib/format";
import { useApi, useNow, useShelves } from "@/lib/hooks";
import { anySizes, describe, loadSizes, NO_SIZES, saveSizes, slot } from "@/lib/mySizes";
import type { Deal, MySizes } from "@/lib/types";
import { DealCard, SkeletonGrid } from "../DealCard";
import { Empty, LoadError } from "../States";

// D59: clothes and shoes on their own page. Every Resale unit is one size, so the feed's sized items are noise unless
// they fit (persona interview 5). The first visit asks for the visitor's sizes (kept on this device), then shows only
// the deals in them; each card shows its size on the photo.
export default function Sizes() {
  const [mine, setMine] = useState<MySizes | null>(null);
  const [editing, setEditing] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const m = loadSizes();
    setMine(m);
    setEditing(!m);
    setReady(true);
    countView("sizes", variant());
  }, []);

  if (!ready) return <SkeletonGrid n={8} className="grid w200" />;
  return (
    <section style={{ gap: 28 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <h1 className="page-title">Clothes &amp; Shoes</h1>
        <p className="explainer">
          Clothes and shoes come one size per unit, so a great deal only helps if it fits. Tell us your sizes once and we
          show only the half-off deals in them. Your sizes stay on this device. Everything else is in{" "}
          <Link href="/deals/">All deals</Link>.
        </p>
      </div>
      {editing ? (
        <Picker
          start={mine ?? NO_SIZES}
          onDone={(m) => {
            saveSizes(m);
            setMine(m);
            setEditing(false);
          }}
        />
      ) : (
        <Results mine={mine ?? NO_SIZES} onEdit={() => setEditing(true)} />
      )}
    </section>
  );
}

function Picker({ start, onDone }: { start: MySizes; onDone: (m: MySizes) => void }) {
  const { data, error, retry } = useApi(api.sizes, "sizes");
  const [m, setM] = useState<MySizes>(start);
  const on = (g: string, v: string) => {
    const [k, x] = slot(g, v);
    return m[k].includes(x);
  };
  const toggle = (g: string, v: string) => {
    const [k, x] = slot(g, v);
    setM((p) => ({ ...p, [k]: p[k].includes(x) ? p[k].filter((y) => y !== x) : [...p[k], x] }));
  };
  if (!data && error) return <LoadError retry={retry} />;
  if (!data) return <SkeletonGrid n={4} className="grid w200" />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <span className="mono mono-13 ink2 tnum">
        {count(data.sized)} SIZED DEALS · PICK ANY THAT FIT YOU OR SOMEONE YOU SHOP FOR
      </span>
      {data.groups
        .filter((g) => g.values.length > 0)
        .map((g) => (
          <div className="size-group" key={g.id}>
            <h2>{g.name}</h2>
            <div className="chips-wrap">
              {g.values.map(({ v, n }) => (
                <button key={v} className="chip" aria-pressed={on(g.id, v)} onClick={() => toggle(g.id, v)}>
                  {v} <span className="n tnum">{n}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      <div className="size-bar">
        <button className="btn btn-ink" disabled={!anySizes(m)} onClick={() => onDone(m)}>
          Show deals in my sizes
        </button>
        <button className="btn btn-outline" onClick={() => onDone(NO_SIZES)}>
          Show every size
        </button>
      </div>
    </div>
  );
}

function Results({ mine, onEdit }: { mine: MySizes; onEdit: () => void }) {
  const key = JSON.stringify(mine);
  const { data, error, retry } = useApi(() => api.sized(mine), `sized:${key}`);
  const [extra, setExtra] = useState<Deal[]>([]);
  const [busy, setBusy] = useState(false);
  const shelves = useShelves();
  const now = useNow();
  useEffect(() => setExtra([]), [key]);
  const deals = data ? [...data.deals, ...extra] : [];
  const loadMore = () => {
    setBusy(true);
    api
      .sized(mine, deals.length)
      .then((r) => setExtra((x) => [...x, ...r.deals]))
      .catch(() => {})
      .finally(() => setBusy(false));
  };
  return (
    <div className="results">
      <div className="size-bar">
        <span className="mono mono-13 ink2">{anySizes(mine) ? `YOUR SIZES: ${describe(mine).toUpperCase()}` : "EVERY SIZE"}</span>
        <button className="chip" onClick={onEdit}>
          Change sizes
        </button>
        {data && <span className="mono mono-13 ink2 tnum">{count(data.count)} LIVE</span>}
      </div>
      {!data && error ? <LoadError retry={retry} /> : null}
      {!data && !error && <SkeletonGrid n={8} className="grid w200" />}
      {data && data.count === 0 && (
        <Empty>Nothing in your sizes right now. New units land every day; add a size or check back tomorrow.</Empty>
      )}
      {deals.length > 0 && (
        <div className="grid w200" role="list">
          {deals.map((d) => (
            <DealCard key={d.id} d={d} shelfLabel={shelfName(d.shelf, shelves)} now={now} source="sizes" />
          ))}
        </div>
      )}
      {data && deals.length < data.count && (
        <button className="btn btn-ink more" onClick={loadMore} disabled={busy}>
          Show more
        </button>
      )}
    </div>
  );
}
