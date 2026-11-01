import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Banner, fmtDate, StatusBadge } from "../ui";

export default function History() {
  const [f, setF] = useState({ q: "", status: "", review_state: "", subject_type: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState<any>({ total: 0, items: [] });
  const [err, setErr] = useState("");
  useEffect(() => {
    const t = setTimeout(() => {
      const qs = new URLSearchParams({ ...f, page: String(page), page_size: "25" });
      api(`/screenings?${qs}`).then(setData).catch(e => setErr(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [f, page]);
  const set = (k: string) => (e: any) => { setF({ ...f, [k]: e.target.value }); setPage(1); };
  const pages = Math.max(1, Math.ceil(data.total / 25));
  return <div className="space-y-4">
    <h1 className="text-xl font-semibold">Screening history</h1>
    <div className="card p-3 grid grid-cols-2 md:grid-cols-6 gap-2">
      <input className="input col-span-2" placeholder="Search name or ID" value={f.q} onChange={set("q")} aria-label="Search" />
      <select className="input" value={f.status} onChange={set("status")} aria-label="Status"><option value="">Any status</option>
        {["GREEN", "AMBER", "RED", "FAILED"].map(s => <option key={s}>{s}</option>)}</select>
      <select className="input" value={f.review_state} onChange={set("review_state")} aria-label="Case state"><option value="">Any case state</option>
        <option value="open">Open</option><option value="closed">Closed</option></select>
      <select className="input" value={f.subject_type} onChange={set("subject_type")} aria-label="Subject type"><option value="">Any type</option>
        <option value="individual">Individual</option><option value="entity">Entity</option></select>
      <div className="col-span-2 md:col-span-1 flex gap-1">
        <input type="date" className="input" value={f.date_from} onChange={set("date_from")} aria-label="From date" />
        <input type="date" className="input" value={f.date_to} onChange={set("date_to")} aria-label="To date" />
      </div>
    </div>
    {err && <Banner kind="error">{err}</Banner>}
    <div className="card overflow-hidden">
      <table className="w-full hidden md:table">
        <thead className="bg-slate-50"><tr><th className="th">Subject</th><th className="th">Type</th><th className="th">Status</th><th className="th">Review / mitig.</th><th className="th">Case</th><th className="th">Screened</th><th className="th">By</th></tr></thead>
        <tbody>{data.items.map((s: any) => <tr key={s.id} className="border-t hover:bg-slate-50">
          <td className="td"><Link className="text-indigo-700 font-medium hover:underline" to={`/screenings/${s.id}`}>{s.subject_name || "[anonymised]"}</Link>
            <div className="text-xs text-slate-400">{s.id}{s.test_mode ? " · TEST" : ""}</div></td>
          <td className="td">{s.subject_type}</td>
          <td className="td"><StatusBadge status={s.job_status === "completed" || s.job_status === "failed" ? s.final_status : s.job_status} />{s.incomplete && <span className="text-xs text-amber-700 ml-1">incomplete</span>}</td>
          <td className="td tabular-nums">{s.counts.review} / {s.counts.mitigating}</td>
          <td className="td">{s.review_state}</td><td className="td whitespace-nowrap">{fmtDate(s.created_at)}</td><td className="td">{s.created_by}</td></tr>)}</tbody>
      </table>
      <ul className="md:hidden divide-y">{data.items.map((s: any) => <li key={s.id}>
        <Link to={`/screenings/${s.id}`} className="block p-3">
          <div className="flex justify-between items-start gap-2"><span className="font-medium text-indigo-700 break-words">{s.subject_name || "[anonymised]"}</span><StatusBadge status={s.final_status || s.job_status} /></div>
          <div className="text-xs text-slate-500 mt-1">{s.subject_type} · {fmtDate(s.created_at)} · {s.review_state} · review {s.counts.review}{s.test_mode ? " · TEST" : ""}</div>
        </Link></li>)}</ul>
      {!data.items.length && <p className="p-4 text-sm text-slate-500">No screenings found.</p>}
    </div>
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-500">{data.total} screening(s)</span>
      <div className="flex gap-2"><button className="btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
        <span className="py-2">{page} / {pages}</span>
        <button className="btn-secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></div>
    </div>
  </div>;
}
