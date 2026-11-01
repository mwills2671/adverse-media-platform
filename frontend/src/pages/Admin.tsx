import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../App";
import { Banner, fmtDate } from "../ui";

function Users() {
  const { user } = useAuth();
  const [list, setList] = useState<any[]>([]);
  const [n, setN] = useState({ username: "", password: "", role: "analyst" });
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const load = () => api("/admin/users").then(setList);
  useEffect(() => { load(); }, []);
  const run = async (p: Promise<any>, ok: string) => { try { await p; setMsg({ k: "ok", t: ok }); load(); } catch (e: any) { setMsg({ k: "error", t: e.message }); } };
  return <section className="card p-4 space-y-3">
    <h2 className="font-semibold">Users</h2>
    <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-sm">
      <thead><tr><th className="th">User</th><th className="th">Role</th><th className="th">Active</th><th className="th">Last login</th><th className="th"></th></tr></thead>
      <tbody>{list.map(u => <tr key={u.id} className="border-t">
        <td className="td">{u.username}</td>
        <td className="td"><select className="input !py-1" value={u.role} disabled={u.username === user?.username}
          onChange={e => run(api(`/admin/users/${u.id}`, { method: "PATCH", body: { role: e.target.value } }), "Role updated")}>
          <option>admin</option><option>analyst</option><option>readonly</option></select></td>
        <td className="td">{u.active ? "yes" : "no"}</td><td className="td text-xs">{fmtDate(u.last_login_at)}</td>
        <td className="td">{u.username !== user?.username && <button className="btn-secondary !py-1" onClick={() => run(api(`/admin/users/${u.id}`, { method: "PATCH", body: { active: !u.active } }), "Updated")}>{u.active ? "Disable" : "Enable"}</button>}</td>
      </tr>)}</tbody></table></div>
    <form className="grid sm:grid-cols-4 gap-2" onSubmit={e => { e.preventDefault(); run(api("/admin/users", { method: "POST", body: n }).then(() => setN({ username: "", password: "", role: "analyst" })), "User created"); }}>
      <input className="input" placeholder="Username" value={n.username} onChange={e => setN({ ...n, username: e.target.value })} autoComplete="off" />
      <input className="input" type="password" placeholder="Initial password (12+ chars)" value={n.password} onChange={e => setN({ ...n, password: e.target.value })} autoComplete="new-password" />
      <select className="input" value={n.role} onChange={e => setN({ ...n, role: e.target.value })}><option>analyst</option><option>readonly</option><option>admin</option></select>
      <button className="btn-primary">Add user</button>
    </form>
    {msg && <Banner kind={msg.k}>{msg.t}</Banner>}
  </section>;
}

function Policy() {
  const [txt, setTxt] = useState("");
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const load = () => api("/admin/policy").then(r => { const p = { ...r.policy }; delete p.version; setTxt(JSON.stringify(p, null, 2)); });
  useEffect(() => { load(); }, []);
  const save = async () => {
    let body; try { body = JSON.parse(txt); } catch { setMsg({ k: "error", t: "Invalid JSON" }); return; }
    try { await api("/admin/policy", { method: "PUT", body }); setMsg({ k: "ok", t: "Policy saved (audited)" }); load(); } catch (e: any) { setMsg({ k: "error", t: e.message }); }
  };
  return <section className="card p-4 space-y-2">
    <h2 className="font-semibold">Scoring & coverage policy</h2>
    <p className="text-xs text-slate-500">Thresholds for RED rules, identity weights, minimum source coverage and retention. min_core_ok cannot be below 1 — failed research can never be GREEN.</p>
    <textarea className="input font-mono text-xs" rows={18} value={txt} onChange={e => setTxt(e.target.value)} aria-label="Policy JSON" spellCheck={false} />
    <div className="flex gap-2"><button className="btn-primary" onClick={save}>Save policy</button><button className="btn-secondary" onClick={load}>Reset edits</button></div>
    {msg && <Banner kind={msg.k}>{msg.t}</Banner>}
  </section>;
}

function Taxonomy() {
  const { meta } = useAuth();
  const [cats, setCats] = useState<any[]>(meta?.taxonomy.categories || []);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const upd = (i: number, k: string, v: any) => setCats(cats.map((c, j) => j === i ? { ...c, [k]: v } : c));
  const save = async () => {
    const body = Object.fromEntries(cats.map(c => [c.id, { enabled: c.enabled, weight: Number(c.weight), severity: c.severity }]));
    try { await api("/admin/taxonomy", { method: "PUT", body }); setMsg({ k: "ok", t: "Taxonomy saved (audited). New screenings will use it." }); } catch (e: any) { setMsg({ k: "error", t: e.message }); }
  };
  return <section className="card p-4 space-y-2">
    <h2 className="font-semibold">Risk taxonomy</h2>
    <div className="overflow-x-auto max-h-[480px]"><table className="w-full min-w-[520px] text-sm">
      <thead className="sticky top-0 bg-white"><tr><th className="th">Category</th><th className="th">Group</th><th className="th">Severity</th><th className="th">Weight</th><th className="th">Enabled</th></tr></thead>
      <tbody>{cats.map((c, i) => <tr key={c.id} className="border-t">
        <td className="td">{c.label}</td><td className="td text-xs">{meta?.taxonomy.groups?.[c.group] || c.group}</td>
        <td className="td"><select className="input !py-1" value={c.severity} onChange={e => upd(i, "severity", e.target.value)}>
          {["critical", "high", "medium", "low"].map(s => <option key={s}>{s}</option>)}</select></td>
        <td className="td"><input className="input !py-1 w-20" type="number" min={0} max={3} step={0.1} value={c.weight} onChange={e => upd(i, "weight", e.target.value)} /></td>
        <td className="td"><input type="checkbox" checked={c.enabled} onChange={e => upd(i, "enabled", e.target.checked)} aria-label={`Enable ${c.label}`} /></td>
      </tr>)}</tbody></table></div>
    <button className="btn-primary" onClick={save}>Save taxonomy</button>
    {msg && <Banner kind={msg.k}>{msg.t}</Banner>}
  </section>;
}

function Retention() {
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState("");
  return <section className="card p-4 space-y-2">
    <h2 className="font-semibold">Data retention (UK GDPR)</h2>
    <p className="text-sm text-slate-600">Anonymises screenings older than the policy retention period: subject data and findings are removed; status, coverage and the audit chain are kept.</p>
    <button className="btn-secondary" onClick={() => api("/admin/retention/run", { method: "POST" }).then(setR).catch(e => setErr(e.message))}>Run retention now</button>
    {r && <Banner kind="ok">Anonymised {r.anonymised} screening(s) older than {r.retention_days} days.</Banner>}
    {err && <Banner kind="error">{err}</Banner>}
  </section>;
}

export default function Admin() {
  return <div className="space-y-4"><h1 className="text-xl font-semibold">Administration</h1><Users /><Policy /><Taxonomy /><Retention /></div>;
}
