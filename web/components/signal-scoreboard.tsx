import Link from "next/link";

import type { Scoreboard, ScoreboardHorizonStats, ScoreboardRow } from "@/lib/api";

/**
 * Did the signals work?
 *
 * One card per strategy, in the order the backend returns them (alphabetical). Rows are never
 * pooled across strategies and strategies are never ordered by their results: the reader
 * compares a strategy's BUYs against its own AVOIDs, and against the benchmark.
 */

function pct(value: number | null | undefined, digits = 1, signed = true): string {
  if (value === null || value === undefined) return "—";
  const fixed = value.toFixed(digits);
  return signed && value > 0 ? `+${fixed}%` : `${fixed}%`;
}

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-text-muted";
  if (value > 0) return "text-stance-buy";
  if (value < 0) return "text-stance-avoid";
  return "text-text-primary";
}

const STANCE_TONE: Record<string, string> = {
  BUY: "text-stance-buy",
  WATCH: "text-stance-watch",
  AVOID: "text-stance-avoid",
};

function Toggle({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      scroll={false}
      className={`rounded-token px-2.5 py-1 font-mono text-xs ${
        active ? "bg-accent text-white" : "bg-surface-sunken text-text-secondary hover:text-text-primary"
      }`}
    >
      {children}
    </Link>
  );
}

function ExcessCell({ stats }: { stats: ScoreboardHorizonStats }) {
  if (stats.mean_excess_pp === null) return <span className="text-text-muted">—</span>;
  return (
    <span className={tone(stats.mean_excess_pp)}>
      {stats.mean_excess_pp > 0 ? "+" : ""}
      {stats.mean_excess_pp.toFixed(2)}
      <span className="text-text-muted">
        {stats.excess_se_pp !== null ? ` ± ${stats.excess_se_pp.toFixed(2)}` : ""} pp
      </span>
    </span>
  );
}

function RowLine({ row, horizon }: { row: ScoreboardRow; horizon: string }) {
  const stats = row.horizons[horizon];
  const isTotal = row.band === "all";
  return (
    <tr className={`border-t border-border-subtle ${isTotal ? "" : "text-text-secondary"}`}>
      <td className={`py-1.5 pr-3 font-mono text-xs ${isTotal ? "font-semibold" : "pl-4"}`}>
        {isTotal ? (
          <span className={STANCE_TONE[row.stance] ?? ""}>{row.stance}</span>
        ) : (
          <span className="text-text-muted">conv {row.band}</span>
        )}
      </td>
      <td className="tabular-nums py-1.5 pr-3 font-mono text-xs">{row.signals}</td>
      <td className="tabular-nums py-1.5 pr-3 font-mono text-xs">
        {stats ? stats.measured : "—"}
        {stats && stats.pending > 0 ? <span className="text-text-muted"> (+{stats.pending})</span> : null}
        {stats && stats.measured > 0 && stats.thin ? (
          <span className="ml-1.5 rounded-token bg-stance-watch-soft px-1 py-px text-[10px] text-stance-watch">
            thin
          </span>
        ) : null}
      </td>
      <td className={`tabular-nums py-1.5 pr-3 font-mono text-xs ${tone(stats?.mean_return_pct)}`}>
        {pct(stats?.mean_return_pct, 2)}
      </td>
      <td className="tabular-nums py-1.5 pr-3 font-mono text-xs">
        {stats ? <ExcessCell stats={stats} /> : "—"}
      </td>
      <td className={`tabular-nums py-1.5 pr-3 font-mono text-xs ${tone(stats?.median_excess_pp)}`}>
        {stats?.median_excess_pp === null || stats?.median_excess_pp === undefined
          ? "—"
          : `${stats.median_excess_pp > 0 ? "+" : ""}${stats.median_excess_pp.toFixed(2)} pp`}
      </td>
      <td className="tabular-nums py-1.5 pr-3 font-mono text-xs">{pct(stats?.beat_benchmark_pct, 0, false)}</td>
      <td className="tabular-nums py-1.5 font-mono text-xs text-text-muted">
        {stats && stats.with_stop > 0 ? pct(stats.stop_touched_pct, 0, false) : "—"}
      </td>
    </tr>
  );
}

export function SignalScoreboard({
  board,
  horizon,
  basePath = "/performance",
}: {
  board: Scoreboard;
  horizon: number;
  basePath?: string;
}) {
  const h = String(horizon);
  const href = (nextH: number, signals: string) => `${basePath}?h=${nextH}&signals=${signals}`;

  return (
    <section className="card-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle pb-3">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">Signal Scoreboard</h2>
          <p className="mt-0.5 text-sm text-text-secondary">
            What happened after each verdict the scan published — per strategy, against{" "}
            <span className="font-mono">{board.benchmarks.join(", ") || "the benchmark"}</span>.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {board.horizons.map((n) => (
            <Toggle key={n} href={href(n, board.signal_filter)} active={n === horizon}>
              {n} sessions
            </Toggle>
          ))}
          <span className="mx-1 h-4 w-px bg-border-subtle" />
          <Toggle href={href(horizon, "new")} active={board.signal_filter === "new"}>
            new signals
          </Toggle>
          <Toggle href={href(horizon, "all")} active={board.signal_filter === "all"}>
            every scan
          </Toggle>
        </div>
      </div>

      <div className="mt-4 grid gap-2.5 sm:grid-cols-4">
        {[
          ["Scans read", board.runs.count],
          ["Signals", board.totals.signals],
          ["Measured", board.totals.measured],
          ["Pending / unpriced", `${board.totals.pending} / ${board.totals.unpriced}`],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-token bg-surface-sunken px-3 py-2.5">
            <p className="text-[11px] text-text-muted">{label}</p>
            <p className="tabular-nums mt-0.5 font-mono text-lg font-semibold text-text-primary">{value}</p>
          </div>
        ))}
      </div>

      {board.notes.length > 0 ? (
        <ul className="mt-3 space-y-1 text-xs text-stance-watch">
          {board.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}

      <div className="mt-5 space-y-5">
        {board.strategies.map((strategy) => (
          <div key={strategy.strategy_id}>
            <h3 className="font-mono text-sm font-semibold text-text-primary">{strategy.strategy_id}</h3>
            <div className="mt-1.5 overflow-x-auto">
              <table className="w-full min-w-[720px] text-left">
                <thead className="text-[11px] text-text-muted">
                  <tr>
                    <th className="pb-1.5 pr-3 font-normal">Stance</th>
                    <th className="pb-1.5 pr-3 font-normal">Signals</th>
                    <th className="pb-1.5 pr-3 font-normal">Measured (+pending)</th>
                    <th className="pb-1.5 pr-3 font-normal">Mean return</th>
                    <th className="pb-1.5 pr-3 font-normal">Mean excess ± SE</th>
                    <th className="pb-1.5 pr-3 font-normal">Median excess</th>
                    <th className="pb-1.5 pr-3 font-normal">Beat benchmark</th>
                    <th className="pb-1.5 font-normal">Stop touched</th>
                  </tr>
                </thead>
                <tbody>
                  {strategy.rows.map((row) => (
                    <RowLine key={`${row.stance}-${row.band}`} row={row} horizon={h} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>

      {board.recent_buys.length > 0 ? (
        <details className="mt-5 border-t border-border-subtle pt-3">
          <summary className="cursor-pointer text-xs font-medium text-text-muted hover:text-text-primary">
            Recent BUY signals and how they went ({board.recent_buys.length})
          </summary>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="text-text-muted">
                <tr>
                  <th className="pb-1.5 pr-3 font-normal">Signalled</th>
                  <th className="pb-1.5 pr-3 font-normal">Ticker</th>
                  <th className="pb-1.5 pr-3 font-normal">Strategy</th>
                  <th className="pb-1.5 pr-3 font-normal">Conv</th>
                  <th className="pb-1.5 pr-3 font-normal">Entry</th>
                  {board.horizons.map((n) => (
                    <th key={n} className="pb-1.5 pr-3 font-normal">
                      {n}s excess
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {board.recent_buys.slice(0, 60).map((s) => (
                  <tr key={`${s.run_id}-${s.strategy_id}-${s.symbol}`} className="border-t border-border-subtle">
                    <td className="tabular-nums py-1.5 pr-3 font-mono text-text-muted">
                      {s.signalled_at.slice(0, 10)}
                    </td>
                    <td className="py-1.5 pr-3 font-mono font-semibold">
                      <Link href={`/stock?symbol=${encodeURIComponent(s.symbol)}`} className="text-accent hover:underline">
                        {s.symbol}
                      </Link>
                    </td>
                    <td className="py-1.5 pr-3 font-mono text-text-secondary">{s.strategy_id}</td>
                    <td className="tabular-nums py-1.5 pr-3 font-mono">{s.conviction}</td>
                    <td className="tabular-nums py-1.5 pr-3 font-mono">
                      {s.entry_price === null ? (
                        <span className="text-text-muted">{s.status}</span>
                      ) : (
                        `₹${s.entry_price.toFixed(2)}`
                      )}
                    </td>
                    {board.horizons.map((n) => {
                      const outcome = s.horizons[String(n)];
                      const excess = outcome?.excess_pp ?? null;
                      return (
                        <td key={n} className={`tabular-nums py-1.5 pr-3 font-mono ${tone(excess)}`}>
                          {excess === null ? "—" : `${excess > 0 ? "+" : ""}${excess.toFixed(1)}`}
                          {outcome?.stop_touched ? <span className="ml-1 text-stance-avoid">✕</span> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-text-muted">
            Excess in percentage points over the benchmark. ✕ marks a window in which the plan&apos;s stop was traded through.
          </p>
        </details>
      ) : null}

      <details className="mt-4 border-t border-border-subtle pt-3">
        <summary className="cursor-pointer text-xs font-medium text-text-muted hover:text-text-primary">
          How this is measured, and what it cannot see
        </summary>
        <p className="mt-2 text-xs text-text-secondary">{board.method}</p>
        <p className="mt-2 text-xs text-text-secondary">
          A row is flagged <span className="text-stance-watch">thin</span> below {board.thin_sample_floor} measured
          signals. SE is the standard error of the mean excess — a mean within about two SEs of zero is not yet
          distinguishable from luck.
        </p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-text-muted">
          {board.biases.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
