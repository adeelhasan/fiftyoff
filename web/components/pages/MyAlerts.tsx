"use client";
// Watch flow step 8 ("My shelves", with keywords) and step 9 (stop: one tap, an Undo, no survey). Opened from any
// email's signed link, so it works without a password. Links from emails arrive with one of:
//   ?rearm=ID  "Watch 'dyson' again"     ?stop=all  "Stop these emails"     ?swap=ID  a second keyword's confirm link
//   ?link=expired  a link past its time
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { alertsApi, day, loadSession, setMe, type AlertRow, type Me } from "@/lib/alerts";
import { useAlert, useSession } from "../Alert";
import { SignInForm } from "./SignIn";

type Note = { text: string; undo?: () => Promise<void> } | null;

export default function MyAlerts() {
  const { me, loaded } = useSession();
  const { open } = useAlert();
  const [note, setNote] = useState<Note>(null);
  const [expired, setExpired] = useState(false);
  const [swapId, setSwapId] = useState<number | null>(null);
  const handled = useRef(false);

  // one-time actions from email links, once we know who's signed in
  useEffect(() => {
    if (!loaded || handled.current) return;
    handled.current = true;
    const p = new URLSearchParams(location.search);
    const clean = () => history.replaceState(history.state, "", location.pathname);
    if (p.get("link") === "expired") setExpired(true);
    if (!me) return;
    const rearm = Number(p.get("rearm"));
    const swap = Number(p.get("swap"));
    if (p.get("stop") === "all") {
      const was = me.alerts.filter((a) => a.state === "watching").map((a) => a.id);
      void alertsApi.stopAll().then((r) => {
        if (r.data) setMe(r.data);
        setNote({
          text: "Stopped. You won't get alert emails.",
          undo: was.length
            ? async () => {
                for (const id of was) await act(id, "undo");
              }
            : undefined,
        });
      });
    } else if (rearm) {
      void alertsApi.change(rearm, "rearm").then((r) => {
        if (r.data) {
          setMe(r.data);
          const a = r.data.alerts.find((x) => x.id === rearm);
          setNote({ text: `Watching '${a?.keyword ?? ""}' again.` });
        } else if (r.full) setSwapId(rearm);
      });
    } else if (swap) setSwapId(swap);
    clean();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, me]);

  const act = async (id: number, action: "edit" | "stop" | "undo" | "rearm" | "swap", keyword?: string) => {
    const r = await alertsApi.change(id, action, keyword);
    if (r.data) setMe(r.data);
    return r;
  };

  if (!loaded) return <section aria-busy="true" style={{ minHeight: 320 }} />;
  if (!me)
    return (
      <section style={{ gap: 28, maxWidth: 520 }}>
        <h1 className="page-title">My alerts</h1>
        {expired && <div className="soon warn">That link has expired. Ask for a new one below.</div>}
        <SignInForm lead="Sign in with the address your alerts go to. No password: we email you a link." />
      </section>
    );

  const visible = me.alerts.filter((a) => a.state !== "pending");
  const watching = visible.filter((a) => a.state === "watching").length;
  const swapping = swapId ? me.alerts.find((a) => a.id === swapId) : undefined;
  return (
    <section style={{ gap: 28, maxWidth: 760 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h1 className="page-title">My alerts</h1>
        <span className="mono mono-13 ink2 tnum">
          {watching} OF {me.max} {me.tier === "free" ? "ON FREE" : `ON ${me.tier.toUpperCase()}`} · {me.email.toUpperCase()}
        </span>
      </div>

      {note && (
        <div className="soon" role="status">
          {note.text}{" "}
          {note.undo && (
            <button
              className="linkbtn"
              onClick={async () => {
                await note.undo!();
                setNote({ text: "Back on." });
              }}
            >
              Undo
            </button>
          )}
        </div>
      )}

      {swapping && (
        <div className="watch-panel">
          <div className="h">Swap to &lsquo;{swapping.keyword}&rsquo;?</div>
          <div className="p">
            A free alert watches one keyword at a time. You&apos;re watching{" "}
            {me.alerts
              .filter((a) => a.state === "watching")
              .map((a) => `'${a.keyword}'`)
              .join(", ") || "nothing"}
            .
          </div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
            <button
              className="btn btn-stamp"
              onClick={async () => {
                await act(swapping.id, "swap");
                setSwapId(null);
                setNote({ text: `Watching '${swapping.keyword}'.` });
              }}
            >
              Swap to &lsquo;{swapping.keyword}&rsquo;
            </button>
            <button className="btn btn-outline tall" disabled>
              More keywords · coming soon
            </button>
            <button className="linkbtn" onClick={() => setSwapId(null)}>
              Keep what I have
            </button>
          </div>
        </div>
      )}

      <div className="alert-list">
        {visible.length === 0 && <p className="explainer">No alerts yet.</p>}
        {visible.map((a) => (
          <AlertItem key={a.id} a={a} me={me} act={act} setNote={setNote} />
        ))}
        <button className="btn btn-ink" style={{ alignSelf: "flex-start" }} onClick={() => open("", "my-alerts")}>
          {watching < me.max ? "Add a keyword" : "Change keyword"}
        </button>
      </div>

      {me.caught.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h2 className="sub-head">What your alerts caught</h2>
          <ul className="caught">
            {me.caught.map((c, n) => (
              <li key={`${c.id}-${n}`}>
                <span className={`tag ${c.status}`}>{c.status === "missed" ? "MISSED" : "EMAILED"}</span>
                <span className="t">{c.title}</span>
                <span className="ink2 tnum">
                  {c.status === "missed" ? "sold before we could send it · " : ""}
                  {day(c.at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="watch-panel">
        <label className="check">
          <input
            type="checkbox"
            checked={me.paused}
            onChange={async (e) => {
              const r = await alertsApi.pause(e.target.checked);
              if (r.data) setMe(r.data);
            }}
          />
          Pause all alert emails
        </label>
        <div className="p">
          Emails go to <b>{me.email}</b>. Each one has a link back here and a one-tap stop.
        </div>
        <button
          className="linkbtn"
          style={{ alignSelf: "flex-start" }}
          onClick={async () => {
            await alertsApi.signout();
            setMe(null);
            void loadSession(true);
          }}
        >
          Sign out of this browser
        </button>
      </div>
      <p className="fine">
        Alerts check deals we watch live; they fire on what a search for the same words finds. <Link href="/privacy/">What we keep</Link>.
      </p>
    </section>
  );
}

function AlertItem({
  a,
  me,
  act,
  setNote,
}: {
  a: AlertRow;
  me: Me;
  act: (id: number, action: "edit" | "stop" | "undo" | "rearm" | "swap", keyword?: string) => Promise<{ data: Me | null; error?: string; full?: unknown }>;
  setNote: (n: Note) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [kw, setKw] = useState(a.keyword);
  const [err, setErr] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const r = await act(a.id, "edit", kw);
    if (r.data) {
      setEditing(false);
      setErr("");
    } else setErr(r.full ? "Stop your other alert first: free watches one keyword." : "Use 2 to 40 letters or numbers.");
  };
  const detail =
    a.state === "watching"
      ? me.one_shot
        ? `Emails you once when one lands${a.ends_at ? `. Until ${day(a.ends_at)}` : ""}.`
        : "Emails you each time one lands."
      : a.state === "fired"
        ? `Sent ${day(a.ended_at)}. Free alerts send once.`
        : a.state === "expired"
          ? `Nothing landed in ${me.lifetime_days} days.`
          : `Stopped ${day(a.ended_at)}.`;
  return (
    <div className={`alert-item ${a.state}`}>
      <div className="row">
        <span className="kw">&lsquo;{a.keyword}&rsquo;</span>
        <span className={`tag ${a.state}`}>{a.state === "fired" ? "SENT" : a.state === "expired" ? "ENDED" : a.state.toUpperCase()}</span>
      </div>
      {editing ? (
        <form onSubmit={save} className="edit">
          <input value={kw} onChange={(e) => setKw(e.target.value)} minLength={2} maxLength={40} required aria-label="Keyword" />
          <button className="btn btn-ink" type="submit">
            Save
          </button>
          <button className="linkbtn" type="button" onClick={() => setEditing(false)}>
            Cancel
          </button>
          {err && <p className="form-err">{err}</p>}
        </form>
      ) : (
        <>
          <span className="p">{detail}</span>
          <div className="acts">
            {a.state === "watching" && (
              <>
                <button className="linkbtn" onClick={() => setEditing(true)}>
                  Edit
                </button>
                <button
                  className="linkbtn"
                  onClick={async () => {
                    await act(a.id, "stop");
                    setNote({ text: `Stopped '${a.keyword}'.`, undo: async () => void (await act(a.id, "undo")) });
                  }}
                >
                  Stop
                </button>
              </>
            )}
            {a.state === "stopped" && (
              <button className="linkbtn" onClick={() => void act(a.id, "undo")}>
                Turn back on
              </button>
            )}
            {(a.state === "fired" || a.state === "expired") && (
              <button
                className="linkbtn"
                onClick={async () => {
                  const r = await act(a.id, "rearm");
                  if (!r.data) setNote({ text: "Stop your other alert first: free watches one keyword." });
                }}
              >
                Watch &lsquo;{a.keyword}&rsquo; again
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
