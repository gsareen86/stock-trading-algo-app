import { useState } from "react";
import { Zap, Microscope } from "lucide-react";
import { fmtINR, fmtPct, pnlClass, fmtIST, fmtNum, postJSON } from "../api";
import { Panel, StatCard, useApi, Badge, DataTable, EmptyState, Help, toast, Btn, RefreshBtn } from "../components/ui";
import ScanInspector from "../components/ScanInspector";

export default function LongTermBook() {
  const status = useApi<any>("/api/longterm/book/status");
  const positions = useApi<any[]>("/api/longterm/book/positions");
  const trades = useApi<any[]>("/api/longterm/book/trades");
  const scans = useApi<any[]>("/api/positional/scan-results");
  const [busy, setBusy] = useState(false);
  const [inspected, setInspected] = useState<any | null>(null);

  const s = status.data;
  const candidates = (scans.data ?? []).filter(
    (r) => (r.horizon === "LONG_TERM" || r.horizon === "BOTH") && (r.durability_score ?? 0) >= 70
  );

  const runPass = async () => {
    setBusy(true);
    try { const r = await postJSON("/api/longterm/book/run", {}); toast(r.message); }
    catch (e: any) { toast(`Run failed: ${e.message}`); }
    setBusy(false);
    setTimeout(() => { status.reload(); positions.reload(); trades.reload(); }, 1500);
  };

  return (
    <div className="space-y-6">
      <Help text="Durability-first book, horizon 1–3+ years, no time stop. Entry happens in three tranches: T1 when a durable name (durability ≥ 70) is classified LONG_TERM/BOTH, T2 on a controlled 8–15% drawdown or a 21-EMA reconfirmation, T3 once the guidance ledger confirms management delivered (MET/BEAT). A swing position that takes its +2R partial on a durable name converts its runner into this book automatically. Exits are thesis stops only: guidance miss streak, research verdict flip, management veto, pledge spike, plus a one-time halving below the 40-week MA in a DEFENSIVE regime." />

      {s && !s.enabled && (
        <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/5 text-amber-300 text-xs leading-relaxed">
          <b>The Long-Term book is currently disabled</b> (safe default). To activate it, add
          <code className="mx-1 px-1.5 py-0.5 rounded bg-slate-900 font-mono">LT_BOOK_ENABLED=true</code>
          to your <code className="px-1 rounded bg-slate-900 font-mono">.env</code> and restart. Until then the
          candidate list below still updates with every scan, so you can paper-track what it would buy.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Status" value={<Badge text={s?.enabled ? "ENABLED" : "DISABLED"} />}
          sub={`Pool ${fmtINR(s?.capital)} · max ${s?.max_positions ?? 10} names`} />
        <StatCard label="Invested" value={fmtINR(s?.invested)} tone="accent" sub={`Cash ${fmtINR(s?.cash)}`} />
        <StatCard label="Open Positions" value={s?.open_positions ?? 0} sub="10% max per name, 30% per sector" />
        <StatCard label="Net Realized P&L" value={<span className={pnlClass(s?.net_realized_pnl)}>{fmtINR(s?.net_realized_pnl)}</span>}
          sub="Closed LT positions" />
      </div>

      <div className="flex gap-2">
        <Btn kind="primary" busy={busy} onClick={runPass}><Zap size={11} /> Run LT Book Pass Now</Btn>
        <span className="text-[10px] text-slate-500 self-center">Runs automatically after every EOD scan when enabled.</span>
      </div>

      <Panel title="Holdings" subtitle="avg entry across tranches; 'Tranches' shows accumulation progress (max 3); 'Why Held' is the tranche-1 rationale recorded at entry"
        actions={<RefreshBtn onClick={positions.reload} loading={positions.loading} />}>
        <DataTable
          rows={(positions.data ?? []).filter((p) => p.status === "OPEN")}
          searchKeys={["ticker", "sector", "source"]}
          empty={<EmptyState>No LT holdings yet.{!s?.enabled && " Enable the book to start tranche-1 entries from the candidates below."}</EmptyState>}
          cols={[
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "sector", label: "Sector" },
            { key: "quantity", label: "Qty", align: "right" },
            { key: "avg_entry_price", label: "Avg Entry", align: "right", render: (r) => fmtINR(r.avg_entry_price) },
            { key: "current_price", label: "Live", align: "right", render: (r) => fmtINR(r.current_price) },
            { key: "unrealized_pnl", label: "Unrealized", align: "right", render: (r) => <span className={pnlClass(r.unrealized_pnl)}>{fmtINR(r.unrealized_pnl)} ({fmtPct(r.unrealized_pnl_pct)})</span> },
            { key: "tranches_taken", label: "Tranches", render: (r) => `${r.tranches_taken}/3${r.halved ? " · halved" : ""}` },
            { key: "source", label: "Source", render: (r) => <Badge text={r.source === "conversion" ? "FROM SWING" : "CLASSIFIED"} tone="INFO" /> },
            {
              key: "entry_reason", label: "Why Held", render: (r) => (
                <span className="text-[10px] text-slate-400 whitespace-normal max-w-[260px] inline-block leading-snug"
                  title={r.entry_reason}>{r.entry_reason ?? "—"}</span>
              ),
            },
            { key: "opened_at", label: "Opened", render: (r) => fmtIST(r.opened_at) },
          ]}
        />
      </Panel>

      <Panel title="Candidates" subtitle="Names from the latest scan (one row per stock) with durability ≥ 70 and LONG_TERM/BOTH horizon — what the book buys (T1) when enabled. Click 🔬 Inspect for the full rationale: strategies, pillar breakdown, scan reading and chart, plus jumps to Research / News / Fundamentals."
        actions={<RefreshBtn onClick={scans.reload} loading={scans.loading} />}>
        {inspected && <div className="mb-4"><ScanInspector row={inspected} onClose={() => setInspected(null)} /></div>}
        <DataTable
          rows={candidates}
          searchKeys={["ticker", "horizon"]}
          defaultSort={{ key: "durability_score", dir: "desc" }}
          empty={<EmptyState>No qualifying candidates in the latest scans. Run an EOD scan from the Swing Book page — names classified LONG_TERM with durability ≥ 70 land here.</EmptyState>}
          cols={[
            {
              key: "inspect", label: "", render: (r) => (
                <button onClick={() => setInspected(r)} title="Why is this a candidate? Strategies, pillars and chart"
                  className="p-1 rounded-md bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/25 border border-indigo-500/20">
                  <Microscope size={12} />
                </button>
              ),
            },
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "durability_score", label: "Durability", align: "right", render: (r) => <span className="font-bold text-emerald-400">{fmtNum(r.durability_score, 0)}</span> },
            { key: "timing_score", label: "Timing", align: "right", render: (r) => fmtNum(r.timing_score, 0) },
            { key: "horizon", label: "Horizon", render: (r) => <Badge text={r.horizon} /> },
            { key: "price", label: "Price", align: "right", render: (r) => fmtINR(r.price) },
            { key: "scanned_at", label: "Scanned", render: (r) => fmtIST(r.scanned_at) },
          ]}
        />
      </Panel>

      <Panel title="LT Trade Log" subtitle="Every tranche, conversion, halving and thesis-stop exit"
        actions={<RefreshBtn onClick={trades.reload} loading={trades.loading} />}>
        <DataTable
          rows={trades.data ?? []}
          searchKeys={["ticker", "reason", "side"]}
          empty={<EmptyState>No LT trades yet.</EmptyState>}
          cols={[
            { key: "ts", label: "Time", render: (r) => fmtIST(r.ts) },
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "side", label: "Side", render: (r) => <Badge text={r.side} /> },
            { key: "quantity", label: "Qty", align: "right" },
            { key: "price", label: "Price", align: "right", render: (r) => fmtINR(r.price) },
            { key: "pnl", label: "P&L", align: "right", render: (r) => <span className={pnlClass(r.pnl)}>{fmtINR(r.pnl)}</span> },
            { key: "reason", label: "Reason", render: (r) => <span className="text-[10px] text-slate-400 whitespace-normal">{r.reason}</span> },
          ]}
        />
      </Panel>
    </div>
  );
}
