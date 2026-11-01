import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Banner, fmtDate } from "../ui";

export default function Audit() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<any>({ total: 0, items: [] });
  const [v, setV] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api(`/audit?page=${page}&page_size=50`).then(setData).catch(e => setErr(e.message)); }, [page]);
  const verify = () => api("/audit/verify").then(setV).catch(e => setErr(e.message));
  return <div className="space-y-4">
    <div className="flex flex-wrap justify-between items-center gap-2">
      <h1 className="text-xl font-semibold">Audit log</h1>
      <button className="btn-primary" onClick={verify}>Verify hash chain</button>
    </div>
    <p className="text-sm text-slate-600">Append-only. Each entry stores SHA-256(previous hash + canonical entry). Any edit or deletion breaks the chain.</p>
    {v && (v.valid ? <Banner kind="ok">Chain valid — {v.entries} entries. Head <span className="font-mono break-all">{v.head}</span></Banner>
      : <Banner kind="error">Chain BROKEN at entry #{v.broken_at}: {v.reason}</Banner>)}
    {err && <Banner kind="error">{err}</Banner>}
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[700px] text-sm">
        <thead className="bg-slate-50"><tr><th className="th">#</th><th className="th">Time</th><th className="th">Actor</th><th className="th">Action</th><th className="th">Screening</th><th className="th">Details</th><th className="th">Hash</th></tr></thead>
        <tbody>{data.items.map((e: any) => <tr key={e.seq} className="border-t align-top">
          <td className="td tabular-nums">{e.seq}</td><td className="td whitespace-nowrap text-xs">{fmtDate(e.ts)}</td><td className="td">{e.actor}</td>
          <td className="td font-mono text-xs">{e.action}</td>
          <td className="td text-xs">{e.screening_id ? <Link className="text-indigo-700 underline" to={`/screenings/${e.screening_id}`}>{e.screening_id}</Link> : "—"}</td>
          <td className="td text-xs text-slate-600 break-all max-w-xs">{JSON.stringify(e.details)}</td>
          <td className="td font-mono text-[10px] text-slate-400" title={e.hash}>{e.hash.slice(0, 12)}…</td></tr>)}</tbody>
      </table>
    </div>
    <div className="flex justify-end gap-2 text-sm">
      <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</button>
      <span className="py-2">{page} / {Math.max(1, Math.ceil(data.total / 50))}</span>
      <button className="btn-secondary" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Older</button>
    </div>
  </div>;
}
