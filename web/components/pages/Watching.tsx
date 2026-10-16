"use client";
// Watch flow step 5: where the confirm link lands. The app panel stays "coming soon"; no Head start pitch yet.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "../Alert";

export default function Watching() {
  const { me, loaded } = useSession();
  const [q, setQ] = useState<string | null>(null);
  useEffect(() => setQ(new URLSearchParams(location.search).get("q") ?? ""), []);
  const a = me?.alerts.find((x) => x.keyword === q && x.state === "watching");
  const delay = me?.delay_minutes ?? 30;
  const days = me?.lifetime_days ?? 30;
  return (
    <section style={{ gap: 28, maxWidth: 720 }}>
      <div className="watching-stamp lg">WATCHING</div>
      <h1 className="page-title">&lsquo;{q}&rsquo;</h1>
      {loaded && !me ? (
        <p className="explainer">
          This browser isn&apos;t signed in. <Link href="/sign-in/">Sign in</Link> to see your alerts.
        </p>
      ) : (
        <div className="watch-panel">
          <div className="h">What happens next</div>
          <ol className="steps">
            <li>
              A deal matching &lsquo;{q}&rsquo; lands on fiftyOff at half off or better: Amazon Resale, sold and shipped by Amazon.
            </li>
            <li>
              About {delay} minutes later we email {me ? <b>{me.email}</b> : "you"}, if it&apos;s still there.
            </li>
            {me?.one_shot !== false && <li>That one email ends this free alert. You can set it again with one tap.</li>}
            {days > 0 && <li>If nothing lands{a?.ends_at ? ` by ${new Date(a.ends_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}` : ` in ${days} days`}, we&apos;ll tell you and you can keep watching.</li>}
          </ol>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            <Link className="btn btn-ink" href={q ? `/deals/?q=${encodeURIComponent(q)}` : "/deals/"}>
              See what&apos;s live now
            </Link>
            <Link className="linkbtn" href="/my-alerts/">
              My alerts
            </Link>
          </div>
        </div>
      )}
      <div className="watch-panel muted">
        <div className="h">Get alerts on your phone</div>
        <div className="p">The fiftyOff app is coming soon. Your alerts will move over with your email address.</div>
      </div>
    </section>
  );
}
