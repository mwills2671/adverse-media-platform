import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download } from "../api";
import { useAuth } from "../App";
import { Banner, Bars, fmtDate, humanise, Modal, StatusBadge } from "../ui";
import FindingCard from "./FindingCard";

const PROV_STYLE: Record<string, string> = {
  ok: "bg-green-100 text-green-800", partial: "bg-amber-100 text-amber-800", failed: "bg-red-100 text-red-800",
  "disabled-no-key": "bg-slate-100 text-slate-500", disabled: "bg-slate-100 text-slate-500", pending: "bg-slate-100 text-slate-500",
};

function Progress({ p }: { p: any }) {
  return <div className="card p-4 sm:p-6 max-w-2xl mx-auto" aria-live="polite">
    <h1 className="text-lg font-semibold mb-1">Screening in progress…</h1>
    <p className="text-sm text-slate-500 mb-4">{p.id}. Live searches can take 30–90 seconds.</p>
    <ol className="space-y-1.5 mb-4">
      {p.stages.map((s: string, i: number) => {
        const done = i + 1 < p.stage_index, cur = i + 1 === p.stage_index;
        return <li key={s} className={`flex items-center gap-2 text-sm ${done ? "text-slate-500" : cur ? "font-semibold text-indigo-800" : "text-slate-400"}`}>
          <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${done ? "bg-green-600 text-white" : cur ? "bg-indigo-600 text-white animate-pulse" : "bg-slate-200"}`}>{done ? "✓" : i + 1}</span>{s}</li>;
      })}
    </ol>
    {p.provider_runs?.length > 0 && <div className="flex flex-wrap gap-1.5">
      {p.provider_runs.map((r: any) => <span key={r.id} className={`chip ${PROV_STYLE[r.status] || "bg-slate-100"}`}>{r.name}: {r.status}{r.status === "ok" || r.status === "partial" ? ` (${r.results})` : ""}</span>)}
    </div>}
  </div>;
}

export default function ScreeningPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { can, meta } = useAuth();
  const [s, setS] = useState<any>(null);
  const [prog, setProg] = useState<any>(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<"review" | "mitigating" | "low">("review");
  const [catF, setCatF] = useState("");
  const [idF, setIdF] = useState("");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(25);
  const [modal, setModal] = useState<"" | "override" | "close" | "reopen" | "anonymise" | "delete">("");
  const [form, setForm] = useState<any>({});
  const [mErr, setMErr] = useState("");
  const [trail, setTrail] = useState<any[]>([]);
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    try {
      const full = await api(`/screenings/${id}`);
      setS(full); setNotes(full.analyst_notes || "");
      if (!full.counts.review && full.counts.mitigating) setTab("mitigating");
      api(`/audit?screening_id=${id}&page_size=100`).then(r => setTrail(r.items)).catch(() => {});
    } catch (e: any) { setErr(e.message); }
  }, [id]);

  useEffect(() => {
    let stop = false, t: any;
    const poll = async () => {
      try {
        const p = await api(`/screenings/${id}/progress`);
        if (stop) return;
        if (p.job_status === "completed" || p.job_status === "failed") { setProg(null); load(); return; }
        setProg(p); t = setTimeout(poll, 2000);
      } catch (e: any) { setErr(e.message); }
    };
    setS(null); poll();
    return () => { stop = true; clearTimeout(t); };
  }, [id, load]);

  const findings = s?.findings || [];
  const list = useMemo(() => findings.filter((f: any) => f.bucket === tab
    && (!catF || f.primary_category === catF)
    && (!idF || f.identity_level === idF)
    && (!q || (f.title + " " + (f.source_name || "")).toLowerCase().includes(q.toLowerCase()))), [findings, tab, catF, idF, q]);
  const cats = useMemo(() => {
    const m: Record<string, { label: string; value: number }> = {};
    findings.filter((f: any) => f.bucket === "review" && f.categories?.[0]).forEach((f: any) => {
      const c = f.categories[0]; m[c.id] = m[c.id] || { label: c.label, value: 0 }; m[c.id].value++;
    });
    return Object.entries(m).sort((a, b) => b[1].value - a[1].value);
  }, [findings]);

  if (err) return <Banner kind="error">{err}</Banner>;
  if (prog) return <Progress p={prog} />;
  if (!s) return <div className="text-slate-500">Loading…</div>;

  const locked = s.review_state === "closed";
  const cov = s.coverage || {};
  const pending = findings.filter((f: any) => f.bucket === "review" && !f.decision).length;
  const idLevels = ["confirmed", "probable", "possible", "unlikely", "contradicted"];
  const submit = async (path: string, body: any, after?: () => void) => {
    setMErr("");
    try { await api(path, { method: path.endsWith(id!) ? "DELETE" : "POST", body }); setModal(""); setForm({}); after ? after() : load(); }
    catch (e: any) { setMErr(e.message); }
  };
  const updateFinding = (nf: any) => setS({ ...s, findings: s.findings.map((f: any) => f.id === nf.id ? nf : f) });

  return <div className="space-y-4">
    {s.test_mode && <Banner kind="info"><b>TEST DATA</b> — this screening used labelled test fixtures and/or fault injection.</Banner>}
    <section className="card p-4 sm:p-5">
      <div className="flex flex-col sm:flex-row sm:items-start gap-4 justify-between">
        <div className="min-w-0">
          <div className="text-xs text-slate-500">{s.id} · {s.subject_type} · {fmtDate(s.created_at)} by {s.created_by} · {s.duration_s ? `${Math.round(s.duration_s)}s` : ""}</div>
          <h1 className="text-2xl font-semibold break-words">{s.subject_name}</h1>
          {Object.keys(s.identifiers || {}).length > 0 && <div className="text-xs text-slate-600 mt-1">
            {Object.entries(s.identifiers).map(([k, v]: any) => <span key={k} className="mr-3"><b>{humanise(k)}:</b> {Array.isArray(v) ? v.join(", ") : v}</span>)}</div>}
          <div className="text-xs mt-1 text-slate-500">Case: <b>{s.review_state}</b>{s.disposition ? ` — ${meta?.dispositions[s.disposition] || s.disposition} (${s.reviewed_by})` : ""} · Analysis: {s.analysis_mode}</div>
        </div>
        <div className="flex flex-col items-start sm:items-end gap-1">
          <StatusBadge status={s.final_status} big />
          {s.override_status && <div className="text-xs text-slate-600">Override of automated <StatusBadge status={s.auto_status} /> by {s.override_by}</div>}
        </div>
      </div>
      {(s.auto_status === "FAILED" || cov.incomplete) && <div className="mt-3"><Banner kind={s.auto_status === "FAILED" ? "error" : "warn"}>
        <b>{s.auto_status === "FAILED" ? "Research failed" : "Incomplete research"}:</b> {(cov.notes || s.auto_reasons || []).join("; ")}. This result cannot be treated as clear — re-run when sources recover.</Banner></div>}
      <ul className="mt-3 text-sm space-y-0.5 list-disc pl-5">{(s.auto_reasons || []).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
      {s.override_reason && <p className="text-sm mt-2"><b>Override reason:</b> {s.override_reason}</p>}
      <div className="flex flex-wrap gap-2 mt-4">
        <button className="btn-primary" onClick={() => download(`/screenings/${s.id}/report.pdf`, `${s.id}.pdf`).then(load)}>Export PDF</button>
        {can("write") && !s.test_mode && !s.anonymised && <button className="btn-secondary" onClick={async () => { const r = await api(`/screenings/${s.id}/rerun`, { method: "POST" }); nav(`/screenings/${r.id}`); }}>Re-run</button>}
        {can("write") && !locked && <button className="btn-secondary" onClick={() => setModal("override")}>Override status</button>}
        {can("write") && !locked && <button className="btn-secondary" onClick={() => setModal("close")}>Close case</button>}
        {can("write") && locked && <button className="btn-secondary" onClick={() => setModal("reopen")}>Reopen case</button>}
        {can("admin") && !s.anonymised && <button className="btn-secondary" onClick={() => setModal("anonymise")}>Anonymise</button>}
        {can("admin") && <button className="btn-danger" onClick={() => setModal("delete")}>Delete</button>}
      </div>
    </section>

    <section className="grid md:grid-cols-3 gap-4">
      <div className="card p-4"><h2 className="font-semibold text-sm mb-2">Triage</h2>
        <Bars data={[{ label: "Requires review", value: s.counts.review, cls: "bg-amber-500" }, { label: "Material (RED rules)", value: s.counts.material, cls: "bg-red-600" },
          { label: "Mitigating / exculpatory", value: s.counts.mitigating, cls: "bg-green-600" }, { label: "Low relevance", value: s.counts.low, cls: "bg-slate-400" }]} />
        <p className="text-xs text-slate-500 mt-2">{s.metrics.raw_results} raw results → {s.metrics.clusters} distinct stories · article text {s.metrics.fetched_ok}/{s.metrics.fetch_attempted}</p></div>
      <div className="card p-4"><h2 className="font-semibold text-sm mb-2">Review items by category</h2>
        {cats.length ? <Bars data={cats.slice(0, 8).map(([, v]) => v)} /> : <p className="text-sm text-slate-500">None</p>}</div>
      <div className="card p-4"><h2 className="font-semibold text-sm mb-2">Identity confidence (review items)</h2>
        <Bars data={idLevels.map(l => ({ label: l, value: findings.filter((f: any) => f.bucket === "review" && f.identity_level === l).length }))} colour="bg-orange-500" /></div>
    </section>

    <section className="card p-4"><h2 className="font-semibold mb-1">Narrative <span className="text-xs font-normal text-slate-500">({s.narrative_mode})</span></h2>
      <p className="text-sm text-slate-700 whitespace-pre-line">{s.narrative}</p></section>

    <section className="card p-4 overflow-x-auto"><h2 className="font-semibold mb-2">Source coverage</h2>
      <table className="w-full min-w-[560px]"><thead><tr><th className="th">Source</th><th className="th">Status</th><th className="th">Results</th><th className="th">Notes</th></tr></thead>
        <tbody>{(s.provider_runs || []).map((r: any) => <tr key={r.id} className="border-t">
          <td className="td font-medium">{r.name}{r.core ? <span className="text-xs text-slate-400"> core</span> : ""}</td>
          <td className="td"><span className={`chip ${PROV_STYLE[r.status] || ""}`}>{r.status}</span></td>
          <td className="td tabular-nums">{r.results ?? 0}</td>
          <td className="td text-xs text-slate-600">{r.error || r.coverage_note}</td></tr>)}</tbody></table></section>

    <section>
      <div className="flex flex-wrap gap-2 mb-3" role="tablist">
        {([["review", "Requires review"], ["mitigating", "Mitigating / exculpatory"], ["low", "Low relevance"]] as const).map(([k, l]) =>
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => { setTab(k); setShown(25); }}
            className={`btn ${tab === k ? "bg-indigo-700 text-white" : "bg-white border border-slate-300"}`}>{l} ({s.counts[k]})</button>)}
      </div>
      <div className="grid sm:grid-cols-3 gap-2 mb-3">
        <input className="input" placeholder="Filter by headline/source" value={q} onChange={e => setQ(e.target.value)} aria-label="Filter text" />
        <select className="input" value={catF} onChange={e => setCatF(e.target.value)} aria-label="Category filter">
          <option value="">All categories</option>{cats.map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <select className="input" value={idF} onChange={e => setIdF(e.target.value)} aria-label="Identity filter">
          <option value="">All identity levels</option>{idLevels.map(l => <option key={l} value={l}>{l}</option>)}</select>
      </div>
      {tab === "review" && pending > 0 && can("write") && !locked && <div className="mb-3"><Banner kind="info">{pending} review item(s) still need a decision (true match / false positive / unresolved) before the case can be closed.</Banner></div>}
      {can("write") && !locked && tab !== "mitigating" && list.some((f: any) => !f.decision && !f.material) && <details className="card p-3 mb-3 text-sm">
        <summary className="cursor-pointer font-medium">Bulk decision for the {list.filter((f: any) => !f.decision && !f.material).length} undecided non-material item(s) in this view</summary>
        <p className="text-xs text-slate-500 my-2">Material (RED-rule) findings are excluded and must be decided one by one. The bulk action and its reason are audited.</p>
        <div className="flex flex-col sm:flex-row gap-2">
          <select className="input sm:w-48" value={form.bulkDec || ""} onChange={e => setForm({ ...form, bulkDec: e.target.value })} aria-label="Bulk decision">
            <option value="">Decision…</option><option value="false_positive">False positive</option><option value="unresolved">Unresolved</option><option value="true_match">True match</option></select>
          <input className="input" placeholder="Reason (required)" value={form.bulkReason || ""} onChange={e => setForm({ ...form, bulkReason: e.target.value })} />
          <button className="btn-primary" disabled={!form.bulkDec || (form.bulkReason || "").trim().length < 3} onClick={async () => {
            setMErr("");
            try {
              await api(`/screenings/${s.id}/bulk-decision`, { method: "POST", body: { decision: form.bulkDec, reason: form.bulkReason, finding_ids: list.filter((f: any) => !f.decision && !f.material).map((f: any) => f.id) } });
              setForm({}); load();
            } catch (e: any) { setMErr(e.message); }
          }}>Apply</button>
        </div>
        {mErr && !modal && <div className="mt-2"><Banner kind="error">{mErr}</Banner></div>}
      </details>}
      <div className="space-y-2">
        {list.slice(0, shown).map((f: any) => <FindingCard key={f.id} f={f} canWrite={can("write")} locked={locked} onChange={updateFinding} />)}
        {!list.length && <p className="text-sm text-slate-500 card p-4">No items in this view.</p>}
        {list.length > shown && <button className="btn-secondary w-full" onClick={() => setShown(shown + 25)}>Show more ({list.length - shown} remaining)</button>}
      </div>
    </section>

    <section className="grid md:grid-cols-2 gap-4">
      <div className="card p-4"><h2 className="font-semibold mb-1">Manual checks (not machine-searched)</h2>
        <ul className="text-sm space-y-1">{(cov.link_outs?.adverse_media_manual || []).map((l: any) => <li key={l.id}>
          <a className="text-indigo-700 underline" href={l.url} target="_blank" rel="noopener noreferrer nofollow">{l.name} ↗</a> <span className="text-xs text-slate-500">— {l.note}</span></li>)}</ul></div>
      <div className="card p-4 border-dashed"><h2 className="font-semibold mb-1">Sanctions / PEP reference — separate process</h2>
        <p className="text-xs text-slate-500 mb-1">Not adverse media. Not screened by this tool; links provided for convenience only.</p>
        <ul className="text-sm space-y-1">{(cov.link_outs?.sanctions_pep_reference || []).map((l: any) => <li key={l.id}>
          <a className="text-indigo-700 underline" href={l.url} target="_blank" rel="noopener noreferrer nofollow">{l.name} ↗</a></li>)}</ul></div>
    </section>

    <section className="card p-4"><h2 className="font-semibold mb-2">Analyst notes</h2>
      <textarea className="input" rows={3} value={notes} disabled={!can("write") || locked} onChange={e => setNotes(e.target.value)} aria-label="Analyst notes" />
      {can("write") && !locked && <button className="btn-secondary mt-2" onClick={() => api(`/screenings/${s.id}/notes`, { method: "POST", body: { notes } }).then(load)}>Save notes</button>}
    </section>

    <section className="card p-4 overflow-x-auto"><h2 className="font-semibold mb-2">Case audit trail</h2>
      <table className="w-full min-w-[520px] text-xs"><tbody>{trail.map(e => <tr key={e.seq} className="border-t">
        <td className="td whitespace-nowrap">{fmtDate(e.ts)}</td><td className="td">{e.actor}</td><td className="td font-mono">{e.action}</td>
        <td className="td text-slate-600 break-all">{Object.entries(e.details || {}).filter(([k]) => k !== "url").map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ")}</td></tr>)}</tbody></table>
      <p className="text-xs text-slate-500 mt-2">Result hash: <span className="font-mono break-all">{s.result_hash}</span> · <Link className="underline" to="/audit">Verify chain</Link></p>
    </section>

    {modal === "override" && <Modal title="Override automated status" onClose={() => setModal("")}>
      <div className="space-y-3">
        <div className="flex gap-2">{["GREEN", "AMBER", "RED"].map(st => <button key={st} disabled={st === "GREEN" && s.auto_status === "FAILED"}
          className={`btn flex-1 ${form.status === st ? "ring-2 ring-indigo-500" : ""}`} onClick={() => setForm({ ...form, status: st })}><StatusBadge status={st} /></button>)}</div>
        <textarea className="input" rows={4} placeholder="Reasoning (required, min 10 characters) — recorded in the audit log" value={form.reason || ""} onChange={e => setForm({ ...form, reason: e.target.value })} />
        {mErr && <Banner kind="error">{mErr}</Banner>}
        <button className="btn-primary w-full" disabled={!form.status || (form.reason || "").trim().length < 10} onClick={() => submit(`/screenings/${s.id}/override`, form)}>Record override</button>
      </div></Modal>}
    {modal === "close" && <Modal title="Close case with disposition" onClose={() => setModal("")}>
      <div className="space-y-3">
        <select className="input" value={form.disposition || ""} onChange={e => setForm({ ...form, disposition: e.target.value })}>
          <option value="">Select disposition…</option>{Object.entries(meta?.dispositions || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <textarea className="input" rows={3} placeholder="Closing notes" value={form.notes || ""} onChange={e => setForm({ ...form, notes: e.target.value })} />
        {mErr && <Banner kind="error">{mErr}</Banner>}
        <button className="btn-primary w-full" disabled={!form.disposition} onClick={() => submit(`/screenings/${s.id}/close`, { disposition: form.disposition, notes: form.notes || "" })}>Close case</button>
      </div></Modal>}
    {modal === "reopen" && <Modal title="Reopen case" onClose={() => setModal("")}>
      <textarea className="input" rows={3} placeholder="Reason for reopening" value={form.reason || ""} onChange={e => setForm({ ...form, reason: e.target.value })} />
      {mErr && <div className="mt-2"><Banner kind="error">{mErr}</Banner></div>}
      <button className="btn-primary w-full mt-3" disabled={(form.reason || "").trim().length < 5} onClick={() => submit(`/screenings/${s.id}/reopen`, { reason: form.reason })}>Reopen</button></Modal>}
    {modal === "anonymise" && <Modal title="Anonymise screening" onClose={() => setModal("")}>
      <p className="text-sm">Removes the subject name, identifiers, findings, excerpts and notes. Status, provider coverage, result hash and the audit trail are kept. This cannot be undone.</p>
      {mErr && <Banner kind="error">{mErr}</Banner>}
      <button className="btn-danger w-full mt-3" onClick={() => submit(`/screenings/${s.id}/anonymise`, undefined)}>Anonymise</button></Modal>}
    {modal === "delete" && <Modal title="Delete screening" onClose={() => setModal("")}>
      <p className="text-sm">Permanently deletes this screening and its findings. The audit log keeps a record that it existed and was deleted.</p>
      {mErr && <Banner kind="error">{mErr}</Banner>}
      <button className="btn-danger w-full mt-3" onClick={() => submit(`/screenings/${s.id}`, undefined, () => nav("/history"))}>Delete permanently</button></Modal>}
  </div>;
}
