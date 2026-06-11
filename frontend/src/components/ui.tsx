/* Shared UI primitives — every page is composed from these so the whole app
   stays visually aligned: one panel style, one table style, one button set. */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { RefreshCw, Search, Info, ChevronDown, ChevronUp } from "lucide-react";
import { getJSON } from "../api";

/* ── Data hook: fetch + loading + error + manual reload ─────────────── */

export function useApi<T = any>(path: string | null, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    getJSON<T>(path)
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(String(e.message || e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, reload };
}

/* ── Layout primitives ──────────────────────────────────────────────── */

export function Panel({ title, subtitle, actions, children, className = "" }: {
  title?: string; subtitle?: string; actions?: React.ReactNode;
  children: React.ReactNode; className?: string;
}) {
  return (
    <div className={`glass-panel rounded-2xl p-5 ${className}`}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 mb-4 border-b border-slate-800/80 pb-3">
          <div>
            {title && <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300 m-0">{title}</h3>}
            {subtitle && <p className="text-[11px] text-slate-500 m-0 mt-1 leading-snug max-w-2xl">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

export function StatCard({ label, value, sub, tone = "default" }: {
  label: string; value: React.ReactNode; sub?: React.ReactNode;
  tone?: "default" | "good" | "bad" | "accent";
}) {
  const valueClass =
    tone === "good" ? "text-emerald-400" :
    tone === "bad" ? "text-rose-400" :
    tone === "accent" ? "text-indigo-400" : "text-slate-100";
  return (
    <div className="glass-panel rounded-2xl p-4 flex flex-col gap-1 min-h-[92px]">
      <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">{label}</span>
      <span className={`text-xl font-extrabold font-mono ${valueClass}`}>{value}</span>
      {sub && <span className="text-[10px] text-slate-500 leading-snug">{sub}</span>}
    </div>
  );
}

export function Badge({ text, tone }: { text: string; tone?: string }) {
  const t = (tone ?? text ?? "").toUpperCase();
  let cls = "bg-slate-800/60 text-slate-300 border-slate-700/60";
  if (["OK", "BUY", "RUNNING", "OPEN", "SUCCESS", "PROCEED", "MET", "BEAT", "BULLISH", "LONG", "DONE", "APPROVED", "POSITIVE", "NORMAL", "AGGRESSIVE", "HIGH"].includes(t))
    cls = "bg-emerald-500/10 text-emerald-400 border-emerald-500/25";
  else if (["SELL", "STOPPED", "CLOSED", "ERROR", "SKIP", "MISSED", "BEARISH", "SHORT", "CRITICAL", "REJECTED", "FAIL", "FAILED", "NEGATIVE", "DEFENSIVE", "RATE_LIMITED", "CIRCUIT_OPEN", "AVOID"].includes(t))
    cls = "bg-rose-500/10 text-rose-400 border-rose-500/25";
  else if (["WATCH", "HOLD", "PENDING", "REDUCE", "NEUTRAL", "CACHED", "PAUSED", "MEDIUM", "WARNING", "RUNNING_BT", "UNVERIFIABLE", "REVIEW_EXIT", "BOTH"].includes(t))
    cls = "bg-amber-500/10 text-amber-400 border-amber-500/25";
  else if (["INFO", "LT_WATCH", "LONG_TERM", "SWING", "DIRECT", "LOW"].includes(t))
    cls = "bg-indigo-500/10 text-indigo-300 border-indigo-500/25";
  return <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border whitespace-nowrap ${cls}`}>{text}</span>;
}

export function Btn({ children, onClick, kind = "ghost", disabled, busy, title }: {
  children: React.ReactNode; onClick?: () => void;
  kind?: "primary" | "ghost" | "danger"; disabled?: boolean; busy?: boolean; title?: string;
}) {
  const cls =
    kind === "primary" ? "grad-primary text-white shadow-lg shadow-indigo-600/20" :
    kind === "danger" ? "bg-rose-600/80 text-white hover:bg-rose-600" :
    "bg-slate-800/60 text-slate-300 hover:bg-slate-700/60 border border-slate-700/60";
  return (
    <button title={title} disabled={disabled || busy} onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5 ${cls}`}>
      {busy && <RefreshCw size={12} className="animate-spin" />}
      {children}
    </button>
  );
}

export function RefreshBtn({ onClick, loading }: { onClick: () => void; loading?: boolean }) {
  return (
    <button onClick={onClick} title="Refresh"
      className="p-1.5 rounded-lg bg-slate-800/60 text-slate-400 hover:text-slate-200 border border-slate-700/60">
      <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
    </button>
  );
}

export function SearchBox({ value, onChange, placeholder = "Search…" }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <div className="flex items-center gap-2 bg-slate-900/70 border border-slate-700/60 rounded-lg px-2.5 py-1.5">
      <Search size={13} className="text-slate-500" />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="bg-transparent outline-none text-xs text-slate-200 placeholder:text-slate-600 w-40" />
    </div>
  );
}

export function Help({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 text-[11px] text-slate-500 bg-slate-900/50 border border-slate-800/80 rounded-lg px-3 py-2 leading-snug">
      <Info size={13} className="flex-shrink-0 mt-0.5 text-indigo-400/70" />
      <span>{text}</span>
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="p-8 text-center border border-dashed border-slate-800 rounded-xl text-slate-500 text-xs leading-relaxed">
      {children}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="p-4 border border-rose-500/30 bg-rose-500/5 rounded-xl text-rose-300 text-xs space-y-2">
      <div className="font-semibold">Could not load data</div>
      <div className="font-mono opacity-80 break-all">{error}</div>
      {onRetry && <Btn kind="danger" onClick={onRetry}>Retry</Btn>}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="p-10 flex items-center justify-center text-slate-500">
      <RefreshCw size={18} className="animate-spin" />
    </div>
  );
}

/* ── DataTable: sortable, searchable, consistent everywhere ─────────── */

export interface Col<T = any> {
  key: string;
  label: string;
  render?: (row: T) => React.ReactNode;
  align?: "left" | "right" | "center";
  sortValue?: (row: T) => any;
}

export function DataTable<T = any>({ rows, cols, searchKeys, defaultSort, maxHeight = "420px", empty, initialQuery }: {
  rows: T[]; cols: Col<T>[]; searchKeys?: string[];
  defaultSort?: { key: string; dir: "asc" | "desc" };
  maxHeight?: string; empty?: React.ReactNode; initialQuery?: string;
}) {
  const [q, setQ] = useState(initialQuery ?? "");
  const [sort, setSort] = useState(defaultSort ?? null as null | { key: string; dir: "asc" | "desc" });

  const view = useMemo(() => {
    let out = rows;
    if (q && searchKeys?.length) {
      const needle = q.toLowerCase();
      out = out.filter((r: any) =>
        searchKeys.some((k) => String(r[k] ?? "").toLowerCase().includes(needle)));
    }
    if (sort) {
      const col = cols.find((c) => c.key === sort.key);
      const sv = col?.sortValue ?? ((r: any) => r[sort.key]);
      out = [...out].sort((a, b) => {
        const av = sv(a); const bv = sv(b);
        const an = Number(av); const bn = Number(bv);
        const cmp = !isNaN(an) && !isNaN(bn) && av !== "" && bv !== ""
          ? an - bn
          : String(av ?? "").localeCompare(String(bv ?? ""));
        return sort.dir === "asc" ? cmp : -cmp;
      });
    }
    return out;
  }, [rows, q, sort, cols, searchKeys]);

  return (
    <div className="space-y-3">
      {searchKeys?.length ? (
        <div className="flex items-center justify-between">
          <SearchBox value={q} onChange={setQ} />
          <span className="text-[10px] text-slate-600">{view.length} of {rows.length} rows</span>
        </div>
      ) : null}
      {view.length === 0 ? (
        empty ?? <EmptyState>No data yet.</EmptyState>
      ) : (
        <div className="overflow-auto rounded-lg border border-slate-800/60" style={{ maxHeight }}>
          <table className="w-full text-xs font-mono border-collapse">
            <thead className="sticky top-0 z-10">
              <tr className="bg-[#0a1126] text-slate-500 uppercase tracking-wider text-[9px]">
                {cols.map((c) => (
                  <th key={c.key}
                    onClick={() => setSort((s) =>
                      s?.key === c.key ? { key: c.key, dir: s.dir === "asc" ? "desc" : "asc" }
                                       : { key: c.key, dir: "desc" })}
                    className={`py-2 px-3 cursor-pointer select-none whitespace-nowrap text-${c.align ?? "left"}`}>
                    <span className="inline-flex items-center gap-1">
                      {c.label}
                      {sort?.key === c.key && (sort.dir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40">
              {view.map((row: any, i) => (
                <tr key={row.id ?? row.ticker ?? i} className="hover:bg-slate-900/30">
                  {cols.map((c) => (
                    <td key={c.key} className={`py-2 px-3 text-slate-300 whitespace-nowrap text-${c.align ?? "left"}`}>
                      {c.render ? c.render(row) : (row[c.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── Toast (action feedback) ────────────────────────────────────────── */

let _setToast: ((msg: string | null) => void) | null = null;

export function toast(msg: string) {
  _setToast?.(msg);
  setTimeout(() => _setToast?.(null), 3500);
}

export function ToastHost() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { _setToast = setMsg; return () => { _setToast = null; }; }, []);
  if (!msg) return null;
  return (
    <div className="fixed bottom-6 right-6 z-50 glass-panel rounded-xl px-4 py-3 text-xs text-slate-200 border border-indigo-500/30 max-w-sm">
      {msg}
    </div>
  );
}
