import { useRef, useState } from "react";
import { Upload, Zap, Microscope } from "lucide-react";
import { fmtINR, fmtPct, pnlClass, fmtIST, fmtNum, postJSON, postForm } from "../api";
import { Panel, StatCard, useApi, Badge, DataTable, EmptyState, Help, toast, Btn, RefreshBtn } from "../components/ui";
import ScanInspector, { STRATEGY_INFO } from "../components/ScanInspector";

/* The universe funnel in numbers — where stocks fall out and why */
function UniverseFunnel() {
  const s = useApi<any>("/api/universe/summary");
  const d = s.data;
  if (!d) return null;
  const stages = [
    { label: "NSE EQ Master", value: d.nse_master_eq, note: "every listed EQ-series name (incl. microcaps & IPOs)" },
    { label: "Screener Scanned", value: d.lt_pipeline_scanned, note: `mcap ≥ ₹${d.mcap_floor_cr?.toLocaleString()} Cr + filters applied` },
    { label: "Pipeline Passed", value: d.lt_pipeline_passed, note: "mcap, institutional, pledge, ≥3y financials" },
    { label: "Swing Eligible", value: d.swing_eligible, note: "quality ≥ 60 + fundamentals + hygiene gates" },
  ];
  return (
    <Panel title="Universe Funnel" subtitle="One pipeline feeds every book. Each stage's count shows where names fall out; the weekly Saturday refresh rebuilds the whole chain."
      actions={<RefreshBtn onClick={s.reload} loading={s.loading} />}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        {stages.map((st, i) => (
          <div key={st.label} className="bg-slate-900/50 border border-slate-800/70 rounded-xl p-3 relative">
            {i > 0 && <span className="absolute -left-2.5 top-1/2 -translate-y-1/2 text-slate-600 hidden md:block">→</span>}
            <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest">{st.label}</div>
            <div className="text-xl font-extrabold font-mono text-indigo-300 mt-1">{st.value ?? "—"}</div>
            <div className="text-[9px] text-slate-600 leading-snug mt-1">{st.note}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2 text-[10px]">
        <Badge text={`${d.swing_ipo_track ?? 0} IPO-track (<12m listed)`} tone="INFO" />
        <Badge text={`${d.swing_microcaps ?? 0} microcaps (<₹3,000 Cr — halved risk, 35% book budget)`} tone="WATCH" />
        <Badge text={`${d.surveillance_blocked ?? 0} ASM/GSM blocked`} tone="FAIL" />
        <Badge text={`intraday pool: ${d.intraday_pool ?? 0} (depth over breadth)`} />
      </div>
    </Panel>
  );
}

export default function SwingBook() {
  const status = useApi<any>("/api/positional/status");
  const regime = useApi<any>("/api/positional/regime");
  const scans = useApi<any[]>("/api/positional/scan-results");
  const positions = useApi<any[]>("/api/positional/positions");
  const [busy, setBusy] = useState<string | null>(null);
  const [inspected, setInspected] = useState<any | null>(null);
  const fileA = useRef<HTMLInputElement>(null);
  const fileB = useRef<HTMLInputElement>(null);

  const s = status.data;

  const run = async (label: string, path: string) => {
    setBusy(path);
    try { const r = await postJSON(path, {}); toast(`${label}: ${r.message ?? "started"}`); }
    catch (e: any) { toast(`${label} failed: ${e.message}`); }
    setBusy(null);
  };

  const uploadCSV = async () => {
    const a = fileA.current?.files?.[0];
    const b = fileB.current?.files?.[0];
    if (!a || !b) { toast("Select both CSVs (Query A: non-financials, Query B: banks/NBFCs)."); return; }
    const form = new FormData();
    form.append("query_a", a); form.append("query_b", b);
    setBusy("upload");
    try {
      const r = await postForm("/api/positional/universe/upload", form);
      toast(`Universe updated: ${r.result?.passed ?? "?"} passed, ${r.result?.failed ?? "?"} filtered.`);
    } catch (e: any) { toast(`Upload failed: ${e.message}`); }
    setBusy(null);
  };

  return (
    <div className="space-y-6">
      <Help text="The swing book holds positions for days to weeks. Each EOD scan (16:00 IST) runs four strategies, blends them with quality/valuation/momentum/sentiment/management pillars into a Timing + Durability scorecard, then enters with risk-based sizing. Exits: 8% hard stop → +2R partial (stop to breakeven) → 21-EMA trail → strategy-scaled time stop. Entries are blocked near results dates (event guard) and for ASM/GSM or illiquid names (hygiene gate)." />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Pool Value" value={fmtINR(s?.total_valuation)} tone="accent"
          sub={`Cash ${fmtINR(s?.cash_balance)} · invested ${fmtINR(s?.allocated_value)}`} />
        <StatCard label="Net Realized P&L" value={<span className={pnlClass(s?.net_realized_pnl)}>{fmtINR(s?.net_realized_pnl)}</span>}
          sub="All closed swing trades" />
        <StatCard label="Positions" value={`${s?.active_positions_count ?? 0} / ${s?.max_positions ?? 5}`}
          sub={`${s?.available_slots ?? "—"} slots free`} />
        <StatCard label="Macro Regime" value={<Badge text={regime.data?.flag ?? "—"} />}
          sub={`Size × ${fmtNum(regime.data?.size_multiplier, 2)} · Nifty ROC18m ${fmtNum(regime.data?.nifty_roc_18m, 1)}`} />
      </div>

      <div className="flex flex-wrap gap-2">
        <Btn kind="primary" busy={busy === "/api/positional/scan"} onClick={() => run("EOD scan", "/api/positional/scan")}><Zap size={11} /> Run EOD Scan</Btn>
        <Btn busy={busy === "/api/positional/exit-check"} onClick={() => run("Exit check", "/api/positional/exit-check")}>Run Exit Check</Btn>
        <Btn busy={busy === "/api/positional/regime/run"} onClick={() => run("Regime", "/api/positional/regime/run")}>Recompute Regime</Btn>
        <Btn busy={busy === "/api/positional/universe/sync"} onClick={() => run("Universe sync", "/api/positional/universe/sync")}
          title="Pull the scraped Screener universe through quality + hygiene gates into this book's universe">
          Sync Universe from Screener
        </Btn>
      </div>

      <Panel title="Open Swing Positions" subtitle="Hard stop / EMA trail / time stop per position. 'Why Held' is the entry rationale recorded at buy time (scan score + LLM verdict). 'Partial' shows whether the +2R de-risk has fired (stop then sits at breakeven)."
        actions={<RefreshBtn onClick={positions.reload} loading={positions.loading} />}>
        <DataTable
          rows={positions.data ?? []}
          searchKeys={["ticker", "strategy"]}
          empty={<EmptyState>No open swing positions. Enable the positional module in Control (or via bot_control) and run an EOD scan — entries appear when a setup clears the scorecard, the event guard and the hygiene gate.</EmptyState>}
          cols={[
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "quantity", label: "Qty", align: "right", render: (r) => <span>{r.quantity}{r.initial_quantity && r.initial_quantity !== r.quantity ? <span className="text-slate-600"> /{r.initial_quantity}</span> : null}</span> },
            { key: "entry_price", label: "Entry", align: "right", render: (r) => fmtINR(r.entry_price) },
            { key: "current_price", label: "Live", align: "right", render: (r) => fmtINR(r.current_price) },
            { key: "unrealized_pnl", label: "Unrealized", align: "right", render: (r) => <span className={pnlClass(r.unrealized_pnl)}>{fmtINR(r.unrealized_pnl)} ({fmtPct(r.unrealized_pnl_pct)})</span> },
            { key: "hard_stop", label: "Hard Stop", align: "right", render: (r) => fmtINR(r.hard_stop) },
            { key: "partial_taken", label: "Partial", render: (r) => <Badge text={r.partial_taken ? "TAKEN" : "WAITING"} tone={r.partial_taken ? "OK" : "PENDING"} /> },
            { key: "ema_trail_stop", label: "21-EMA", align: "right", render: (r) => <span>{fmtINR(r.ema_trail_stop)}{r.below_ema_consecutive ? <span className="text-amber-400"> ({r.below_ema_consecutive}↓)</span> : null}</span> },
            { key: "days_held", label: "Held", align: "right", render: (r) => `${r.days_held}d${r.time_stop_days ? ` / ${r.time_stop_days}d` : ""}` },
            { key: "strategy", label: "Strategy", render: (r) => <span className="text-[10px]">{r.strategy}</span> },
            {
              key: "entry_reason", label: "Why Held", render: (r) => (
                <span className="text-[10px] text-slate-400 whitespace-normal max-w-[260px] inline-block leading-snug"
                  title={r.entry_reason}>{r.entry_reason}</span>
              ),
            },
          ]}
        />
      </Panel>

      <Panel title="Latest Scan Results" subtitle="Per-stock scorecard: composite drives entry; Timing = is there a setup now, Durability = can the business compound. Horizon routes names to this book (SWING/BOTH) or the Long-Term book (LONG_TERM). Click 🔬 Inspect on any row to see WHY — which strategies fired, the pillar breakdown and the chart."
        actions={<RefreshBtn onClick={scans.reload} loading={scans.loading} />}>
        {inspected && <div className="mb-4"><ScanInspector row={inspected} onClose={() => setInspected(null)} /></div>}
        <DataTable
          rows={scans.data ?? []}
          searchKeys={["ticker", "alert_type", "horizon", "strategies_fired"]}
          defaultSort={{ key: "composite_score", dir: "desc" }}
          maxHeight="500px"
          empty={<EmptyState>No scans yet. Hit "Run EOD Scan" above — the table fills as each ticker is scored (needs a populated universe first: upload CSVs below or use "Sync Universe from Screener").</EmptyState>}
          cols={[
            {
              key: "inspect", label: "", render: (r) => (
                <button onClick={() => setInspected(r)} title="Why did this score? Strategies, pillars and chart"
                  className="p-1 rounded-md bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/25 border border-indigo-500/20">
                  <Microscope size={12} />
                </button>
              ),
            },
            { key: "scanned_at", label: "Scanned", render: (r) => fmtIST(r.scanned_at) },
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "alert_type", label: "Alert", render: (r) => <Badge text={r.alert_type} /> },
            { key: "composite_score", label: "Composite", align: "right", render: (r) => <span className="font-bold">{fmtNum(r.composite_score ?? r.score, 0)}</span> },
            { key: "timing_score", label: "Timing", align: "right", render: (r) => fmtNum(r.timing_score, 0) },
            { key: "durability_score", label: "Durability", align: "right", render: (r) => fmtNum(r.durability_score, 0) },
            { key: "horizon", label: "Horizon", render: (r) => r.horizon ? <Badge text={r.horizon} /> : "—" },
            { key: "conviction", label: "Conviction", render: (r) => r.conviction ? <Badge text={r.conviction} /> : "—" },
            { key: "confluence", label: "Confl.", align: "right" },
            {
              key: "strategies_fired", label: "Strategies", render: (r) => (
                <span className="flex gap-1 flex-wrap">
                  {String(r.strategies_fired || "").split(",").filter(Boolean).map((sname: string) => (
                    <Badge key={sname} text={STRATEGY_INFO[sname.trim()]?.name ?? sname.trim()} tone="OK" />
                  ))}
                  {!r.strategies_fired && <span className="text-[10px] text-slate-600">—</span>}
                </span>
              ),
            },
            { key: "price", label: "Price", align: "right", render: (r) => fmtINR(r.price) },
          ]}
        />
      </Panel>

      <UniverseFunnel />

      <Panel title="Universe (manual CSV upload — optional)"
        subtitle="The Saturday auto-refresh syncs the scraped Screener pipeline into this book's universe. You can still upload Screener.in exports manually: Query A = non-financials, Query B = banks & NBFCs.">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[10px] text-slate-500 uppercase font-semibold">
            Query A (non-financials)
            <input ref={fileA} type="file" accept=".csv"
              className="block mt-1 text-xs text-slate-400 file:mr-2 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-300" />
          </label>
          <label className="text-[10px] text-slate-500 uppercase font-semibold">
            Query B (banks/NBFCs)
            <input ref={fileB} type="file" accept=".csv"
              className="block mt-1 text-xs text-slate-400 file:mr-2 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-300" />
          </label>
          <Btn kind="primary" busy={busy === "upload"} onClick={uploadCSV}><Upload size={11} /> Upload & Filter</Btn>
        </div>
      </Panel>
    </div>
  );
}
