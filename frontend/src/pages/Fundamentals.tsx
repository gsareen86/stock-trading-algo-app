import { useState } from "react";
import { ExternalLink, Pin } from "lucide-react";
import { fmtNum, postJSON } from "../api";
import { Panel, useApi, Badge, DataTable, EmptyState, Help, toast, Btn, RefreshBtn } from "../components/ui";

export default function Fundamentals() {
  const [scope, setScope] = useState("universe");
  const table = useApi<any[]>(`/api/fundamentals?scope=${scope}`, [scope]);
  const pins = useApi<any[]>("/api/fundamentals/pins");
  const [pinTicker, setPinTicker] = useState("");

  const addPin = async () => {
    if (!pinTicker.trim()) return;
    try {
      await postJSON("/api/fundamentals/pin", { ticker: pinTicker.trim().toUpperCase() });
      toast(`${pinTicker.toUpperCase()} pinned to the watchlist.`);
      setPinTicker(""); pins.reload(); table.reload();
    } catch (e: any) { toast(`Pin failed: ${e.message}`); }
  };

  const rows = (table.data ?? []).map((r: any) => ({ ...r }));

  return (
    <div className="space-y-6">
      <Help text="Fundamental health for every stock the engine touches: holdings across all books, watchlist names, top scan candidates and your pins. Growth figures are smoothed (TTM / 3-year CAGR) to avoid single-quarter distortions; D/E is suppressed for banks where it is meaningless. The Screener link opens the full multi-year picture." />

      <Panel title="Fundamental Scorecards"
        subtitle="Scope 'universe' = names the engine is actively tracking; 'all' = every cached row"
        actions={
          <div className="flex items-center gap-2">
            <select value={scope} onChange={(e) => setScope(e.target.value)}
              className="bg-slate-900/70 border border-slate-700/60 rounded-lg px-2 py-1.5 text-xs text-slate-300 outline-none">
              <option value="universe">Tracked universe</option>
              <option value="all">All cached</option>
            </select>
            <RefreshBtn onClick={table.reload} loading={table.loading} />
          </div>
        }>
        <DataTable
          rows={rows}
          searchKeys={["ticker", "sector", "industry"]}
          defaultSort={{ key: "fundamental_score", dir: "desc" }}
          maxHeight="480px"
          empty={<EmptyState>No fundamentals cached yet. They are fetched automatically for names that enter the universe, get scanned or get pinned.</EmptyState>}
          cols={[
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}{r.is_bank ? <Badge text="BANK" tone="INFO" /> : null}</span> },
            { key: "sector", label: "Sector", render: (r) => <span className="text-[10px]">{r.sector ?? "—"}</span> },
            { key: "fundamental_score", label: "Score", align: "right", render: (r) => <span className="font-bold">{fmtNum(r.fundamental_score, 0)}</span> },
            { key: "pe_ratio", label: "P/E", align: "right", render: (r) => fmtNum(r.pe_ratio, 1) },
            { key: "roe", label: "ROE %", align: "right", render: (r) => fmtNum(r.roe, 1) },
            { key: "revenue_growth", label: "Rev Gr %", align: "right", render: (r) => fmtNum(r.revenue_growth, 1) },
            { key: "earnings_growth", label: "Earn Gr %", align: "right", render: (r) => fmtNum(r.earnings_growth, 1) },
            { key: "debt_to_equity", label: "D/E", align: "right", render: (r) => r.is_bank ? <span className="text-slate-600" title="Not meaningful for banks">n/a</span> : fmtNum(r.debt_to_equity, 2) },
            { key: "profit_margin", label: "Margin %", align: "right", render: (r) => fmtNum(r.profit_margin, 1) },
            { key: "sources", label: "Why Tracked", render: (r) => <span className="text-[9px] text-slate-500">{(r.sources ?? []).join(", ") || "—"}</span> },
            {
              key: "screener_url", label: "Deep Dive", render: (r) => (
                <a href={r.screener_url} target="_blank" rel="noreferrer" className="text-indigo-400 hover:text-indigo-300 inline-flex items-center gap-1">
                  Screener <ExternalLink size={10} />
                </a>
              ),
            },
          ]}
        />
      </Panel>

      <Panel title="Pinned Watchlist" subtitle="Pinned names stay in the tracked universe and get news-impact coverage even when nothing else references them.">
        <div className="flex items-center gap-2 mb-3">
          <input value={pinTicker} onChange={(e) => setPinTicker(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addPin()}
            placeholder="TICKER" className="bg-slate-900/70 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono outline-none w-32 uppercase" />
          <Btn kind="primary" onClick={addPin}><Pin size={11} /> Pin</Btn>
        </div>
        <div className="flex flex-wrap gap-2">
          {(pins.data ?? []).length === 0
            ? <span className="text-[11px] text-slate-500">No pins yet.</span>
            : (pins.data ?? []).map((p: any) => (
              <span key={p.ticker} className="text-[11px] font-mono px-2.5 py-1 rounded-lg bg-slate-800/70 text-slate-200 border border-slate-700/60 inline-flex items-center gap-2">
                {p.ticker}
                <button onClick={async () => {
                  try {
                    await fetch(`/api/fundamentals/pin/${p.ticker}`, { method: "DELETE" });
                    toast(`${p.ticker} unpinned.`); pins.reload();
                  } catch { toast("Unpin failed"); }
                }} className="text-slate-500 hover:text-rose-400">×</button>
              </span>
            ))}
        </div>
      </Panel>
    </div>
  );
}
