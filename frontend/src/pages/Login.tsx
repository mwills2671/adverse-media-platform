import { FormEvent, useState } from "react";
import { api, setCsrf, User } from "../api";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const r = await api("/auth/login", { method: "POST", body: { username, password } });
      setCsrf(r.csrf); onLogin(r.user);
    } catch (e: any) { setErr(e.message || "Login failed"); } finally { setBusy(false); }
  };
  return <div className="min-h-screen flex items-center justify-center bg-login p-4">
    <form onSubmit={submit} className="card w-full max-w-sm p-6 space-y-4 shadow-2xl bg-white/95 backdrop-blur" aria-label="Sign in">
      <div>
        <div className="text-xs font-black text-indigo-900 tracking-widest">AMS</div>
        <h1 className="text-xl font-semibold text-slate-900">Adverse Media Screening</h1>
        <p className="text-sm text-slate-500">Authorised financial crime compliance users only.</p>
      </div>
      <div><label className="label" htmlFor="u">Username</label>
        <input id="u" className="input" autoComplete="username" value={username} onChange={e => setU(e.target.value)} required /></div>
      <div><label className="label" htmlFor="p">Password</label>
        <input id="p" type="password" className="input" autoComplete="current-password" value={password} onChange={e => setP(e.target.value)} required /></div>
      {err && <div role="alert" className="text-sm text-red-700">{err}</div>}
      <button className="btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      <p className="text-[11px] text-slate-500">Activity is recorded in a tamper-evident audit log. Personal data is processed for AML/CTF
        customer due diligence under UK GDPR; see the DPIA.</p>
    </form>
  </div>;
}
