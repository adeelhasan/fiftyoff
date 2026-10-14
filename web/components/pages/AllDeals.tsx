"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { arm } from "@/lib/ab";
import { api, countView } from "@/lib/api";
import { count, shelfName } from "@/lib/format";
import { useNow, useShelves } from "@/lib/hooks";
import { markSeen, visitSince } from "@/lib/lastLook";
import type { AisleCount, CondId, Deal, DealsResponse, Gone, PriceBand, Sort } from "@/lib/types";
import { DealCard, GoneMini, SkeletonGrid } from "../DealCard";
import { Empty, LoadError } from "../States";
import { Sheet, useWatch } from "../Watch";

// The design's sidebar (README "All deals"); the server filters, sorts and pages (api-v1.md).
const CONDS: [CondId, string][] = [
  ["like-new", "Like New"],
  ["very-good", "Very Good"],
  ["good", "Good"],
  ["acceptable", "Acceptable"],
];
// REPORT 2: no chip starts selected. An empty list means the default, every grade but Acceptable, and a first tap
// selects only that grade (instead of removing it from a pre-selected set).
const DEFAULT_COND: CondId[] = ["like-new", "very-good", "good"];
const ALL_COND: CondId[] = ["like-new", "very-good", "good", "acceptable"];
const BANDS: [PriceBand, string][] = [
  ["any", "Any"],
  ["under-100", "Under $100"],
  ["100-300", "$100–300"],
  ["300-plus", "$300+"],
];
// trust-first §1.4: the default mixes shelves (no more than 2 in a row from one); "Newest first" is the pure order.
const SORTS: [Sort, string][] = [
  ["mixed", "Newest, mixed shelves"],
  ["newest", "Newest first"],
  ["saved", "Most $ saved"],
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
  q: string; // search (trust-first §4.1)
  hide: string[]; // aisles left out (§4.3)
}
const sentCond = (f: Filters) => (f.cond.length ? f.cond : DEFAULT_COND);

function fromUrl(): Filters {
  const p = new URLSearchParams(location.search);
  const cond = (p.get("cond") ?? "").split(",").filter((c): c is CondId => CONDS.some(([id]) => id === c));
  const price = p.get("price") as PriceBand;
  const sort = p.get("sort") as Sort;
  return {
    cond,
    price: BANDS.some(([id]) => id === price) ? price : "any",
    aisle: p.get("aisle") ?? "",
    nofit: p.get("nofit") === "true",
    sort: SORTS.some(([id]) => id === sort) ? sort : "mixed",
    q: (p.get("q") ?? "").slice(0, 80),
    hide: (p.get("hide") ?? "").split(",").filter(Boolean),
  };
}

function toUrl(f: Filters) {
  const p = new URLSearchParams();
  const cond = CONDS.map(([id]) => id).filter((c) => f.cond.includes(c)); // a stable order
  if (cond.length) p.set("cond", cond.join(","));
  if (f.price !== "any") p.set("price", f.price);
  if (f.aisle) p.set("aisle", f.aisle);
  if (f.nofit) p.set("nofit", "true");
  if (f.sort !== "mixed") p.set("sort", f.sort);
  if (f.q) p.set("q", f.q);
  if (f.hide.length) p.set("hide", f.hide.join(","));
  const s = p.toString();
  history.replaceState(history.state, "", s ? `?${s}` : location.pathname);
}

const isDefault = (f: Filters) => f.price === "any" && !f.aisle && !f.nofit && !f.cond.length && !f.hide.length;

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
    countView(new URLSearchParams(location.search).get("q") ? "search" : "deals", arm());
  }, []);

  const key = f ? JSON.stringify(f) : "";
  useEffect(() => {
    if (!f) return;
    toUrl(f);
    let live = true;
    setLoading(true);
    setError(null);
    api
      .deals({ ...f, cond: sentCond(f), aisle: f.aisle || undefined, since: f.q ? undefined : (since ?? undefined), limit: PAGE })
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
      .deals({ ...f, cond: sentCond(f), aisle: f.aisle || undefined, since: f.q ? undefined : (since ?? undefined), limit: PAGE, offset: deals.length })
      .then((r) => setDeals((d) => [...d, ...r.deals.filter((x) => !d.some((y) => y.id === x.id))]))
      .catch(() => setError(new Error("more")))
      .finally(() => setMore(false));
  }, [f, res, since, deals.length]);

  const set = (patch: Partial<Filters>) => setF((cur) => (cur ? { ...cur, ...patch } : cur));
  const reset = () => set({ cond: [], price: "any", aisle: "", nofit: false, hide: [] });
  const src = f?.q ? "search" : undefined;

  const newCount = res?.new_count ?? null;
  const [fresh, seen] = useMemo(() => {
    if (newCount === null) return [[], deals] as const;
    return [deals.slice(0, newCount), deals.slice(newCount)] as const;
  }, [deals, newCount]);

  // REPORT 15: the unsorted "just in" shelf isn't a category; such a card shows no shelf label
  const label = (id: string) => (id === "just-in" ? undefined : shelfName(id, shelves));
  const filters = f && (
    <FilterPanel f={f} set={set} aisles={res?.aisles ?? []} total={res ? (f.q ? res.count : res.total) : null} />
  );

  return (
    <section style={{ gap: 28 }}>
      <div className="feed-top">
        <div className="titles">
          <h1 className="page-title">{f?.q ? `“${f.q}”` : "All deals"}</h1>
          {f?.q && (
            <button className="linkbtn" onClick={() => location.assign("/deals/")}>
              Clear search
            </button>
          )}
          {!f?.q && (
            <a className="linkbtn" href="/almost/">
              Almost half off: brands at 30–49% →
            </a>
          )}
          <span className="mono mono-13 ink2 tnum" aria-live="polite">
            {!res ? (
              "CHECKING THE SHELVES"
            ) : f?.q ? (
              `${count(res.count)} LIVE ${res.count === 1 ? "MATCH" : "MATCHES"}${res.gone?.length ? ` · ${res.gone.length} GONE RECENTLY` : ""}`
            ) : f && isDefault(f) && res.total > res.count ? (
              // REPORT 4: say what the default hides, and offer it
              <>
                {count(res.count)} LIVE · {count(res.total - res.count)} ACCEPTABLE HIDDEN ·{" "}
                <button className="linkbtn mono-13" onClick={() => set({ cond: ALL_COND })}>
                  SHOW
                </button>
              </>
            ) : (
              `${count(res.count)} OF ${count(res.total)} LIVE`
            )}
            {res && newCount !== null ? ` · ${count(newCount)} NEW SINCE YOUR LAST LOOK` : ""}
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
          {res && res.count === 0 && !loading && f?.q && (
            <Empty title="None right now">
              Nothing live matches &ldquo;{f.q}&rdquo;{res.gone?.length ? ". These went recently" : ""}. Watch the shelf and we&apos;ll
              tell you when one lands.
            </Empty>
          )}
          {res && res.count === 0 && res.gone?.length ? <SearchGone gone={res.gone} now={now} label={label} lead /> : null}
          {res && res.count === 0 && !loading && !f?.q && (
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
              <div className="grid w200" role="list">
                {fresh.map((d) => (
                  <DealCard key={d.id} d={d} shelfLabel={label(d.shelf)} now={now} source={src} />
                ))}
              </div>
            </>
          )}
          {seen.length > 0 && (
            <>
              {newCount !== null && <div className={`group-label${fresh.length ? " later" : ""}`}>SEEN BEFORE</div>}
              <div className="grid w200" role="list">
                {seen.map((d) => (
                  <DealCard key={d.id} d={d} shelfLabel={label(d.shelf)} now={now} source={src} />
                ))}
              </div>
            </>
          )}
          {res && deals.length < res.count && (
            <button className="btn btn-ink more" onClick={loadMore} disabled={more}>
              {more ? "Loading…" : `Load more · ${count(res.count - deals.length)} left`}
            </button>
          )}
          {res && res.count > 0 && res.gone?.length ? <SearchGone gone={res.gone} now={now} label={label} /> : null}
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

/** D54: search matches that have gone, each with the watch for its shelf. Gone is what alerts are for. */
function SearchGone({ gone, now, label, lead }: { gone: Gone[]; now: number; label: (id: string) => string | undefined; lead?: boolean }) {
  const watch = useWatch();
  return (
    <div className="search-gone">
      <div className="group-label later">{lead ? "WENT RECENTLY" : "GONE RECENTLY"}</div>
      <div className="grid minis">
        {gone.map((g) => {
          const shelf = label(g.shelf) ?? "this shelf";
          return (
            <div className="gone-item" key={`${g.id}-${g.gone_at}`}>
              <GoneMini g={g} now={now} />
              <button className="linkbtn" onClick={() => watch(shelf)} style={{ whiteSpace: "normal", textAlign: "left" }}>
                Watch {shelf}
              </button>
            </div>
          );
        })}
      </div>
    </div>
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
    set({ cond: f.cond.includes(c) ? f.cond.filter((x) => x !== c) : [...f.cond, c] }); // none left = the default
  };
  const allCount = aisles.reduce((n, a) => n + a.count, 0);
  return (
    <div className="filters">
      <div className="group">
        <span className="mono">CONDITION</span>
        {!f.cond.length && <span className="cond-note">Showing every grade but Acceptable. Tap one to see only that grade.</span>}
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
      <details className="hide-aisles" open={f.hide.length > 0}>
        <summary className="mono">HIDE AISLES{f.hide.length ? ` · ${f.hide.length}` : ""}</summary>
        {aisles.map((a) => (
          <label className="check" key={a.id}>
            <input
              type="checkbox"
              checked={f.hide.includes(a.id)}
              onChange={(e) => set({ hide: e.target.checked ? [...f.hide, a.id] : f.hide.filter((x) => x !== a.id) })}
            />
            {a.name}
          </label>
        ))}
      </details>
    </div>
  );
}
