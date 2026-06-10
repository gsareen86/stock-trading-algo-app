import { useState } from "react";
import { Play, Pause, Zap } from "lucide-react";
import { postJSON, putJSON, fmtINR, fmtIST } from "../api";
import { Panel, useApi, Btn, Badge, DataTable, EmptyState, Help, toast, RefreshBtn } from "../components/ui";

/* Every manual trigger in the system lives here, each with a one-line
   explanation of what it does and where to see its result. */
const ACTIONS: { label: string; path: string; desc: string }[] = [
  { label: "Run Intraday Cycle", path: "/api/bot/cycle/run", desc: "One full 15-min scan cycle now (signals → entries/exits). Result: Intraday page + cycle log below." },
  { label: "Run EOD Swing Scan", path: "/api/positional/scan", desc: "Scan the universe with all 4 swing strategies + scorecard. Result: Swing Book page." },
  { label: "Run Swing Exit Check", path: "/api/positional/exit-check", desc: "Evaluate stops / partials / time stops on open swing positions now." },
  { label: "Refresh LLM Research", path: "/api/positional/research/refresh", desc: "Re-run concall research on holdings + watchlist. Result: Research page." },
  { label: "Run News-Impact Pass", path: "/api/alerts/run", desc: "LLM triage of recent news against holdings/watchlist. Result: News & Alerts page." },
  { label: "Scrape News Now", path: "/api/news/scrape", desc: "Pull the 7 RSS feeds and tag tickers. Result: News & Alerts page." },
  { label: "Sync Universe (Screener→Swing)", path: "/api/positional/universe/sync", desc: "Push lt_universe survivors through hygiene gates into the swing universe. Result: Swing Book → Universe." },
  { label: "Refresh Event Calendar", path: "/api/engine/events/refresh", desc: "Fetch NSE results/ex-dates (powers the entry event-guard). Result: Engine Room." },
  { label: "Refresh ASM/GSM Lists", path: "/api/engine/surveillance/refresh", desc: "Fetch NSE surveillance lists (powers the hygiene gate). Result: Engine Room." },
  { label: "Compute Outcomes", path: "/api/engine/outcomes/run", desc: "Attach forward returns to past signals. Result: Engine Room → Outcomes." },
  { label: "Run LT Book Pass", path: "/api/longterm/book/run", desc: "Tranches / thesis-stops for the Long-Term book (no-op while disabled)." },
];

export default function Control() {
  const status = useApi<any>("/api/bot/status");
  const approvals = useApi<any[]>("/api/approvals");
  const cycles = useApi<any[]>("/api/bot/cycles?limit=15");
  const [busy, setBusy] = useState<string | null>(null);
  const [params, setParams] = useState<any | null>(null);

  const s = status.data;
  const p = params ?? s?.params;

  const act = async (label: string, path: string) => {
    setBusy(path);
    try {
      const r = await postJSON(path, {});
      toast(`${label}: ${r.message ?? "started"}`);
    } catch (e: any) { toast(`${label} failed: ${e.message}`); }
    setBusy(null);
  };

  const setBot = async (st: string, mode?: string) => {
    try {
      await postJSON("/api/bot/control", { status: st, mode: mode ?? s?.mode ?? "auto" });
      toast(`Bot ${st}${mode ? ` · mode=${mode}` : ""}`);
      status.reload();
    } catch (e: any) { toast(`Control failed: ${e.message}`); }
  };

  const saveParams = async () => {
    try {
      await putJSON("/api/bot/parameters", p);
      toast("Parameters saved — applied from the next cycle");
      setParams(null); status.reload();
    } catch (e: any) { toast(`Save failed: ${e.message}`); }
  };

  const decide = async (id: number, action: string) => {
    try {
      const r = await postJSON(`/api/approvals/${id}/decide`, { action, note: "dashboard" });
      toast(r.message); approvals.reload();
    } catch (e: any) { toast(`Decision failed: ${e.message}`); }
  };

  return (
    <div className="space-y-6">
      {/* Bot state */}
      <Panel title="Bot Control" subtitle="The intraday scheduler. Swing & LT books run on their own EOD timetable regardless of this switch."
        actions={<RefreshBtn onClick={status.reload} loading={status.loading} />}>
        <div className="flex flex-wrap items-center gap-3">
          <Badge text={s?.status ?? "…"} />
          <Badge text={s?.market_open ? "MARKET OPEN" : "MARKET CLOSED"} tone={s?.market_open ? "OK" : "PENDING"} />
          <span className="text-xs text-slate-500 font-mono">{s?.market_time_ist}</span>
          <div className="flex-1" />
          {s?.status === "RUNNING"
            ? <Btn kind="danger" onClick={() => setBot("STOPPED")}><Pause size={12} /> Stop</Btn>
            : <Btn kind="primary" onClick={() => setBot("RUNNING")}><Play size={12} /> Start</Btn>}
          <div className="flex items-center gap-1 bg-slate-900/70 border border-slate-700/60 rounded-lg p-1">
            {["auto", "manual", "dry_run"].map((m) => (
              <button key={m} onClick={() => setBot(s?.status ?? "STOPPED", m)}
                className={`px-2.5 py-1 rounded-md text-[10px] font-semibold uppercase ${s?.mode === m ? "grad-primary text-white" : "text-slate-400 hover:text-slate-200"}`}>
                {m}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-2 text-[10px] text-slate-500">
          auto = executes signals itself · manual = every signal waits in the approval queue below · dry_run = log signals only, no positions
        </div>
        {s?.last_cycle && (
          <div className="mt-3 text-[11px] text-slate-400 font-mono bg-slate-900/50 rounded-lg p-3 border border-slate-800/60">
            Last cycle {fmtIST(s.last_cycle.started_at)} · <Badge text={s.last_cycle.status} /> ·{" "}
            {typeof s.last_cycle.summary === "object" && s.last_cycle.summary
              ? `signals=${s.last_cycle.summary.signals ?? "—"} placed=${(s.last_cycle.summary.placed_long ?? 0) + (s.last_cycle.summary.placed_short ?? 0)} closed=${s.last_cycle.summary.closed ?? 0} regime=${s.last_cycle.summary.regime ?? "—"}`
              : ""}
          </div>
        )}
      </Panel>

      {/* Parameters */}
      <Panel title="Risk Parameters" subtitle="Live-editable; the scheduler reads these from the DB on every cycle.">
        {p && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              { k: "max_open_positions", label: "Max Positions", step: 1 },
              { k: "risk_per_trade_pct", label: "Risk / Trade", step: 0.005 },
              { k: "stop_loss_pct", label: "Stop-Loss %", step: 0.005 },
              { k: "take_profit_pct", label: "Take-Profit %", step: 0.01 },
              { k: "min_composite_score", label: "Min Score", step: 5 },
            ].map((f) => (
              <label key={f.k} className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                {f.label}
                <input type="number" step={f.step} value={p[f.k] ?? ""}
                  onChange={(e) => setParams({ ...p, [f.k]: Number(e.target.value) })}
                  className="mt-1 w-full bg-slate-900/70 border border-slate-700/60 rounded-lg px-2 py-1.5 text-xs text-slate-200 font-mono outline-none focus:border-indigo-500/50" />
              </label>
            ))}
          </div>
        )}
        <div className="mt-3 flex gap-2">
          <Btn kind="primary" onClick={saveParams} disabled={!params}>Save Parameters</Btn>
          {params && <Btn onClick={() => setParams(null)}>Discard</Btn>}
        </div>
      </Panel>

      {/* Approval queue */}
      <Panel title="Approval Queue" subtitle="Signals waiting for your decision (manual mode). They expire automatically after 10 minutes."
        actions={<RefreshBtn onClick={approvals.reload} loading={approvals.loading} />}>
        <DataTable
          rows={approvals.data ?? []}
          empty={<EmptyState>Nothing pending. Switch mode to <b>manual</b> if you want to approve every trade yourself.</EmptyState>}
          cols={[
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "side", label: "Side", render: (r) => <Badge text={r.side} /> },
            { key: "quantity", label: "Qty", align: "right" },
            { key: "price", label: "Price", align: "right", render: (r) => fmtINR(r.price) },
            { key: "composite_score", label: "Score", align: "right" },
            { key: "strategy", label: "Strategy" },
            { key: "remaining_seconds", label: "Expires", render: (r) => `${Math.floor(r.remaining_seconds / 60)}m ${r.remaining_seconds % 60}s` },
            {
              key: "id", label: "Decision", render: (r) => (
                <span className="flex gap-1.5">
                  <Btn kind="primary" onClick={() => decide(r.id, "APPROVE")}>Approve</Btn>
                  <Btn kind="danger" onClick={() => decide(r.id, "REJECT")}>Reject</Btn>
                </span>
              ),
            },
          ]}
        />
      </Panel>

      {/* Manual triggers */}
      <Panel title="Manual Triggers" subtitle="Everything that normally runs on a schedule can be kicked off here. Each runs in the background — watch the toast, then check the page named in its description.">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {ACTIONS.map((a) => (
            <div key={a.path} className="bg-slate-900/50 border border-slate-800/70 rounded-xl p-3 flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-200">{a.label}</span>
                <Btn kind="ghost" busy={busy === a.path} onClick={() => act(a.label, a.path)}>
                  <Zap size={11} /> Run
                </Btn>
              </div>
              <span className="text-[10px] text-slate-500 leading-snug">{a.desc}</span>
            </div>
          ))}
        </div>
      </Panel>

      {/* Cycle log */}
      <Panel title="Recent Scheduler Cycles" subtitle="What the intraday loop did on each pass."
        actions={<RefreshBtn onClick={cycles.reload} loading={cycles.loading} />}>
        <DataTable
          rows={cycles.data ?? []}
          empty={<EmptyState>No cycles recorded yet — start the bot or trigger one manually above.</EmptyState>}
          cols={[
            { key: "started_at", label: "Started", render: (r) => fmtIST(r.started_at) },
            { key: "status", label: "Status", render: (r) => <Badge text={r.status} /> },
            { key: "triggered_by", label: "Trigger" },
            { key: "summary", label: "Summary", render: (r) => <span className="text-[10px] text-slate-400 whitespace-normal break-all">{typeof r.summary === "string" ? r.summary.slice(0, 160) : JSON.stringify(r.summary ?? {}).slice(0, 160)}</span> },
          ]}
        />
      </Panel>

      <Help text="Tip: a typical manual validation pass is — Scrape News → Run News-Impact Pass → Run EOD Swing Scan → check the Swing Book and News & Alerts pages, then Compute Outcomes and open the Engine Room." />
    </div>
  );
}
