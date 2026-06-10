/* Typed-ish API client. Uses a relative base so the app works wherever the
   FastAPI server serves it from; falls back to :8000 during `vite dev`. */

export const API_BASE =
  window.location.port === "5173" ? "http://127.0.0.1:8000" : "";

export async function getJSON<T = any>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

export async function postJSON<T = any>(path: string, body?: any): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

export async function putJSON<T = any>(path: string, body?: any): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

export async function postForm<T = any>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

/* ── Formatting helpers ─────────────────────────────────────────────── */

export const fmtINR = (v: number | null | undefined) =>
  v === null || v === undefined || isNaN(v)
    ? "—"
    : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(v);

export const fmtNum = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || isNaN(Number(v)) ? "—" : Number(v).toFixed(digits);

export const fmtPct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || isNaN(Number(v))
    ? "—"
    : `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(digits)}%`;

export const fmtIST = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso).slice(0, 16);
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
};

export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso).slice(0, 10);
  return d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "2-digit" });
};

export const pnlClass = (v: number | null | undefined) =>
  v === null || v === undefined || isNaN(Number(v)) || Number(v) === 0
    ? "text-slate-400"
    : Number(v) > 0 ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold";
