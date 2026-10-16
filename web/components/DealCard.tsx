import { onCardClick } from "@/lib/sheet";
import { dealLink } from "@/lib/share";
import type { Deal, Gone } from "@/lib/types";
import { Usual } from "./Usual";
import { ago, minutesSince, money, OUT, outLink, variantTag } from "@/lib/format";

export const WEAR_LINE = "Visible wear. Works, may lack box or extras.";

export function PctStamp({ pct, large, muted }: { pct: number; large?: boolean; muted?: boolean }) {
  return (
    <div className={`stamp tnum${large ? " lg" : ""}${muted ? " muted" : ""}`} aria-label={`${pct}% off`}>
      {pct}%<small aria-hidden>OFF</small>
    </div>
  );
}

export function Grade({ condition, large }: { condition: string; large?: boolean }) {
  return <span className={`grade${condition === "Acceptable" ? " warn" : ""}${large ? " lg" : ""}`}>{condition}</span>;
}

export function Photo({ src, alt, eager }: { src: string | null; alt: string; eager?: boolean }) {
  return (
    // Amazon's CDN, hot-linked: next/image can't optimise in a static export.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src ?? undefined}
      alt={alt}
      loading={eager ? "eager" : "lazy"}
      fetchPriority={eager ? "high" : undefined}
      decoding="async"
      referrerPolicy="no-referrer"
    />
  );
}

/** What a screen reader says for a card (REPORT 24): "Sony lens, 53% off, $153.80, Like New, on Amazon". */
export function cardName(d: Deal): string {
  const words = d.title.split(/\s+/);
  const short = words.length > 10 ? words.slice(0, 10).join(" ") + "…" : d.title;
  const was = d.usual_price ? `, usually ${money(d.usual_price)}` : "";
  return `${short}, ${d.pct_off}% off, ${money(d.price)}${was}, ${d.condition}, details`;
}

/** The grid card. D64: the whole card is one plain link to our deal page (share, related deals, the Amazon button
 * there). A plain <a>: /deal/{slug}/ has no Next route (FastAPI serves the one exported page). D68: a small
 * "Amazon ↗" link sits on the card's bottom line for people who already know what they want (a sibling, not
 * nested: links can't hold links). */
export function DealCard({ d, shelfLabel, now, source }: { d: Deal; shelfLabel?: string; now: number; source?: string }) {
  const acceptable = d.condition === "Acceptable";
  const tag = variantTag(d);
  return (
    <div className="li" role="listitem">
      <a
        className={`card${acceptable ? " acceptable" : ""}`}
        href={dealLink(d, source)}
        onClick={(e) => onCardClick(e, d, source)}
        aria-label={cardName(d)}
      >
        <div className="photo">
          <Photo src={d.image} alt="" />
          <PctStamp pct={d.pct_off} muted={acceptable} />
          <Grade condition={d.condition} />
          {tag && <span className="vtag">{tag}</span>}
          {d.size && <span className="size-tag">{d.size}</span>}
        </div>
        <div className="body">
          {shelfLabel && <span className="mono ink2">{shelfLabel}</span>}
          <div className="line">
            <span className="price tnum">{money(d.price)}</span>
            {d.title}
          </div>
          <Usual d={d} />
          {/* D70: no time on cards ("last checked" is on the deal page); no "from": the price is the lowest */}
          {acceptable && <span className="wear">{WEAR_LINE}</span>}
          <span className="out">
            Details <span aria-hidden>→</span>
          </span>
        </div>
      </a>
      <a className="card-amazon" href={outLink(d, source)} {...OUT} aria-label={`${d.title.slice(0, 60)} on Amazon`}>
        Amazon <span aria-hidden>↗</span>
      </a>
    </div>
  );
}

/** The gone mini. Not a link. */
export function GoneMini({ g, now }: { g: Gone; now: number }) {
  const when = ago(minutesSince(g.gone_at, now || undefined));
  return (
    <div className="card gone">
      <div className="photo">
        <Photo src={g.image} alt="" />
        <div className="gone-stamp" aria-hidden>
          GONE
        </div>
      </div>
      <div className="body">
        <div className="line">
          <span className="price tnum">{money(g.last_price)}</span>
          {g.title}
        </div>
        <span className="meta tnum">
          {g.pct_off}% off{now > 0 && when ? ` · gone ${when}` : ""}
        </span>
      </div>
    </div>
  );
}

export function SkeletonGrid({ n = 5, className = "grid" }: { n?: number; className?: string }) {
  return (
    <div className={className} aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <div className="card skel" key={i}>
          <div className="photo" />
          <div className="body">
            <div className="skel-line" />
            <div className="skel-line" style={{ width: "50%" }} />
          </div>
        </div>
      ))}
    </div>
  );
}
