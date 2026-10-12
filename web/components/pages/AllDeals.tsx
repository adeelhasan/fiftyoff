"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { count, shelfName } from "@/lib/format";
import { useNow, useShelves } from "@/lib/hooks";
import { markSeen, visitSince } from "@/lib/lastLook";
import type { AisleCount, CondId, Deal, DealsResponse, PriceBand, Sort } from "@/lib/types";
import { DealCard, SkeletonGrid } from "../DealCard";
import { Empty, LoadError } from "../States";
import { Sheet } from "../Watch";

// The design's sidebar (README "All deals"); the server filters, sorts and pages (api-v1.md).
const CONDS: [CondId, string][] = [
  ["like-new", "Like New"],
  ["very-good", "Very Good"],
  ["good", "Good"],
  ["acceptable", "Acceptable"],
];
const DEFAULT_COND: CondId[] = ["like-new", "very-good", "good"]; // Acceptable only when chosen
const BANDS: [PriceBand, string][] = [
  ["any", "Any"],
  ["under-100", "Under $100"],
  ["100-300", "$100–300"],
  ["300-plus", "$300+"],
];
const SORTS: [Sort, string][] = [
  ["newest", "Newest first"],
  ["discount", "Biggest discount"],
  ["price-asc", "Lowest price"],
  ["price-desc", "Highest price"],
];
const PAGE = 60;

interface Filters {
  cond: CondId[];
  price: PriceBand;
  aisle: string;
  nofit: boolean;
  sort: Sort;
}
const DEFAULTS: Filters = { cond: DEFAULT_COND, price: "any", aisle: "", nofit: false, sort: "newest" };

function fromUrl(): Filters {
  const p = new URLSearchParams(location.search);
  const cond = (p.get("cond") ?? "").split(",").filter((c): c is CondId => CONDS.some(([id]) => id === c));
  const price = p.get("price") as PriceBand;
  const sort = p.get("sort") as Sort;
  return {
    cond: cond.length ? cond : DEFAULT_COND,
    price: BANDS.some(([id]) => id === price) ? price : "any",
    aisle: p.get("aisle") ?? "",
    nofit: p.get("nofit") === "true",
    sort: SORTS.some(([id]) => id === sort) ? sort : "newest",
  };
}

function toUrl(f: Filters) {
  const p = new URLSearchParams();
  const cond = CONDS.map(([id]) => id).filter((c) => f.cond.includes(c)); // a stable order
  if (cond.join() !== DEFAULT_COND.join()) p.set("cond", cond.join(","));
  if (f.price !== "any") p.set("price", f.price);
  if (f.aisle) p.set("aisle", f.aisle);
  if (f.nofit) p.set("nofit", "true");
  if (f.sort !== "newest") p.set("sort", f.sort);
  const s = p.toString();
  history.replaceState(history.state, "", s ? `?${s}` : location.pathname);
}

const isDefault = (f: Filters) =>
  f.price === "any" && !f.aisle && !f.nofit && [...f.cond].sort().join() === [...DEFAULT_COND].sort().join();

export default function AllDeals() {
  const [f, setF] = useState<Filters | null>(null); // null until read from the URL
  const [since, setSince] = useState<string | null>(null);
  const [res, setRes] = useState<DealsResponse | null>(null);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [sheet, setSheet] = useState(false);
  const shelves = useShelves();
  const now = useNow();

  useEffect(() => {
    setSince(visitSince());
    setF(fromUrl());
  }, []);

  const key = f ? JSON.stringify(f) : "";
  useEffect(() => {
    if (!f) return;
    toUrl(f);
    let live = true;
    setLoading(true);
    setError(null);
    api
      .deals({ ...f, cond: f.cond, aisle: f.aisle || undefined, since: since ?? undefined, limit: PAGE })
      .then((r) => {
        if (!live) return;
        setRes(r);
        setDeals(r.deals);
        markSeen();
      })
      .catch((e) => live && setError(e))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, since, attempt]);

  const loadMore = useCallback(() => {
    if (!f || !res) return;
    setMore(true);
    api
      .deals({ ...f, aisle: f.aisle || undefined, since: since ?? undefined, limit: PAGE, offset: deals.length })
      .then((r) => setDeals((d) => [...d, ...r.deals.filter((x) => !d.some((y) => y.id === x.id))]))
      .catch(() => setError(new Error("more")))
      .finally(() => setMore(false));
  }, [f, res, since, deals.length]);

  const set = (patch: Partial<Filters>) => setF((cur) => (cur ? { ...cur, ...patch } : cur));
  const reset = () => set({ cond: DEFAULT_COND, price: "any", aisle: "", nofit: false });

  const newCount = res?.new_count ?? null;
  const [fresh, seen] = useMemo(() => {
    if (newCount === null) return [[], deals] as const;
    return [deals.slice(0, newCount), deals.slice(newCount)] as const;
  }, [deals, newCount]);

  const label = (id: string) => shelfName(id, shelves);
  const filters = f && (
    <FilterPanel f={f} set={set} aisles={res?.aisles ?? []} total={res?.total ?? null} />
  );

  return (
    <section style={{ gap: 28 }}>
      <div className="feed-top">
        <div className="titles">
          <h1 className="page-title">All deals</h1>
          <span className="mono mono-13 ink2 tnum" aria-live="polite">
            {res
              ? `${count(res.count)} OF ${count(res.total)} LIVE${newCount !== null ? ` · ${count(newCount)} NEW SINCE YOUR LAST LOOK` : ""}`
              : "CHECKING THE SHELVES"}
          </span>
        </div>
        <button className="chip filter-btn" onClick={() => setSheet(true)} aria-haspopup="dialog">
          Filters{f && !isDefault(f) ? " ·  on" : ""}
        </button>
        {f && (
          <label className="sort">
            Sort
            <select value={f.sort} onChange={(e) => set({ sort: e.target.value as Sort })}>
              {SORTS.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="feed">
        <aside className="filters" aria-label="Filters">
          {filters}
        </aside>
        <div className={`results${loading && res ? " dim" : ""}`} aria-busy={loading}>
          {error && !more ? <LoadError retry={() => setAttempt((n) => n + 1)} kept={deals.length > 0} /> : null}
          {!res && !error && <SkeletonGrid n={8} className="grid w200" />}
          {res && res.count === 0 && !loading && (
            <Empty
              action={
                f && !isDefault(f) ? (
                  <button className="btn btn-ink" onClick={reset}>
                    Clear filters
                  </button>
                ) : null
              }
            >
              No deals match these filters at the moment. Widen the condition or price, or watch a shelf in this aisle and we&apos;ll
              tell you when one lands.
            </Empty>
          )}
          {fresh.length > 0 && (
            <>
              <div className="group-label new">NEW SINCE YOUR LAST LOOK</div>
              <div className="grid w200">
                {fresh.map((d) => (
                  <DealCard key={d.id} d={d} shelfLabel={label(d.shelf)} now={now} />
                ))}
              </div>
            </>
          )}
          {seen.length > 0 && (
            <>
              {newCount !== null && <div className={`group-label${fresh.length ? " later" : ""}`}>SEEN BEFORE</div>}
              <div className="grid w200">
                {seen.map((d) => (
                  <DealCard key={d.id} d={d} shelfLabel={label(d.shelf)} now={now} />
                ))}
              </div>
            </>
          )}
          {res && deals.length < res.count && (
            <button className="btn btn-ink more" onClick={loadMore} disabled={more}>
              {more ? "Loading…" : `Load more · ${count(res.count - deals.length)} left`}
            </button>
          )}
        </div>
      </div>

      {sheet && f && (
        <Sheet label="Filters" onClose={() => setSheet(false)}>
          <div className="sheet-head">
            <div className="name">Filters</div>
            <span className="mono ink2 tnum">{res ? `${count(res.count)} MATCH` : ""}</span>
          </div>
          {filters}
          <button className="btn btn-ink" onClick={() => setSheet(false)}>
            Show {res ? count(res.count) : ""} deals
          </button>
        </Sheet>
      )}
    </section>
  );
}

function FilterPanel({
  f,
  set,
  aisles,
  total,
}: {
  f: Filters;
  set: (p: Partial<Filters>) => void;
  aisles: AisleCount[];
  total: number | null;
}) {
  const toggle = (c: CondId) => {
    const next = f.cond.includes(c) ? f.cond.filter((x) => x !== c) : [...f.cond, c];
    set({ cond: next.length ? next : f.cond }); // at least one condition stays on
  };
  const allCount = aisles.reduce((n, a) => n + a.count, 0);
  return (
    <div className="filters">
      <div className="group">
        <span className="mono">CONDITION</span>
        <div className="chips-wrap">
          {CONDS.map(([id, name]) => (
            <button key={id} className="chip" aria-pressed={f.cond.includes(id)} onClick={() => toggle(id)}>
              {name}
            </button>
          ))}
        </div>
      </div>
      <div className="group">
        <span className="mono">PRICE</span>
        <div className="chips-wrap">
          {BANDS.map(([id, name]) => (
            <button key={id} className="chip" aria-pressed={f.price === id} onClick={() => set({ price: id })}>
              {name}
            </button>
          ))}
        </div>
      </div>
      <div className="aisles">
        <span className="mono">AISLE</span>
        <button className="aisle-row" aria-pressed={!f.aisle} onClick={() => set({ aisle: "" })}>
          All<span className="n tnum">{aisles.length ? count(allCount) : total !== null ? count(total) : ""}</span>
        </button>
        {aisles.map((a) => (
          <button key={a.id} className="aisle-row" aria-pressed={f.aisle === a.id} onClick={() => set({ aisle: a.id })}>
            {a.name}
            <span className="n tnum">{count(a.count)}</span>
          </button>
        ))}
      </div>
      <label className="check">
        <input type="checkbox" checked={f.nofit} onChange={(e) => set({ nofit: e.target.checked })} />
        Hide items that depend on size
      </label>
    </div>
  );
}
