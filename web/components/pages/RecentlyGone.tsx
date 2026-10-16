"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ago, count, minutesSince, money, shelfName, upFor } from "@/lib/format";
import { useApi, useNow, useShelves } from "@/lib/hooks";
import type { GoneWindow } from "@/lib/types";
import { Photo } from "../DealCard";
import { Empty, LoadError } from "../States";
import { suggestKeyword } from "@/lib/alerts";
import { AlertLink } from "../Alert";

const WINDOWS: [GoneWindow, string, string][] = [
  ["24h", "24 h", "24 H"],
  ["3d", "3 days", "3 DAYS"],
  ["7d", "7 days", "7 DAYS"],
];

export default function RecentlyGone() {
  const [win, setWin] = useState<GoneWindow>("3d");
  useEffect(() => {
    const w = new URLSearchParams(location.search).get("window");
    if (WINDOWS.some(([id]) => id === w)) setWin(w as GoneWindow);
  }, []);
  const { data, error, loading, retry } = useApi(() => api.gone(win), win);
  const shelves = useShelves();
  const now = useNow();
  const pick = (w: GoneWindow) => {
    setWin(w);
    history.replaceState(history.state, "", w === "3d" ? location.pathname : `?window=${w}`);
  };
  const winCaps = WINDOWS.find(([id]) => id === win)![2];

  return (
    <section style={{ gap: 28 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <h1 className="page-title">Recently gone</h1>
        <p className="explainer">
          Units our checks stopped finding. We call one gone after 6 hours without a sighting. Usually it sold; sometimes it was
          withdrawn, and we can&apos;t tell which.
        </p>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "16px 28px" }}>
        <div className="seg" role="group" aria-label="Window">
          {WINDOWS.map(([id, name]) => (
            <button key={id} aria-pressed={win === id} onClick={() => pick(id)}>
              {name}
            </button>
          ))}
        </div>
        <span className="mono mono-13 ink2 tnum">{data ? `${count(data.count)} GONE IN THE LAST ${winCaps}` : ""}</span>
      </div>

      {error && !loading ? <LoadError retry={retry} kept={!!data} /> : null}
      {data && data.gone.length === 0 && !loading ? (
        <Empty>Nothing went in the last {winCaps.toLowerCase()}. Try a longer window.</Empty>
      ) : (
        <div className={`table${loading && data ? " dim" : ""}`} aria-busy={loading}>
          <div className="trow th mono" role="row">
            <span />
            <span>PRODUCT</span>
            <span className="r">LAST PRICE · OFF</span>
            <span className="r" style={{ minWidth: 84 }}>
              GONE
            </span>
          </div>
          {!data &&
            Array.from({ length: 6 }, (_, i) => (
              <div className="trow" key={i} aria-hidden>
                <div className="thumb skel" />
                <div className="skel-line" />
                <span />
                <span />
              </div>
            ))}
          {data?.gone.map((g) => {
            const shelf = shelfName(g.shelf, shelves);
            const up = upFor(g.up_for_min, g.up_for_is_lower_bound);
            return (
              <div className="trow" key={`${g.id}-${g.gone_at}`}>
                <div className="thumb">
                  <Photo src={g.image} alt="" />
                </div>
                <div className="prod">
                  <span className="t">{g.title}</span>
                  <span className="s">
                    {g.condition} · {shelf}
                    {up ? ` · ${up}` : ""}
                  </span>
                  <AlertLink keyword={suggestKeyword(g.title, g.brand)} source="gone">
                    Tell me when one lands
                  </AlertLink>
                </div>
                <div className="last">
                  <span className="p tnum">{money(g.last_price)}</span>
                  <span className="pct tnum">{g.pct_off}%</span>
                </div>
                <span className="when tnum">{now > 0 ? ago(minutesSince(g.gone_at, now)) : ""}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
