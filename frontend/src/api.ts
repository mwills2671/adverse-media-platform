let csrf = "";
export const setCsrf = (t: string) => { csrf = t; };

export class ApiError extends Error {
  status: number;
  constructor(status: number, msg: string) { super(msg); this.status = status; }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = opts.method || "GET";
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrf;
  const r = await fetch("/api" + path, {
    method, headers, credentials: "same-origin",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: any) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join("; ") : msg;
    } catch { /* ignore */ }
    if (r.status === 401 && !path.startsWith("/auth/login")) window.dispatchEvent(new Event("ams-unauth"));
    throw new ApiError(r.status, msg);
  }
  const ct = r.headers.get("content-type") || "";
  return (ct.includes("json") ? r.json() : (r.blob() as any)) as Promise<T>;
}

export async function download(path: string, filename: string) {
  const r = await fetch("/api" + path, { credentials: "same-origin" });
  if (!r.ok) throw new ApiError(r.status, "Download failed");
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export type User = { username: string; role: "admin" | "analyst" | "readonly" };
export type Meta = {
  providers: any[]; test_mode: boolean; llm_enabled: boolean; llm_model: string | null; app_env: string;
  taxonomy: { groups: any; categories: { id: string; group: string; label: string; severity: string; weight: number; enabled: boolean }[] };
  statuses: { id: string; label: string }[]; dispositions: Record<string, string>; stages: string[]; fixture_sets: string[];
};
