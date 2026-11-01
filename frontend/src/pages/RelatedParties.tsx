import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../App";
import { Banner, StatusBadge } from "../ui";

const CONF: Record<string, string> = {
  high: "bg-green-100 text-green-800", medium: "bg-amber-100 text-amber-800", low: "bg-slate-200 text-slate-700",
  manual: "bg-indigo-100 text-indigo-800",
};
const TYPE: Record<string, string> = { individual: "Individual", entity: "Entity", family: "Family" };

export default function RelatedParties({ s, reload }: { s: any; reload: () => void }) {
  const { can, meta } = useAuth();
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [add, setAdd] = useState<any>({ party_type: "individual", role: "director" });
  const [edit, setEdit] = useState<{ id: number; name: string } | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  const rows: any[] = s.related_parties || [];
  const rs = s.related_summary || {};
  const disc = s.metrics?.related_discovery;
  const write = can("write") && !s.anonymised;
  const visible = rows.filter(r => showDismissed || r.state !== "dismissed");
  const order = ["ubo", "owner", "shareholder", "intermediary", "parent", "board_member", "director", "executive", "founder", "related_person", "other"];
  const cOrder = ["manual", "high", "medium", "low"];
  visible.sort((a, b) => cOrder.indexOf(a.confidence) - cOrder.indexOf(b.confidence) || order.indexOf(a.role) - order.indexOf(b.role) || (a.depth - b.depth));

  const act = async (fn: () => Promise<any>, id: number | null = null) => {
    setErr(""); setBusy(id);
    try { await fn(); reload(); } catch (e: any) { setErr(e.message); } finally { setBusy(null); }
  };
  const screen = (r: any) => act(() => api(`/related-parties/${r.id}/screen`, { method: "POST", body: {} }), r.id);
  const patch = (r: any, body: any) => act(() => api(`/related-parties/${r.id}`, { method: "PATCH", body }), r.id);

  return <div className="space-y-4">
    <div className="grid sm:grid-cols-3 gap-3">
      <div className="card p-4"><div className="label">Subject's own result</div><StatusBadge status={s.final_status} big />
        <p className="text-xs text-slate-500 mt-2">Adverse media about {s.subject_name} itself.</p></div>
      <div className="card p-4"><div className="label">Highest related-party result</div>
        {rs.highest ? <StatusBadge status={rs.highest} big /> : <span className="text-sm text-slate-500">No related party screened yet</span>}
        <p className="text-xs text-slate-500 mt-2">{rs.completed || 0} of {rs.total || 0} screened{rs.pending ? ` · ${rs.pending} running…` : ""}. Kept separate from the subject's status.</p></div>
      <div className="card p-4 text-sm"><div className="label">Decision note</div>
        <p className={rs.hits?.length ? "text-red-800 font-medium" : "text-slate-600"}>{rs.overall_note || "Screen key directors, shareholders and UBOs, then consider any hits in the case decision."}</p></div>
    </div>

    <Banner kind="warn"><b>Unverified leads.</b> Auto-discovered parties are extracted from the public pages cited in each row (company website, Wikipedia,
      news, official registers where configured). Names are only kept if they appear verbatim in the fetched text, but roles and
      percentages may be out of date. Confirm against an official register before relying on them.</Banner>

    {err && <Banner kind="error">{err}</Banner>}
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[900px]">
        <thead><tr className="bg-slate-50"><th className="th">Name</th><th className="th">Type</th><th className="th">Role</th><th className="th">%</th>
          <th className="th">Confidence</th><th className="th">Source</th><th className="th">Screening</th><th className="th">Actions</th></tr></thead>
        <tbody>
          {visible.map(r => {
            const ev = r.evidence?.[0];
            const ch = r.child;
            const screenable = r.party_type !== "family" && !r.partial_name && (r.party_type === "entity" || r.name.trim().split(/\s+/).length >= 2);
            return <tr key={r.id} className={`border-t align-top ${r.state === "dismissed" ? "opacity-50" : ""}`}>
              <td className="td">
                {edit && edit.id === r.id ? <div className="flex gap-1"><input className="input !py-1" value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} aria-label="Full name" />
                  <button className="btn-primary !py-1" onClick={() => { patch(r, { name: edit.name }); setEdit(null); }}>Save</button></div>
                  : <div className="font-medium">{r.name}</div>}
                <div className="text-[11px] text-slate-500">
                  {r.origin === "manual" ? `Added by ${r.added_by}` : "Unverified"}{r.partial_name ? " · partial name" : ""}{r.depth > 1 ? ` · chain depth ${r.depth}` : ""}
                  {r.state === "confirmed" && r.origin !== "manual" ? " · confirmed by analyst" : ""}{r.state === "dismissed" ? " · dismissed" : ""}</div>
                {r.note && <div className="text-[11px] text-slate-500">{r.note}</div>}
              </td>
              <td className="td text-xs">{TYPE[r.party_type] || r.party_type}</td>
              <td className="td text-xs"><div className="font-medium">{r.role_label}</div>
                {r.role_detail && <div className="text-slate-500">{r.role_detail}</div>}
                {r.via && <div className="text-slate-500">via {r.via}</div>}</td>
              <td className="td text-sm tabular-nums">{r.ownership_pct ? `${r.ownership_pct}%` : "—"}</td>
              <td className="td"><span className={`chip ${CONF[r.confidence] || ""}`}>{r.confidence}</span></td>
              <td className="td text-xs max-w-[260px]">
                {ev ? <><a className="text-indigo-700 underline break-all" href={ev.url} target="_blank" rel="noopener noreferrer nofollow">{ev.source} ↗</a>
                  <div className="text-slate-500 italic line-clamp-2" title={ev.quote}>“{ev.quote}”</div>
                  {r.evidence.length > 1 && <details><summary className="cursor-pointer text-slate-500">+{r.evidence.length - 1} more source(s)</summary>
                    {r.evidence.slice(1).map((e: any, i: number) => <div key={i}><a className="text-indigo-700 underline break-all" href={e.url} target="_blank" rel="noopener noreferrer nofollow">{e.source} ↗</a></div>)}</details>}</>
                  : <span className="text-slate-500">Manual entry</span>}
              </td>
              <td className="td text-xs">{ch ? <Link to={`/screenings/${ch.id}`} className="inline-flex flex-col gap-1">
                {ch.job_status === "completed" || ch.job_status === "failed" ? <StatusBadge status={ch.final_status} /> : <span className="chip bg-indigo-100 text-indigo-800 animate-pulse">{ch.stage || "running"}</span>}
                <span className="underline text-indigo-700">{ch.id}</span></Link> : <span className="text-slate-400">Not screened</span>}</td>
              <td className="td text-xs">{write && <div className="flex flex-wrap gap-1 max-w-[190px]">
                {screenable ? <button className="btn-primary !py-1" disabled={busy === r.id || (ch && !["completed", "failed"].includes(ch.job_status))} onClick={() => screen(r)}>{ch ? "Re-screen" : "Screen"}</button>
                  : <button className="btn-secondary !py-1" onClick={() => setEdit({ id: r.id, name: r.name })} title="Only a partial or family name is known">Add full name</button>}
                {r.state === "candidate" && <button className="btn-secondary !py-1" onClick={() => patch(r, { state: "confirmed" })}>Confirm</button>}
                {r.state !== "dismissed" ? <button className="btn-secondary !py-1" onClick={() => patch(r, { state: "dismissed" })}>Dismiss</button>
                  : <button className="btn-secondary !py-1" onClick={() => patch(r, { state: "candidate" })}>Restore</button>}
              </div>}</td>
            </tr>;
          })}
          {!visible.length && <tr><td colSpan={8} className="td text-slate-500">{s.subject_type === "entity" ? "No related parties found in the public sources searched. Add known parties manually below." : "Related-party discovery runs for entity screenings. Add known associates manually below."}</td></tr>}
        </tbody>
      </table>
      {rows.some(r => r.state === "dismissed") && <label className="text-xs text-slate-600 flex items-center gap-1 p-3"><input type="checkbox" checked={showDismissed} onChange={e => setShowDismissed(e.target.checked)} />Show dismissed</label>}
    </div>

    {write && <div className="card p-4">
      <h3 className="font-semibold text-sm mb-2">Add a related party manually</h3>
      <div className="grid sm:grid-cols-5 gap-2">
        <input className="input sm:col-span-2" placeholder="Full name" value={add.name || ""} onChange={e => setAdd({ ...add, name: e.target.value })} aria-label="Name" />
        <select className="input" value={add.party_type} onChange={e => setAdd({ ...add, party_type: e.target.value })} aria-label="Type">
          <option value="individual">Individual</option><option value="entity">Entity</option></select>
        <select className="input" value={add.role} onChange={e => setAdd({ ...add, role: e.target.value })} aria-label="Role">
          {(meta?.related_roles || []).map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</select>
        <input className="input" placeholder="% (optional)" value={add.ownership_pct || ""} onChange={e => setAdd({ ...add, ownership_pct: e.target.value })} aria-label="Ownership percent" />
        <input className="input sm:col-span-4" placeholder="Note / source (optional)" value={add.note || ""} onChange={e => setAdd({ ...add, note: e.target.value })} aria-label="Note" />
        <button className="btn-primary" disabled={(add.name || "").trim().length < 2} onClick={() => act(async () => {
          await api(`/screenings/${s.id}/related-parties`, { method: "POST", body: add }); setAdd({ party_type: "individual", role: "director" });
        })}>Add</button>
      </div>
    </div>}

    {disc && <details className="card p-4 text-sm">
      <summary className="cursor-pointer font-medium">How this list was built — {disc.sources?.length || 0} source checks in {disc.elapsed_s ?? "?"}s</summary>
      <ul className="mt-2 space-y-1 text-xs">{(disc.sources || []).map((x: any, i: number) => <li key={i}>
        <span className={`chip mr-1 ${x.status === "ok" ? "bg-green-100 text-green-800" : "bg-slate-100 text-slate-600"}`}>{x.status}</span>
        <b>{x.source}</b>{x.url && <> — <a className="text-indigo-700 underline break-all" href={x.url} target="_blank" rel="noopener noreferrer nofollow">{x.url}</a></>}
        {x.note && <span className="text-slate-500"> — {x.note}</span>}{x.found ? ` · ${x.found} found` : ""}</li>)}</ul>
      {disc.manual_links?.length > 0 && <><div className="font-medium mt-3 mb-1">Check manually (not machine-searched)</div>
        <ul className="text-xs space-y-1">{disc.manual_links.map((l: any) => <li key={l.url}><a className="text-indigo-700 underline" href={l.url} target="_blank" rel="noopener noreferrer nofollow">{l.name} ↗</a> <span className="text-slate-500">{l.note}</span></li>)}</ul></>}
    </details>}
  </div>;
}
