import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { fmtINR, fmtPct, fmtNum, pnlClass } from "../api";
import { Panel, StatCard, useApi, DataTable, EmptyState, Help, RefreshBtn } from "../components/ui";

export default function Performance() {
  const summary = useApi<any>("/api/analytics/summary");
  const strategies = useApi<any[]>("/api/analytics/strategies");
  const positional = useApi<any>("/api/positional/analytics");

  const s = summary.data ?? {};
  const stratRows = strategies.data ?? [];
  const p = positional.data ?? {};

  return (
    <div className="space-y-6">
      <Help text="Results across the books, after every cost (brokerage, STT, GST, slippage). Per-strategy attribution shows where the edge actually is — and where it isn't. Cross-check this against the Engine Room's outcome hit-rates before trusting any single number." />

      <Panel title="Intraday Book" actions={<RefreshBtn onClick={summary.reload} loading={summary.loading} />}>
        {(s.total_trades ?? 0) === 0 ? (
          <EmptyState>No completed intraday trades yet — stats appear after the first round-trips close.</EmptyState>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
            <StatCard label="Trades" value={s.total_trades} />
            <StatCard label="Win Rate" value={fmtPct(s.win_rate, 0)} tone={(s.win_rate ?? 0) >= 50 ? "good" : "bad"} />
            <StatCard label="Total P&L" value={<span className={pnlClass(s.total_pnl)}>{fmtINR(s.total_pnl)}</span>} />
            <StatCard label="Profit Factor" value={fmtNum(s.profit_factor)} />
            <StatCard label="Avg Win" value={fmtINR(s.avg_win)} tone="good" />
            <StatCard label="Avg Loss" value={fmtINR(s.avg_loss)} tone="bad" />
            <StatCard label="Best / Worst" value={<span className="text-sm">{fmtINR(s.best_trade)} / {fmtINR(s.worst_trade)}</span>} />
          </div>
        )}
      </Panel>

      <Panel title="P&L by Strategy" subtitle="Which strategies pay for the rest"
        actions={<RefreshBtn onClick={strategies.reload} loading={strategies.loading} />}>
        {stratRows.length === 0 ? (
          <EmptyState>No per-strategy data yet.</EmptyState>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="h-64 text-[10px] font-mono">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stratRows} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                  <XAxis dataKey="strategy" stroke="#475569" angle={-25} textAnchor="end" height={60} />
                  <YAxis stroke="#475569" />
                  <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                  <Bar dataKey="total_pnl" name="Total P&L ₹" radius={[4, 4, 0, 0]}>
                    {stratRows.map((r: any, i: number) => (
                      <Cell key={i} fill={(r.total_pnl ?? 0) >= 0 ? "#10b981" : "#ef4444"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <DataTable
              rows={stratRows}
              defaultSort={{ key: "total_pnl", dir: "desc" }}
              cols={[
                { key: "strategy", label: "Strategy" },
                { key: "trades", label: "Trades", align: "right" },
                { key: "total_pnl", label: "Total P&L", align: "right", render: (r) => <span className={pnlClass(r.total_pnl)}>{fmtINR(r.total_pnl)}</span> },
                { key: "avg_pnl", label: "Avg", align: "right", render: (r) => fmtINR(r.avg_pnl) },
                { key: "win_rate_pct", label: "Win %", align: "right", render: (r) => fmtPct(r.win_rate_pct, 0) },
              ]}
            />
          </div>
        )}
      </Panel>

      <Panel title="Swing Book Analytics" actions={<RefreshBtn onClick={positional.reload} loading={positional.loading} />}>
        {Object.keys(p).length === 0 || (p.total_trades ?? p.closed_trades ?? 0) === 0 ? (
          <EmptyState>No closed swing trades yet — analytics appear once positions complete their round-trips.</EmptyState>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries(p)
              .filter(([, v]) => typeof v === "number")
              .map(([k, v]: any) => (
                <StatCard key={k} label={k.replace(/_/g, " ")}
                  value={k.includes("pct") || k.includes("rate") ? fmtPct(v) : k.includes("pnl") || k.includes("value") ? fmtINR(v) : fmtNum(v)} />
              ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
