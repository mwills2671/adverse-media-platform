import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../App";
import { Banner } from "../ui";

type F = { key: string; label: string; list?: boolean; placeholder?: string; type?: string };
const IND: F[] = [
  { key: "dob", label: "Date of birth or year", placeholder: "1938-04-29 or 1938" },
  { key: "nationality", label: "Nationality", placeholder: "United Kingdom" },
  { key: "country_of_residence", label: "Country of residence" },
  { key: "country_of_birth", label: "Country of birth" },
  { key: "occupation", label: "Occupation / role", placeholder: "Investment adviser" },
  { key: "employer", label: "Employer" },
  { key: "aliases", label: "Aliases / other names", list: true, placeholder: "One per line or comma-separated" },
  { key: "associated_entities", label: "Associated companies", list: true },
  { key: "associated_people", label: "Associated people", list: true },
  { key: "address", label: "Address / postcode", placeholder: "Used only for matching, never searched" },
];
const ENT: F[] = [
  { key: "jurisdiction", label: "Jurisdiction of incorporation", placeholder: "Germany" },
  { key: "registration_number", label: "Registration number", placeholder: "e.g. Companies House number" },
  { key: "country", label: "Country of operation" },
  { key: "sector", label: "Sector" },
  { key: "website", label: "Website" },
  { key: "trading_names", label: "Trading names", list: true },
  { key: "previous_names", label: "Previous names", list: true },
  { key: "aliases", label: "Other aliases", list: true },
  { key: "directors", label: "Directors / officers", list: true, placeholder: "Markus Braun" },
  { key: "ubos", label: "Beneficial owners", list: true },
  { key: "parent_company", label: "Parent company" },
  { key: "registered_address", label: "Registered address / postcode" },
];

export default function NewScreening() {
  const { meta } = useAuth();
  const nav = useNavigate();
  const [type, setType] = useState<"individual" | "entity">("individual");
  const [name, setName] = useState("");
  const [vals, setVals] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(false);
  const [fixture, setFixture] = useState("");
  const [faults, setFaults] = useState<Record<string, boolean>>({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [lookback, setLookback] = useState<string>("");
  const lbDefault = meta?.lookback_years ?? 5;
  const fields = type === "individual" ? IND : ENT;

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(""); setBusy(true);
    const identifiers: Record<string, unknown> = {};
    for (const f of fields) {
      const v = (vals[f.key] || "").trim();
      if (!v) continue;
      identifiers[f.key] = f.list ? v.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean) : v;
    }
    const body: any = { subject_type: type, name: name.trim(), identifiers };
    if (lookback !== "") body.lookback_years = Number(lookback);
    if (meta?.test_mode) {
      if (fixture) body.test_fixture_set = fixture;
      const fi = Object.fromEntries(Object.entries(faults).filter(([, v]) => v).map(([k]) => [k, "simulated outage"]));
      if (Object.keys(fi).length) body.fault_injection = fi;
    }
    try { const r = await api("/screenings", { method: "POST", body }); nav(`/screenings/${r.id}`); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  const filled = fields.filter(f => (vals[f.key] || "").trim()).length;

  return <div className="max-w-3xl mx-auto">
    <h1 className="text-2xl font-semibold mb-1">New adverse media screening</h1>
    <p className="text-sm text-slate-600 mb-4">Searches free news indexes and official sources in real time. Adding identifiers lets the
      engine separate your subject from namesakes — a name-only match can never be rated above “Possible”.</p>
    <form onSubmit={submit} className="card p-4 sm:p-6 space-y-5">
      <div role="radiogroup" aria-label="Subject type" className="grid grid-cols-2 gap-2">
        {(["individual", "entity"] as const).map(t =>
          <button type="button" key={t} role="radio" aria-checked={type === t} onClick={() => setType(t)}
            className={`btn ${type === t ? "bg-indigo-700 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}>
            {t === "individual" ? "Individual" : "Entity / company"}</button>)}
      </div>
      <div>
        <label className="label" htmlFor="name">{type === "individual" ? "Full name" : "Legal / registered name"} *</label>
        <input id="name" className="input text-base" required minLength={2} maxLength={200} value={name} onChange={e => setName(e.target.value)}
          placeholder={type === "individual" ? "e.g. Bernard L. Madoff" : "e.g. Wirecard AG"} />
      </div>
      <div className="grid sm:grid-cols-2 gap-3 items-end">
        <div>
          <label className="label" htmlFor="lb">Date window (look-back)</label>
          <select id="lb" className="input" value={lookback} onChange={e => setLookback(e.target.value)}>
            <option value="">Last {lbDefault} years (default)</option>
            {[1, 2, 3, 5, 7, 10, 15, 20].filter(n => n !== lbDefault).map(n => <option key={n} value={n}>Last {n} years</option>)}
            <option value="0">No date limit</option>
          </select>
        </div>
        <p className="text-xs text-slate-500 pb-1">Articles published before the window are listed separately as context and do not drive the RAG status.
          {type === "entity" && " Entity screenings also search public sources for directors, board, shareholders and UBOs."}</p>
      </div>
      <div className="border rounded-md">
        <button type="button" className="w-full flex justify-between items-center px-3 py-2 text-sm font-medium" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span>Identifiers <span className="text-slate-500 font-normal">(optional, strongly recommended{filled ? ` · ${filled} added` : ""})</span></span>
          <span aria-hidden>{open ? "▲" : "▼"}</span>
        </button>
        {open && <div className="grid sm:grid-cols-2 gap-3 p-3 border-t">
          {fields.map(f => <div key={f.key} className={f.list ? "sm:col-span-1" : ""}>
            <label className="label" htmlFor={f.key}>{f.label}</label>
            {f.list ? <textarea id={f.key} rows={2} className="input" placeholder={f.placeholder} value={vals[f.key] || ""}
              onChange={e => setVals({ ...vals, [f.key]: e.target.value })} />
              : <input id={f.key} className="input" placeholder={f.placeholder} value={vals[f.key] || ""}
                onChange={e => setVals({ ...vals, [f.key]: e.target.value })} />}
          </div>)}
          <p className="sm:col-span-2 text-xs text-slate-500">Identifiers are used to corroborate or contradict matches; only names and
            aliases are sent to search providers. Data minimisation: enter only what is needed for due diligence.</p>
        </div>}
      </div>
      {meta?.test_mode && <div className="border-2 border-dashed border-fuchsia-400 rounded-md p-3 space-y-2 bg-fuchsia-50">
        <div className="text-xs font-bold text-fuchsia-800">TEST MODE ONLY — results will be labelled as test data</div>
        <label className="label" htmlFor="fx">Labelled fixture set (replaces live search)</label>
        <select id="fx" className="input" value={fixture} onChange={e => setFixture(e.target.value)}>
          <option value="">— live search —</option>
          {meta.fixture_sets.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
        <div className="text-xs font-semibold text-slate-700">Fault injection (simulate provider outage)</div>
        <div className="flex flex-wrap gap-3">
          {meta.providers.filter(p => p.core).map(p => <label key={p.id} className="text-sm flex items-center gap-1">
            <input type="checkbox" checked={!!faults[p.id]} onChange={e => setFaults({ ...faults, [p.id]: e.target.checked })} />{p.name}</label>)}
        </div>
      </div>}
      {err && <Banner kind="error">{err}</Banner>}
      <div className="flex flex-col sm:flex-row gap-2 sm:items-center sm:justify-between">
        <p className="text-xs text-slate-500">Typical duration 30–90 seconds. You can leave this page; results are saved.</p>
        <button className="btn-primary sm:w-auto w-full" disabled={busy || name.trim().length < 2}>{busy ? "Starting…" : "Run screening"}</button>
      </div>
    </form>
    {meta && <details className="mt-4 card p-4 text-sm">
      <summary className="cursor-pointer font-medium">Sources that will be searched ({meta.providers.length})</summary>
      <ul className="mt-2 space-y-1">
        {meta.providers.map(p => <li key={p.id} className="flex gap-2">
          <span className={`chip ${p.core ? "bg-indigo-100 text-indigo-800" : "bg-slate-100 text-slate-600"}`}>{p.core ? "media" : "official"}</span>
          <span><b>{p.name}</b> — <span className="text-slate-600">{p.coverage_note}</span></span>
        </li>)}
      </ul>
    </details>}
  </div>;
}
