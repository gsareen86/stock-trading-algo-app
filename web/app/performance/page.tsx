import { Empty, GrossNote, Unavailable } from "@/components/states";
import { fetchAnalytics } from "@/lib/api";
import type { BookAnalytics } from "@/lib/api";

/**
 * Performance — how the books are doing, and what each strategy has actually done.
 *
 * Attribution reports activity per strategy. It deliberately does not rank them: "which
 * strategy performed best" is a question this platform cannot answer with one number, and a
 * leaderboard here would answer it anyway.
 *
 * No charts. Nothing on this page needs one that a table does not say better, and a chart
 * library is a dependency with a rendering budget.
 */

export const dynamic = "force-dynamic";

const BOOKS = ["swing", "longterm"] as const;

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-token bg-surface-sunken px-3 py-2">
      <p className="text-xs text-text-muted">{label}</p>
      <p className="mt-0.5 font-mono text-lg text-text-primary">{value}</p>
      {hint ? <p className="text-[11px] text-text-muted">{hint}</p> : null}
    </div>
  );
}

function BookPanel({ book, analytics }: { book: string; analytics: BookAnalytics }) {
  const closed = analytics.closed_trades;
  const attribution = Object.entries(analytics.attribution);

  return (
    <div className="mt-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Open positions" value={String(analytics.open_positions)} />
        <Stat label="Cost basis" value={money(analytics.cost_basis)} />
        <Stat
          label="Unrealised (gross)"
          value={money(analytics.unrealised_pnl_gross)}
          hint={analytics.market_value === null ? "a price is missing" : undefined}
        />
        <Stat label="Realised (gross)" value={money(analytics.realised_pnl_gross)} />
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <Stat label="Closed trades" value={String(closed.closed)} />
        <Stat
          label="Win rate"
          value={closed.win_rate_pct === null ? "—" : `${closed.win_rate_pct}%`}
          // Open positions have no outcome; counting unrealised gains as wins is how a
          // strategy looks good until it is closed.
          hint="closed positions only"
        />
        <Stat label="Trades recorded" value={String(analytics.trade_count)} />
      </div>

      {attribution.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Activity by strategy
          </h3>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="pb-1 pr-3 font-normal">Strategy</th>
                  <th className="pb-1 pr-3 font-normal">Trades</th>
                  <th className="pb-1 pr-3 font-normal">Bought</th>
                  <th className="pb-1 font-normal">Sold</th>
                </tr>
              </thead>
              <tbody>
                {attribution
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([strategy, row]) => (
                    <tr key={strategy} className="border-t border-border-subtle">
                      <td className="py-1.5 pr-3 text-text-primary">{strategy}</td>
                      <td className="py-1.5 pr-3 font-mono">{row.trades}</td>
                      <td className="py-1.5 pr-3 font-mono">{money(row.bought)}</td>
                      <td className="py-1.5 font-mono">{money(row.sold)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-text-muted">
            Activity, in alphabetical order — not a ranking. Which strategy performed best is
            not a question this platform answers with one number.
          </p>
        </div>
      ) : null}
    </div>
  );
}

async function BookSection({ book }: { book: string }) {
  const analytics = await fetchAnalytics(book);

  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold capitalize text-text-primary">{book}</h2>
      {!analytics.ok ? (
        <div className="mt-3">
          <Unavailable result={analytics} />
        </div>
      ) : analytics.data.trade_count === 0 ? (
        <div className="mt-3">
          <Empty>Nothing has been traded in this book yet.</Empty>
        </div>
      ) : (
        <BookPanel book={book} analytics={analytics.data} />
      )}
    </section>
  );
}

export default function Page() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Performance</h1>
      <p className="mt-1 text-sm text-text-secondary">
        How each book is doing, and what each strategy has actually done.
      </p>

      {BOOKS.map((book) => (
        <BookSection key={book} book={book} />
      ))}

      <GrossNote />

      <p className="mt-2 text-xs text-text-muted">
        Historical replay lives at <code className="font-mono">POST /backtest/run</code>. It is
        deliberately not a button here: a replay is minutes of work and its results carry
        biases that need reading, not glancing at.
      </p>
    </div>
  );
}
