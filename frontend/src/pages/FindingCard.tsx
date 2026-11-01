import { useState } from "react";
import { api } from "../api";
import { Banner, humanise, IdentityChip, SeverityChip } from "../ui";

const DEC_STYLE: Record<string, string> = { true_match: "bg-red-100 text-red-800", false_positive: "bg-green-100 text-green-800", unresolved: "bg-amber-100 text-amber-800" };

export default function FindingCard({ f, canWrite, locked, onChange }: { f: any; canWrite: boolean; locked: boolean; onChange: (f: any) => void }) {
  const [open, setOpen] = useState(false);
  const [dec, setDec] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const [notes, setNotes] = useState(f.notes || "");
  const cat = f.categories?.[0];
  const summaryEv = (f.identity_evidence || []).find((e: any) => e.type === "_summary");
  const ev = (f.identity_evidence || []).filter((e: any) => e.type !== "_summary");

  const act = async (path: string, body: any) => {
    setErr("");
    try { onChange(await api(`/findings/${f.id}/${path}`, { method: "POST", body })); setDec(null); setReason(""); }
    catch (e: any) { setErr(e.message); }
  };

  return <article className={`card ${f.material ? "border-red-400 border-l-4" : f.bucket === "mitigating" ? "border-l-4 border-l-green-500" : ""}`}>
    <button className="w-full text-left p-3 sm:p-4" aria-expanded={open} onClick={() => setOpen(!open)}>
      <div className="flex flex-wrap gap-1.5 mb-1.5 items-center">
        <span className="text-xs text-slate-400 tabular-nums">#{f.rank + 1}</span>
        {f.material && <span className="chip bg-red-700 text-white">MATERIAL</span>}
        {cat && <span className="chip bg-indigo-50 text-indigo-800">{cat.label}</span>}
        <SeverityChip sev={f.severity} />
        {f.event_status !== "unknown" && <span className="chip bg-slate-800 text-white">{humanise(f.event_status)}</span>}
        <IdentityChip level={f.identity_level} />
        <span className="chip bg-slate-100 text-slate-700" title={f.credibility_note}>Tier {f.credibility_tier}</span>
        {f.independent_sources > 1 && <span className="chip bg-slate-100 text-slate-700">{f.independent_sources} sources</span>}
        {f.temporal === "historical" && <span className="chip bg-slate-100 text-slate-600">historical</span>}
        {f.decision && <span className={`chip ${DEC_STYLE[f.decision]}`}>{humanise(f.decision)}</span>}
        {f.escalated && <span className="chip bg-red-50 text-red-700 border border-red-300">escalated</span>}
      </div>
      <h3 className="font-medium text-slate-900 leading-snug">{f.title}</h3>
      <div className="text-xs text-slate-500 mt-0.5">{f.source_name || f.domain} · {f.published_at || "date unknown"} · {humanise(f.implication)}</div>
      {!open && f.summary && <p className="text-sm text-slate-600 mt-1 line-clamp-2">{f.summary}</p>}
    </button>
    {open && <div className="px-3 sm:px-4 pb-4 space-y-3 text-sm border-t pt-3">
      <a className="text-indigo-700 underline break-all" href={f.url} target="_blank" rel="noopener noreferrer nofollow">Open source ↗</a>
      <p>{f.summary}</p>
      {f.quotes?.length > 0 && <div><div className="label">Verbatim evidence</div>
        {f.quotes.map((q: any, i: number) => <blockquote key={i} className="border-l-4 border-indigo-200 pl-3 italic text-slate-700 my-1">“{q.text}”</blockquote>)}</div>}
      {f.excerpt && <details><summary className="cursor-pointer label inline">Excerpt ({f.text_source})</summary>
        <p className="text-slate-700 whitespace-pre-line mt-1">{f.excerpt}</p></details>}
      {f.fetch_note && <p className="text-xs text-slate-500">Retrieval: {f.fetch_note}</p>}
      <div className="grid md:grid-cols-2 gap-3">
        <div className="bg-slate-50 rounded p-3">
          <div className="label">Identity — {f.identity_level} ({f.identity_points} pts)</div>
          {summaryEv && <p className="text-xs text-slate-600 mb-1">{summaryEv.detail}</p>}
          <ul className="text-xs space-y-0.5">
            {ev.map((e: any, i: number) => <li key={i} className="flex justify-between gap-2"><span>{e.detail}</span>
              <span className={`tabular-nums ${e.points >= 0 ? "text-green-700" : "text-red-700"}`}>{e.points >= 0 ? "+" : ""}{e.points}</span></li>)}
          </ul>
          {f.contradictions?.length > 0 && <div className="mt-2"><div className="label !text-red-700">Contradictions</div>
            <ul className="text-xs list-disc pl-4">{f.contradictions.map((c: any, i: number) => <li key={i}>{c.detail}</li>)}</ul></div>}
        </div>
        <div className="bg-slate-50 rounded p-3 space-y-1 text-xs">
          <div className="label">Assessment</div>
          <div><b>Implication:</b> {humanise(f.implication)} — {f.implication_note}</div>
          {f.party_note && <div><b>Party:</b> {f.party} — {f.party_note}</div>}
          <div><b>Status detected:</b> {(f.statuses_detected || []).map((x: any) => typeof x === "string" ? humanise(x) : `${humanise(x.status)} ("${x.term}")`).join(", ") || "none"}</div>
          {f.mitigation?.length > 0 && <div><b>Mitigation:</b> {f.mitigation.map((m: any) => typeof m === "string" ? m : m.detail || m.status).join("; ")}</div>}
          <div><b>Categories:</b> {(f.categories || []).map((c: any) => `${c.label} (${c.severity})`).join(", ") || "none"}</div>
          <div><b>Credibility:</b> Tier {f.credibility_tier} — {f.credibility_note}</div>
          <div><b>Analysis:</b> {f.analysis_mode}{f.llm?.rejected ? " (LLM output rejected by verifier)" : ""}</div>
          <div className="pt-1"><b>RED rule trace {f.material ? "— all conditions met (material)" : "— not material"}:</b>
            <ul className="pl-1">{(f.material_reasons || []).map((r: any, i: number) => <li key={i} className={r.ok ? "text-green-800" : "text-slate-500"}>{r.ok ? "✓" : "✗"} {r.rule}</li>)}</ul></div>
          {f.relevance_reasons?.length > 0 && <div><b>Triage reasons:</b><ul className="list-disc pl-4">{f.relevance_reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></div>}
        </div>
      </div>
      {f.corroborating?.length > 0 && <details><summary className="cursor-pointer label inline">Same story elsewhere ({f.corroborating.length})</summary>
        <ul className="text-xs mt-1 space-y-0.5">{f.corroborating.map((c: any, i: number) => <li key={i}>
          <a className="text-indigo-700 underline break-all" href={c.url} target="_blank" rel="noopener noreferrer nofollow">{c.source || c.domain}</a> — {c.title}</li>)}</ul></details>}
      {f.decision && <p className="text-xs text-slate-600">Decision: <b>{humanise(f.decision)}</b> by {f.decided_by} — {f.decision_reason}</p>}
      {canWrite && !locked && <div className="space-y-2 border-t pt-3">
        <div className="flex flex-wrap gap-2">
          {(["true_match", "false_positive", "unresolved"] as const).map(d =>
            <button key={d} className={`btn-secondary ${dec === d ? "!border-indigo-600 ring-2 ring-indigo-200" : ""}`} onClick={() => setDec(d)}>{humanise(d)}</button>)}
          <button className="btn-secondary" onClick={() => act("escalate", { escalated: !f.escalated, reason: "" })}>{f.escalated ? "De-escalate" : "Escalate"}</button>
        </div>
        {dec && <div className="flex flex-col sm:flex-row gap-2">
          <input className="input" placeholder={`Reason for "${humanise(dec)}" (required)`} value={reason} onChange={e => setReason(e.target.value)} />
          <button className="btn-primary" disabled={reason.trim().length < 3} onClick={() => act("decision", { decision: dec, reason })}>Save decision</button>
        </div>}
        <div className="flex flex-col sm:flex-row gap-2">
          <input className="input" placeholder="Finding notes" value={notes} onChange={e => setNotes(e.target.value)} />
          <button className="btn-secondary" onClick={() => act("notes", { notes })}>Save note</button>
        </div>
        {err && <Banner kind="error">{err}</Banner>}
      </div>}
    </div>}
  </article>;
}
