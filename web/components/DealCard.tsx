import type { Deal, Gone } from "@/lib/types";
import { ago, freshness, minutesSince, money, outLink, variantTag } from "@/lib/format";

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

/** The grid card. The whole card is one plain link to our /d/ redirect (never next/link, never Amazon). */
export function DealCard({ d, shelfLabel, now }: { d: Deal; shelfLabel?: string; now: number }) {
  const acceptable = d.condition === "Acceptable";
  const tag = variantTag(d);
  const f = freshness(d, now || undefined);
  return (
    <a className={`card${acceptable ? " acceptable" : ""}`} href={outLink(d)}>
      <div className="photo">
        <Photo src={d.image} alt={d.title} />
        <PctStamp pct={d.pct_off} muted={acceptable} />
        <Grade condition={d.condition} />
        {tag && <span className="vtag">{tag}</span>}
      </div>
      <div className="body">
        {shelfLabel && <span className="mono ink2">{shelfLabel}</span>}
        <div className="line">
          {d.from && <span className="from">from</span>}
          <span className="price tnum">{money(d.price)}</span>
          {d.title}
        </div>
        {acceptable ? (
          <span className="wear">{WEAR_LINE}</span>
        ) : (
          now > 0 && f.text && <span className={`fresh${f.isNew ? " new" : ""}`}>{f.text}</span>
        )}
      </div>
    </a>
  );
}

/** The gone mini. Not a link. */
export function GoneMini({ g, now }: { g: Gone; now: number }) {
  const when = ago(minutesSince(g.gone_at, now || undefined));
  return (
    <div className="card gone">
      <div className="photo">
        <Photo src={g.image} alt={g.title} />
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
