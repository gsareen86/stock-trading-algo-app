import { useEffect, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { Zap, ShieldCheck } from "lucide-react";
import { fmtPct, fmtNum, fmtIST, getJSON, postJSON } from "../api";
import { Panel, StatCard, useApi, Badge, DataTable, EmptyState, Help, toast, Btn, RefreshBtn } from "../components/ui";

/* ── Backtest lab ─────────────────────────────────────────────────────── */

function BacktestLab() {
  const [form, setForm] = useState({ tickers: "", years: 2, min_trend_score: 60, walk_forward: false, max_tickers: 20 });
  const [job, setJob] = useState<any>({ state: "idle" });

  const poll = async () => { try { setJob(await getJSON("/api/backtest/status")); } catch { /* server away */ } };
  useEffect(() => { poll(); }, []);
  useEffect(() => {
    if (job.state !== "running") return;
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, [job.state]);

  const start = async () => {
    try {
      const r = await postJSON("/api/backtest/run", { ...form, tickers: form.tickers || null });
      toast(r.message);
      if (r.success) setJob({ state: "running", progress: "starting" });
    } catch (e: any) { toast(`Backtest failed to start: ${e.message}`); }
  };

  const res = job.state === "done" ? job.result : null;
  return (
    <Panel title="Backtest Lab" subtitle="Replays the live swing rules (signals, risk sizing, hard stop, +2R partial, EMA trail, time stop, real costs) on historical daily candles. Walk-forward picks parameters on a train window and reports out-of-sample results — those are the numbers to trust. Validates the timing layer only; fundamental pillars and the LLM veto have no historical snapshot.">
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <label className="text-[10px] text-slate-500 uppercase font-semibold">
          Tickers (blank = swing universe)
          <input value={form.tickers} onChange={(e) => setForm({ ...form, tickers: e.target.value })}
            placeholder="RELIANCE,TCS,INFY"
            className="block mt-1 bg-slate-900/70 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono outline-none w-56 uppercase" />
        </label>
        <label className="text-[10px] text-slate-500 uppercase font-semibold">
          Years
          <input type="number" min={1} max={5} value={form.years} onChange={(e) => setForm({ ...form, years: Number(e.target.value) })}
            className="block mt-1 bg-slate-900/70 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono outline-none w-16" />
        </label>
        <label className="text-[10px] text-slate-500 uppercase font-semibold">
          Min Score
          <input type="number" value={form.min_trend_score} onChange={(e) => setForm({ ...form, min_trend_score: Number(e.target.value) })}
            className="block mt-1 bg-slate-900/70 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono outline-none w-20" />
        </label>
        <label className="flex items-center gap-2 text-[10px] text-slate-400 uppercase font-semibold pb-2">
          <input type="checkbox" checked={form.walk_forward} onChange={(e) => setForm({ ...form, walk_forward: e.target.checked })} />
          Walk-forward
        </label>
        <Btn kind="primary" busy={job.state === "running"} onClick={start}><Zap size={11} /> Run Backtest</Btn>
        {job.state === "running" && <span className="text-[10px] text-amber-400 pb-2 font-mono">{job.progress}… (first run downloads price history — can take a few minutes)</span>}
        {job.state === "error" && <span className="text-[10px] text-rose-400 pb-2 font-mono">{job.error}</span>}
      </div>

      {res?.mode === "single" && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
            <StatCard label="Return" value={fmtPct(res.metrics.total_return_pct)} tone={res.metrics.total_return_pct >= 0 ? "good" : "bad"} />
            <StatCard label="CAGR" value={fmtPct(res.metrics.cagr_pct)} />
            <StatCard label="Sharpe" value={fmtNum(res.metrics.sharpe)} tone="accent" />
            <StatCard label="Max DD" value={fmtPct(res.metrics.max_dd_pct)} tone="bad" />
            <StatCard label="Trades" value={res.metrics.n_round_trips} sub={`${fmtNum(res.metrics.avg_hold_days, 0)}d avg hold`} />
            <StatCard label="Win Rate" value={fmtPct(res.metrics.win_rate_pct, 0)} />
            <StatCard label="Profit Factor" value={fmtNum(res.metrics.profit_factor)} />
          </div>
          <div className="h-52 text-[10px] font-mono">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={(res.equity_curve ?? []).map(([d, v]: any) => ({ d, v }))} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <defs>
                  <linearGradient id="btEq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                <XAxis dataKey="d" stroke="#475569" minTickGap={50} />
                <YAxis stroke="#475569" domain={["auto", "auto"]} />
                <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                <Area type="monotone" dataKey="v" name="Equity ₹" stroke="#10b981" strokeWidth={2} fill="url(#btEq)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <DataTable
            rows={res.trades ?? []}
            searchKeys={["ticker", "reason", "side"]}
            maxHeight="280px"
            cols={[
              { key: "dt", label: "Date" },
              { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
              { key: "side", label: "Side", render: (r) => <Badge text={r.side} /> },
              { key: "qty", label: "Qty", align: "right" },
              { key: "price", label: "Price", align: "right" },
              { key: "pnl", label: "P&L", align: "right", render: (r) => <span className={r.pnl > 0 ? "text-emerald-400" : r.pnl < 0 ? "text-rose-400" : "text-slate-400"}>{fmtNum(r.pnl)}</span> },
              { key: "reason", label: "Reason" },
            ]}
          />
        </div>
      )}

      {res?.mode === "walk_forward" && (
        <div className="space-y-3">
          {res.oos && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="OOS Return" value={fmtPct(res.oos.total_return_pct)} tone={res.oos.total_return_pct >= 0 ? "good" : "bad"} sub="Out-of-sample — the honest number" />
              <StatCard label="OOS Sharpe" value={fmtNum(res.oos.sharpe)} tone="accent" />
              <StatCard label="OOS Max DD" value={fmtPct(res.oos.max_dd_pct)} tone="bad" />
              <StatCard label="Folds" value={res.oos.n_folds} />
            </div>
          )}
          <DataTable
            rows={res.folds ?? []}
            maxHeight="280px"
            cols={[
              { key: "test", label: "Test Window" },
              { key: "chosen_params", label: "Chosen Params", render: (r) => <span className="text-[10px]">{JSON.stringify(r.chosen_params)}</span> },
              { key: "train_sharpe", label: "Train Sharpe", align: "right" },
              { key: "test_metrics", label: "Test (OOS)", render: (r) => <span className="text-[10px]">{`ret ${fmtPct(r.test_metrics?.total_return_pct)} · sharpe ${fmtNum(r.test_metrics?.sharpe)} · dd ${fmtPct(r.test_metrics?.max_dd_pct)}`}</span> },
            ]}
          />
        </div>
      )}
    </Panel>
  );
}

/* ── Hygiene checker ──────────────────────────────────────────────────── */

function HygieneChecker() {
  const [ticker, setTicker] = useState("");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const check = async () => {
    if (!ticker.trim()) return;
    setBusy(true);
    try { setResult(await getJSON(`/api/engine/hygiene/${ticker.trim().toUpperCase()}`)); }
    catch (e: any) { toast(`Check failed: ${e.message}`); }
    setBusy(false);
  };

  return (
    <Panel title="Hygiene & Event Check" subtitle="Run any ticker through the exact gates an entry must pass: ASM/GSM surveillance, liquidity, and upcoming results/ex-dates.">
      <div className="flex items-center gap-2">
        <input value={ticker} onChange={(e) => setTicker(e.target.value)} onKeyDown={(e) => e.key === "Enter" && check()}
          placeholder="RELIANCE" className="bg-slate-900/70 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono outline-none w-36 uppercase" />
        <Btn kind="primary" busy={busy} onClick={check}><ShieldCheck size={12} /> Check</Btn>
      </div>
      {result && (
        <div className="mt-3 space-y-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-100">{result.ticker}</span>
            <Badge text={result.passed ? "PASSES GATES" : "BLOCKED"} tone={result.passed ? "OK" : "FAIL"} />
            {result.median_traded_value_cr != null && (
              <span className="text-slate-400 font-mono">median traded ₹{fmtNum(result.median_traded_value_cr, 1)} Cr/day</span>
            )}
          </div>
          {result.reasons?.length > 0 && <div className="text-rose-400">{result.reasons.join(" · ")}</div>}
          {result.notes?.length > 0 && <div className="text-slate-500">{result.notes.join(" · ")}</div>}
          {result.upcoming_events?.length > 0 ? (
            <div className="text-amber-400">
              Upcoming events: {result.upcoming_events.map((e: any) => `${e.event_type} on ${e.event_date}`).join(" · ")}
            </div>
          ) : <div className="text-slate-500">No known events in the guard window.</div>}
        </div>
      )}
    </Panel>
  );
}

/* ── Main page ────────────────────────────────────────────────────────── */

export default function EngineRoom() {
  const outcomes = useApi<any>("/api/engine/outcomes/summary");
  const recent = useApi<any[]>("/api/engine/outcomes?limit=100");
  const calib = useApi<any>("/api/engine/calibration");
  const events = useApi<any>("/api/engine/events?days=14");
  const surv = useApi<any>("/api/engine/surveillance");
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (label: string, path: string, after?: () => void) => {
    setBusy(path);
    try { const r = await postJSON(path, {}); toast(`${label}: ${r.message ?? "started"}`); setTimeout(() => after?.(), 2500); }
    catch (e: any) { toast(`${label} failed: ${e.message}`); }
    setBusy(null);
  };

  const summary: any[] = outcomes.data?.summary ?? [];
  const cal = calib.data;

  return (
    <div className="space-y-6">
      <Help text="The feedback machinery of the engine. Outcomes attach forward returns to every signal so you can see — empirically — whether scores, verdicts and alerts predict anything. Calibration turns that into threshold recommendations (advisory only, and only after 200+ samples). The backtest lab replays the swing rules on history. The calendars power the entry guards." />

      {/* Outcomes */}
      <Panel title="Signal Outcomes" subtitle="Forward 5/20/60-day returns attached to every scan, research verdict and news alert. 'Hit rate' = share with positive 20-day return."
        actions={
          <div className="flex gap-2">
            <Btn busy={busy === "/api/engine/outcomes/run"} onClick={() => run("Outcomes", "/api/engine/outcomes/run", () => { outcomes.reload(); recent.reload(); })}>
              <Zap size={11} /> Compute Now
            </Btn>
            <RefreshBtn onClick={() => { outcomes.reload(); recent.reload(); }} loading={outcomes.loading} />
          </div>
        }>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <StatCard label="Outcomes Tracked" value={outcomes.data?.total ?? 0} sub={`${outcomes.data?.incomplete ?? 0} awaiting more trading days`} />
          {summary.map((s: any) => (
            <StatCard key={s.signal_type} label={s.signal_type} value={`${fmtNum((s.hit_rate_20d ?? 0) * 100, 0)}% hit`}
              tone={(s.hit_rate_20d ?? 0) >= 0.5 ? "good" : "bad"}
              sub={`n=${s.n} · avg 20d ${fmtPct(s.avg_20d)}`} />
          ))}
        </div>
        <DataTable
          rows={recent.data ?? []}
          searchKeys={["ticker", "signal_type"]}
          maxHeight="280px"
          empty={<EmptyState>No outcomes yet. They accrue automatically after each EOD scan once signals are ≥5 trading days old — or press "Compute Now".</EmptyState>}
          cols={[
            { key: "signal_ts", label: "Signal Time", render: (r) => fmtIST(r.signal_ts) },
            { key: "signal_type", label: "Type", render: (r) => <Badge text={r.signal_type} tone="INFO" /> },
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "ref_price", label: "Ref ₹", align: "right" },
            { key: "fwd_ret_5d", label: "+5d", align: "right", render: (r) => <span className={r.fwd_ret_5d > 0 ? "text-emerald-400" : r.fwd_ret_5d < 0 ? "text-rose-400" : ""}>{fmtPct(r.fwd_ret_5d)}</span> },
            { key: "fwd_ret_20d", label: "+20d", align: "right", render: (r) => <span className={r.fwd_ret_20d > 0 ? "text-emerald-400" : r.fwd_ret_20d < 0 ? "text-rose-400" : ""}>{fmtPct(r.fwd_ret_20d)}</span> },
            { key: "fwd_ret_60d", label: "+60d", align: "right", render: (r) => <span className={r.fwd_ret_60d > 0 ? "text-emerald-400" : r.fwd_ret_60d < 0 ? "text-rose-400" : ""}>{fmtPct(r.fwd_ret_60d)}</span> },
          ]}
        />
      </Panel>

      {/* Calibration */}
      <Panel title="Calibration Report" subtitle="Did higher scores actually earn higher returns? Advisory only — nothing is auto-applied."
        actions={<RefreshBtn onClick={calib.reload} loading={calib.loading} />}>
        {cal && (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <Badge text={cal.status === "ok" ? "ENOUGH DATA" : "COLLECTING DATA"} tone={cal.status === "ok" ? "OK" : "PENDING"} />
              <span className="text-xs text-slate-400 font-mono">{cal.outcomes_with_20d} / {cal.min_required} outcomes with 20-day returns</span>
            </div>
            {cal.recommendation && (
              <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 text-emerald-300 text-xs">
                Suggested minimum entry score: <b>{cal.recommendation.suggested_min_score}</b> (band {cal.recommendation.based_on_band?.band}: {cal.recommendation.based_on_band?.hit_rate_pct}% hit rate, avg {fmtPct(cal.recommendation.based_on_band?.avg_fwd_20d_pct)})
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {[["Scan score bands", cal.scan_score_bands, "band"],
                ["Research verdicts", cal.research_verdicts, "verdict"],
                ["Alert severities", cal.news_alert_severity, "severity"]].map(([title, rows, key]: any) => (
                <div key={title} className="bg-slate-900/50 border border-slate-800/70 rounded-xl p-3">
                  <div className="text-[10px] text-slate-500 font-semibold uppercase mb-2">{title}</div>
                  {(rows ?? []).length === 0 ? <div className="text-[10px] text-slate-600">no data yet</div> : (
                    <table className="w-full text-[10px] font-mono">
                      <tbody>
                        {rows.map((b: any, i: number) => (
                          <tr key={i} className="text-slate-300">
                            <td className="py-0.5">{b[key]}</td>
                            <td className="text-right">n={b.n}</td>
                            <td className={`text-right ${b.avg_fwd_20d_pct > 0 ? "text-emerald-400" : "text-rose-400"}`}>{fmtPct(b.avg_fwd_20d_pct)}</td>
                            <td className="text-right">{b.hit_rate_pct}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              ))}
            </div>
            <div className="text-[10px] text-slate-500">{(cal.notes ?? []).join(" · ")}</div>
          </div>
        )}
      </Panel>

      <BacktestLab />
      <HygieneChecker />

      {/* Calendars */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Event Calendar (next 14 days)" subtitle="NSE results & ex-dates. Swing entries are blocked within 3 days of these."
          actions={
            <div className="flex gap-2">
              <Btn busy={busy === "/api/engine/events/refresh"} onClick={() => run("Calendar", "/api/engine/events/refresh", events.reload)}>Refresh from NSE</Btn>
              <RefreshBtn onClick={events.reload} loading={events.loading} />
            </div>
          }>
          <div className="text-[10px] text-slate-500 mb-2">Last fetched: {fmtIST(events.data?.last_refreshed)}</div>
          <DataTable
            rows={events.data?.rows ?? []}
            searchKeys={["ticker", "event_type"]}
            maxHeight="260px"
            empty={<EmptyState>Calendar is empty — press "Refresh from NSE". (If NSE blocks the request the guard simply stays inactive: fail-open by design.)</EmptyState>}
            cols={[
              { key: "event_date", label: "Date" },
              { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
              { key: "event_type", label: "Event", render: (r) => <Badge text={r.event_type} tone={["results", "board_meeting"].includes(r.event_type) ? "WARNING" : "INFO"} /> },
              { key: "source", label: "Source" },
            ]}
          />
        </Panel>

        <Panel title="ASM / GSM Surveillance" subtitle="Names under NSE surveillance — blocked by the hygiene gate."
          actions={
            <div className="flex gap-2">
              <Btn busy={busy === "/api/engine/surveillance/refresh"} onClick={() => run("Surveillance", "/api/engine/surveillance/refresh", surv.reload)}>Refresh from NSE</Btn>
              <RefreshBtn onClick={surv.reload} loading={surv.loading} />
            </div>
          }>
          <div className="text-[10px] text-slate-500 mb-2">Last fetched: {fmtIST(surv.data?.last_refreshed)}</div>
          <DataTable
            rows={surv.data?.rows ?? []}
            searchKeys={["ticker", "list_type"]}
            maxHeight="260px"
            empty={<EmptyState>No surveillance entries loaded — press "Refresh from NSE". A name KNOWN to be listed is always blocked; an empty list never blocks.</EmptyState>}
            cols={[
              { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
              { key: "list_type", label: "List", render: (r) => <Badge text={r.list_type} tone="FAIL" /> },
              { key: "stage", label: "Stage" },
              { key: "fetched_at", label: "Fetched", render: (r) => fmtIST(r.fetched_at) },
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
