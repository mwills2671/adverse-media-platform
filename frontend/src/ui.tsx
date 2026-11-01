import { ReactNode } from "react";

export const STATUS_STYLE: Record<string, string> = {
  GREEN: "bg-green-700 text-white", AMBER: "bg-amber-500 text-black", RED: "bg-red-700 text-white",
  FAILED: "bg-slate-600 text-white",
};

export function StatusBadge({ status, big }: { status?: string | null; big?: boolean }) {
  const s = status || "PENDING";
  return <span className={`inline-flex items-center rounded font-bold tracking-wide ${big ? "px-4 py-2 text-xl" : "px-2 py-0.5 text-xs"} ${STATUS_STYLE[s] || "bg-slate-200 text-slate-700"}`}
    aria-label={`Status ${s}`}>{s}</span>;
}

const LEVEL_STYLE: Record<string, string> = {
  confirmed: "bg-red-100 text-red-800", probable: "bg-orange-100 text-orange-800", possible: "bg-yellow-100 text-yellow-800",
  unlikely: "bg-slate-100 text-slate-700", contradicted: "bg-slate-200 text-slate-500 line-through",
};
export const IdentityChip = ({ level }: { level: string }) =>
  <span className={`chip ${LEVEL_STYLE[level] || "bg-slate-100"}`} title="Identity match confidence">ID: {level}</span>;

const SEV_STYLE: Record<string, string> = {
  critical: "bg-red-700 text-white", high: "bg-red-100 text-red-800", medium: "bg-amber-100 text-amber-800", low: "bg-slate-100 text-slate-700",
};
export const SeverityChip = ({ sev }: { sev?: string | null }) =>
  sev ? <span className={`chip ${SEV_STYLE[sev]}`}>{sev}</span> : null;

export function Banner({ kind, children }: { kind: "warn" | "error" | "info" | "ok"; children: ReactNode }) {
  const c = { warn: "bg-amber-50 border-amber-400 text-amber-900", error: "bg-red-50 border-red-400 text-red-900",
    info: "bg-indigo-50 border-indigo-300 text-indigo-900", ok: "bg-green-50 border-green-400 text-green-900" }[kind];
  return <div role={kind === "error" ? "alert" : "status"} className={`border-l-4 rounded p-3 text-sm ${c}`}>{children}</div>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <div className="fixed inset-0 z-50 bg-black/40 flex items-end sm:items-center justify-center p-0 sm:p-4" role="dialog" aria-modal="true" aria-label={title}>
    <div className="bg-white w-full sm:max-w-lg rounded-t-lg sm:rounded-lg shadow-xl max-h-[90vh] overflow-auto">
      <div className="flex justify-between items-center border-b px-4 py-3">
        <h2 className="font-semibold">{title}</h2>
        <button className="text-slate-500 hover:text-slate-900 text-xl leading-none" onClick={onClose} aria-label="Close">×</button>
      </div>
      <div className="p-4">{children}</div>
    </div>
  </div>;
}

export function Bars({ data, colour = "bg-indigo-600" }: { data: { label: string; value: number; cls?: string }[]; colour?: string }) {
  const max = Math.max(1, ...data.map(d => d.value));
  return <div className="space-y-1.5">
    {data.map(d => <div key={d.label} className="flex items-center gap-2 text-xs">
      <div className="w-32 sm:w-40 truncate text-slate-600" title={d.label}>{d.label}</div>
      <div className="flex-1 bg-slate-100 rounded h-3 overflow-hidden">
        <div className={`h-3 ${d.cls || colour}`} style={{ width: `${(d.value / max) * 100}%` }} />
      </div>
      <div className="w-8 text-right tabular-nums">{d.value}</div>
    </div>)}
  </div>;
}

export const fmtDate = (s?: string | null) => s ? new Date(s).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—";
export const humanise = (s?: any) => String(s ?? "").replace(/_/g, " ");
