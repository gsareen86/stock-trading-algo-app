import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { fmtINR, fmtPct, pnlClass } from "../api";
import { Panel, StatCard, useApi, Spinner, ErrorState, EmptyState, Badge, DataTable, Help } from "../components/ui";

export default function Overview({ go }: { go: (page: string) => void }) {
  const summary = useApi<any>("/api/portfolio/summary");
  const curve = useApi<any>("/api/portfolio/equity-curve?days=60");
  const dd = useApi<any>("/api/portfolio/drawdown");
  const open = useApi<any[]>("/api/positions/open");
  const swing = useApi<any>("/api/positional/status");
  const lt = useApi<any>("/api/longterm/book/status");

  const s = summary.data;
  return (
    <div className="space-y-6">
      <Help text="One snapshot of all three books. Intraday trades 15-min candles and squares off daily; the Swing book holds days-to-weeks from EOD scans; the Long-Term book accumulates durable compounders in tranches. Each book has its own capital pool and its own page." />

      {/* Intraday pool */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Intraday — Total Value" value={fmtINR(s?.total_value)} tone="accent"
          sub={`Cash ${fmtINR(s?.cash)} · started at ₹1,00,000`} />
        <StatCard label="Realized P&L" value={<span className={pnlClass(s?.realized_pnl)}>{fmtINR(s?.realized_pnl)}</span>}
          sub="Booked on closed trades" />
        <StatCard label="Unrealized P&L" value={<span className={pnlClass(s?.live_unrealized_pnl ?? s?.unrealized_pnl)}>{fmtINR(s?.live_unrealized_pnl ?? s?.unrealized_pnl)}</span>}
          sub="Open positions, marked to live prices" />
        <StatCard label="Total Return" value={<span className={pnlClass(s?.total_return_pct)}>{fmtPct(s?.total_return_pct)}</span>}
          sub={`Sharpe ${s?.sharpe ?? "—"} · MaxDD ${fmtPct(s?.max_dd_pct)}`} />
      </div>

      {/* Other two books */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <button onClick={() => go("swing")} className="text-left">
          <div className="glass-panel glass-panel-hover rounded-2xl p-4 flex items-center justify-between cursor-pointer">
            <div>
              <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Swing Book</div>
              <div className="text-lg font-bold font-mono text-slate-100 mt-1">
                {swing.data ? `${swing.data.active_positions ?? swing.data.open_positions ?? 0} open · cash ${fmtINR(swing.data.cash_balance)}` : "—"}
              </div>
              <div className="text-[10px] text-slate-500 mt-1">
                Net realized {fmtINR(swing.data?.net_realized_pnl)} · open the Swing Book page →
              </div>
            </div>
            <Badge text={swing.data?.enabled === false ? "DISABLED" : "ACTIVE"} />
          </div>
        </button>
        <button onClick={() => go("ltbook")} className="text-left">
          <div className="glass-panel glass-panel-hover rounded-2xl p-4 flex items-center justify-between cursor-pointer">
            <div>
              <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Long-Term Book</div>
              <div className="text-lg font-bold font-mono text-slate-100 mt-1">
                {lt.data ? `${lt.data.open_positions} open · cash ${fmtINR(lt.data.cash)}` : "—"}
              </div>
              <div className="text-[10px] text-slate-500 mt-1">
                {lt.data?.enabled ? `Net realized ${fmtINR(lt.data.net_realized_pnl)}` : "Disabled — enable with LT_BOOK_ENABLED=true in .env"} · details →
              </div>
            </div>
            <Badge text={lt.data?.enabled ? "ACTIVE" : "DISABLED"} />
          </div>
        </button>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Panel title="Equity Curve" subtitle="Intraday portfolio value over the last 60 days" className="lg:col-span-2">
          {curve.loading ? <Spinner /> : curve.error ? <ErrorState error={curve.error} onRetry={curve.reload} /> : (
            <div className="h-64 text-[10px] font-mono">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={curve.data?.portfolio || []} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <defs>
                    <linearGradient id="ovEq" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6366f1" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                  <XAxis dataKey="ts_ist" stroke="#475569" minTickGap={40} />
                  <YAxis stroke="#475569" domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                  <Area type="monotone" dataKey="portfolio_value" name="Portfolio ₹" stroke="#6366f1" strokeWidth={2} fill="url(#ovEq)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>
        <Panel title="Drawdown" subtitle="Decline from the previous portfolio peak (%)">
          {dd.loading ? <Spinner /> : dd.error ? <ErrorState error={dd.error} onRetry={dd.reload} /> : (
            <div className="h-64 text-[10px] font-mono">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={dd.data || []} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <defs>
                    <linearGradient id="ovDD" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                  <XAxis dataKey="ts_ist" stroke="#475569" minTickGap={40} />
                  <YAxis stroke="#475569" domain={["auto", 0]} />
                  <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                  <Area type="monotone" dataKey="drawdown_pct" name="Drawdown %" stroke="#ef4444" strokeWidth={1.5} fill="url(#ovDD)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>
      </div>

      {/* Open intraday positions */}
      <Panel title="Open Intraday Positions" subtitle="Auto square-off at 15:10 IST. Full history on the Intraday page."
        actions={<Badge text={`${open.data?.length ?? 0} open`} tone="INFO" />}>
        {open.loading ? <Spinner /> : (
          <DataTable
            rows={open.data ?? []}
            empty={<EmptyState>No open intraday positions. Start the bot from the Control Center; entries appear here during market hours.</EmptyState>}
            cols={[
              { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
              { key: "side", label: "Side", render: (r) => <Badge text={r.side} /> },
              { key: "quantity", label: "Qty", align: "right" },
              { key: "entry_price", label: "Entry", align: "right", render: (r) => fmtINR(r.entry_price) },
              { key: "current_price", label: "Live", align: "right", render: (r) => fmtINR(r.current_price) },
              { key: "unrealized_pnl", label: "Unrealized", align: "right", render: (r) => <span className={pnlClass(r.unrealized_pnl)}>{fmtINR(r.unrealized_pnl)} ({fmtPct(r.unrealized_pnl_pct)})</span> },
              { key: "stop_loss", label: "Stop", align: "right", render: (r) => fmtINR(r.stop_loss) },
              { key: "strategy", label: "Strategy" },
              { key: "entered_at", label: "Opened", render: (r) => r.entered_at ?? "—" },
            ]}
          />
        )}
      </Panel>
    </div>
  );
}
