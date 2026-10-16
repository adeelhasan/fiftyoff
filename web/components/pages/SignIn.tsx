"use client";
// Accounts: "Email me a sign-in link". The same answer for any address, so the form never says who has alerts.
import { useState, type FormEvent } from "react";
import { alertsApi } from "@/lib/alerts";

export function SignInForm({ lead }: { lead?: string }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    const r = await alertsApi.signin(email);
    setBusy(false);
    if (r.data) setSent(email.trim().toLowerCase());
    else setErr(r.error === "email" ? "That email address doesn't look right." : r.status === 429 ? "Too many tries from here. Try again in an hour." : "That didn't work. Try again in a moment.");
  };
  if (sent)
    return (
      <div className="watch-panel">
        <div className="h">Check your inbox</div>
        <div className="p">
          If <b>{sent}</b> has alerts with us, a sign-in link is on its way. It works for 24 hours.
        </div>
        <button className="linkbtn" style={{ alignSelf: "flex-start" }} onClick={() => setSent(null)}>
          Use a different address
        </button>
      </div>
    );
  return (
    <form className="watch-panel" onSubmit={submit}>
      <div className="h">Sign in</div>
      <div className="p">{lead ?? "No password: we email you a link that signs you in on this browser."}</div>
      <label className="field">
        Email address
        <input type="email" required autoComplete="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      {err && <p className="form-err">{err}</p>}
      <button className="btn btn-stamp" type="submit" disabled={busy}>
        {busy ? "Sending…" : "Email me a sign-in link"}
      </button>
    </form>
  );
}

export default function SignIn() {
  return (
    <section style={{ gap: 28, maxWidth: 520 }}>
      <h1 className="page-title">Sign in</h1>
      <SignInForm />
    </section>
  );
}
