import { fmtINR, fmtPct, pnlClass, fmtIST } from "../api";
import { Panel, useApi, Badge, DataTable, EmptyState, Help, RefreshBtn } from "../components/ui";

export default function Intraday() {
  const open = useApi<any[]>("/api/positions/open");
  const closed = useApi<any[]>("/api/positions/closed");
  const signals = useApi<any[]>("/api/signals?limit=500");

  return (
    <div className="space-y-6">
      <Help text="The intraday book: 15-min candle strategies, ATR stops with a partial at +1×ATR, and a hard square-off at 15:10 IST. Signals below show every decision the composite scorer made — including the ones that were not taken." />

      <Panel title="Open Positions" subtitle="Live intraday holdings with their ATR exit ladder"
        actions={<RefreshBtn onClick={open.reload} loading={open.loading} />}>
        <DataTable
          rows={open.data ?? []}
          searchKeys={["ticker", "strategy"]}
          empty={<EmptyState>No open positions. The bot only enters between 09:30 and 15:00 IST on trading days, when a signal clears the composite score.</EmptyState>}
          cols={[
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "side", label: "Side", render: (r) => <Badge text={r.side} /> },
            { key: "quantity", label: "Qty", align: "right" },
            { key: "entry_price", label: "Entry", align: "right", render: (r) => fmtINR(r.entry_price) },
            { key: "current_price", label: "Live", align: "right", render: (r) => fmtINR(r.current_price) },
            { key: "unrealized_pnl", label: "Unrealized", align: "right", render: (r) => <span className={pnlClass(r.unrealized_pnl)}>{fmtINR(r.unrealized_pnl)} ({fmtPct(r.unrealized_pnl_pct)})</span> },
            { key: "stop_loss", label: "Stop", align: "right", render: (r) => fmtINR(r.stop_loss) },
            { key: "t1_target", label: "T1", align: "right", render: (r) => <span>{fmtINR(r.t1_target)} {r.t1_taken ? <Badge text="TAKEN" tone="OK" /> : null}</span> },
            { key: "take_profit", label: "Target", align: "right", render: (r) => fmtINR(r.take_profit) },
            { key: "strategy", label: "Strategy" },
            { key: "entered_at", label: "Opened", render: (r) => r.entered_at ?? "—" },
          ]}
        />
      </Panel>

      <Panel title="Closed Positions" subtitle="Completed round-trips with realized P&L (after all costs and slippage)"
        actions={<RefreshBtn onClick={closed.reload} loading={closed.loading} />}>
        <DataTable
          rows={closed.data ?? []}
          searchKeys={["ticker", "strategy", "exit_reason"]}
          defaultSort={{ key: "closed_at", dir: "desc" }}
          cols={[
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "side", label: "Side", render: (r) => <Badge text={r.side} /> },
            { key: "quantity", label: "Qty", align: "right" },
            { key: "entry_price", label: "Entry", align: "right", render: (r) => fmtINR(r.entry_price) },
            { key: "exit_price", label: "Exit", align: "right", render: (r) => fmtINR(r.exit_price) },
            { key: "pnl", label: "P&L", align: "right", render: (r) => <span className={pnlClass(r.pnl)}>{fmtINR(r.pnl)} ({fmtPct(r.pnl_pct)})</span> },
            { key: "strategy", label: "Strategy" },
            { key: "opened_at", label: "Opened", render: (r) => r.opened_at ?? "—" },
            { key: "closed_at", label: "Closed", render: (r) => r.closed_at ?? "—" },
            { key: "exit_reason", label: "Exit Reason", render: (r) => <span className="text-[10px] text-slate-400">{r.exit_reason ?? "—"}</span> },
          ]}
          empty={<EmptyState>No closed trades yet.</EmptyState>}
        />
      </Panel>

      <Panel title="Signal History" subtitle="Last 500 signals with the three score pillars. 'Taken' means it became a position or approval."
        actions={<RefreshBtn onClick={signals.reload} loading={signals.loading} />}>
        <DataTable
          rows={signals.data ?? []}
          searchKeys={["ticker", "strategy", "action"]}
          maxHeight="500px"
          cols={[
            { key: "ts", label: "Time", render: (r) => fmtIST(r.ts) },
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "action", label: "Action", render: (r) => <Badge text={r.action} /> },
            { key: "composite_score", label: "Composite", align: "right" },
            { key: "technical_score", label: "Tech", align: "right" },
            { key: "fundamental_score", label: "Fund", align: "right" },
            { key: "sentiment_score", label: "Sent", align: "right" },
            { key: "strategy", label: "Strategy" },
            { key: "taken", label: "Taken", render: (r) => <Badge text={r.taken ? "YES" : "NO"} tone={r.taken ? "OK" : "PENDING"} /> },
          ]}
          empty={<EmptyState>No signals logged yet. Trigger a cycle from the Control Center during market hours.</EmptyState>}
        />
      </Panel>
    </div>
  );
}
