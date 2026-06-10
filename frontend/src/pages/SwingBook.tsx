import { useEffect, useRef, useState } from "react";
import { Upload, Zap, X, Microscope } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { fmtINR, fmtPct, pnlClass, fmtIST, fmtNum, getJSON, postJSON, postForm } from "../api";
import { Panel, StatCard, useApi, Badge, DataTable, EmptyState, Help, toast, Btn, RefreshBtn } from "../components/ui";

/* What each swing strategy looks for — shown in the per-ticker inspector so
   "strategies_fired" is a story, not a code name. */
const STRATEGY_INFO: Record<string, { name: string; desc: string; hold: string }> = {
  minervini_vcp: {
    name: "Minervini VCP",
    desc: "Stage-2 uptrend (price > rising 50/150/200 MAs, near 52-week high) plus a Volatility Contraction Pattern: successive pullbacks get tighter while volume dries up — supply is exhausted. Entry is the breakout from the final tight pivot.",
    hold: "~18 trading days",
  },
  brahma_vishnu_mahesh: {
    name: "Brahma-Vishnu-Mahesh",
    desc: "Multi-timeframe trend alignment: creation (base), preservation (trend intact across timeframes) and momentum legs must agree, gated by a market-health filter. Rides established trends rather than catching breakouts.",
    hold: "~30 trading days",
  },
  fun_tech_momentum: {
    name: "Fundamental-Technical Momentum",
    desc: "CANSLIM-style: strong earnings/sales acceleration combined with a tight technical range near highs. The fundamental engine confirms the move is earned, the technical setup times the entry.",
    hold: "~15 trading days",
  },
  young_momentum: {
    name: "Young Momentum",
    desc: "A fresh 20–50% impulse leg followed by a short, shallow pause (≤6 bars, retracing less than 38.2%). Enters the continuation while the move is still young — momentum begets momentum.",
    hold: "~10 trading days",
  },
};

function PillarBar({ label, value }: { label: string; value: number | null | undefined }) {
  const v = value == null ? null : Math.max(0, Math.min(100, Number(value)));
  const color = v == null ? "#334155" : v >= 70 ? "#10b981" : v >= 50 ? "#6366f1" : v >= 35 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className="w-24 text-slate-500 uppercase tracking-wider font-semibold">{label}</span>
      <div className="flex-1 h-2 bg-slate-800/80 rounded-full overflow-hidden">
        {v != null && <div className="h-full rounded-full" style={{ width: `${v}%`, background: color }} />}
      </div>
      <span className="w-8 text-right font-mono text-slate-300">{v == null ? "—" : Math.round(v)}</span>
    </div>
  );
}

/* Per-ticker inspector: why the strategies fired + scorecard + price chart */
function ScanInspector({ row, onClose }: { row: any; onClose: () => void }) {
  const [series, setSeries] = useState<any[] | null>(null);
  useEffect(() => {
    let alive = true;
    setSeries(null);
    getJSON(`/api/fundamentals/price-history/${row.ticker}?period=1Y`)
      .then((d) => {
        if (!alive) return;
        const rows = d.series ?? [];
        // 21-EMA computed client-side (the endpoint provides 50/200 DMA)
        let ema = rows.length ? Number(rows[0].close) : 0;
        const k = 2 / 22;
        for (const p of rows) {
          ema = p.close * k + ema * (1 - k);
          p.ema21 = Math.round(ema * 100) / 100;
        }
        setSeries(rows);
      })
      .catch(() => alive && setSeries([]));
    return () => { alive = false; };
  }, [row.ticker]);

  const fired = String(row.strategies_fired || "").split(",").map((s) => s.trim()).filter(Boolean);

  return (
    <div className="bg-slate-950/70 border border-indigo-500/25 rounded-2xl p-4 space-y-4">
      <div className="flex items-center gap-3">
        <Microscope size={15} className="text-indigo-400" />
        <span className="font-bold text-slate-100">{row.ticker}</span>
        <Badge text={row.alert_type} />
        {row.horizon && <Badge text={row.horizon} />}
        {row.conviction && <Badge text={row.conviction} />}
        <span className="text-[10px] text-slate-500">scanned {fmtIST(row.scanned_at)} @ {fmtINR(row.price)}</span>
        <span className="flex-1" />
        <button onClick={onClose} className="text-slate-500 hover:text-slate-200"><X size={15} /></button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Left: strategies + why */}
        <div className="space-y-3">
          <div>
            <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1.5">
              Strategies that fired ({fired.length || 0})
            </div>
            {fired.length === 0 ? (
              <div className="text-[11px] text-slate-500">No strategy fired — this row is a WATCH/HOLD scored on the trend template alone.</div>
            ) : (
              <div className="space-y-2">
                {fired.map((key) => {
                  const info = STRATEGY_INFO[key];
                  return (
                    <div key={key} className="bg-slate-900/60 border border-slate-800/70 rounded-lg p-2.5">
                      <div className="flex items-center gap-2">
                        <Badge text={info?.name ?? key} tone="OK" />
                        <span className="text-[9px] text-slate-500">expected hold {info?.hold ?? "—"}</span>
                      </div>
                      <p className="text-[10px] text-slate-400 mt-1.5 mb-0 leading-relaxed">{info?.desc ?? ""}</p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div>
            <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1.5">Scan detail (trend template + VCP read)</div>
            <p className="text-[10px] text-slate-400 font-mono leading-relaxed whitespace-pre-wrap m-0 bg-slate-900/50 rounded-lg p-2.5 border border-slate-800/60">{row.reason || "—"}</p>
          </div>
          <div className="space-y-1.5">
            <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1.5">Scorecard pillars</div>
            <PillarBar label="Timing" value={row.timing_score} />
            <PillarBar label="Durability" value={row.durability_score} />
            <PillarBar label="Quality" value={row.quality_pillar} />
            <PillarBar label="Valuation" value={row.valuation_pillar} />
            <PillarBar label="Momentum" value={row.momentum_pillar} />
            <PillarBar label="Sentiment" value={row.sentiment_pillar} />
            <PillarBar label="Management" value={row.management_pillar} />
          </div>
        </div>

        {/* Right: 1Y chart with the MAs the strategies actually use */}
        <div>
          <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1.5">
            1-year price · 21-EMA (trail) · 50/200 DMA (trend template)
          </div>
          <div className="h-72 text-[10px] font-mono">
            {series === null ? (
              <div className="h-full flex items-center justify-center text-slate-500 text-xs">loading chart…</div>
            ) : series.length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-500 text-xs">price history unavailable</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                  <XAxis dataKey="ts" stroke="#475569" minTickGap={50} />
                  <YAxis stroke="#475569" domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                  <Legend wrapperStyle={{ fontSize: "10px" }} />
                  <Line type="monotone" dataKey="close" name="Close" stroke="#e2e8f0" strokeWidth={1.6} dot={false} />
                  <Line type="monotone" dataKey="ema21" name="21 EMA" stroke="#f59e0b" strokeWidth={1} dot={false} />
                  <Line type="monotone" dataKey="sma50" name="50 DMA" stroke="#6366f1" strokeWidth={1} dot={false} />
                  <Line type="monotone" dataKey="sma200" name="200 DMA" stroke="#ef4444" strokeWidth={1} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
    </div>
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

      <Panel title="Open Swing Positions" subtitle="Hard stop / EMA trail / time stop per position. 'Partial' shows whether the +2R de-risk has fired (stop then sits at breakeven)."
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
