import Link from "next/link";

import { Empty, GrossNote, Unavailable } from "@/components/states";
import { type BookAnalytics, type Trade, fetchAnalytics, fetchTrades } from "@/lib/api";

export const dynamic = "force-dynamic";

const BOOKS = ["swing", "longterm"] as const;

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="rounded-token bg-surface-sunken px-3 py-2.5">
      <p className="text-[11px] text-text-muted">{label}</p>
      <p className={`tabular-nums mt-0.5 font-mono text-lg font-semibold ${tone ?? "text-text-primary"}`}>
        {value}
      </p>
      {hint ? <p className="text-[10px] text-text-muted">{hint}</p> : null}
    </div>
  );
}

function BookCard({
  book,
  analytics,
  trades,
}: {
  book: string;
  analytics: BookAnalytics;
  trades: Trade[];
}) {
  const closed = analytics.closed_trades;
  const attribution = Object.entries(analytics.attribution);
  const maxBought = attribution.reduce((acc, [, row]) => Math.max(acc, row.bought), 1);

  return (
    <section className="card-surface p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-subtle pb-3">
        <h2 className="text-lg font-semibold capitalize text-text-primary">
          {book === "longterm" ? "Long-Term" : "Swing"} Book
        </h2>
        <span className="tabular-nums font-mono text-xs text-text-muted">
          {analytics.trade_count} recorded fills
        </span>
      </div>

      <div className="mt-4 grid gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Open Positions" value={String(analytics.open_positions)} />
        <Stat label="Cost Basis" value={money(analytics.cost_basis)} />
        <Stat
          label="Unrealised (Gross)"
          value={money(analytics.unrealised_pnl_gross)}
          hint={analytics.market_value === null ? "price missing" : undefined}
          tone={(analytics.unrealised_pnl_gross ?? 0) < 0 ? "text-stance-avoid" : "text-stance-buy"}
        />
        <Stat
          label="Realised (Gross)"
          value={money(analytics.realised_pnl_gross)}
          tone={analytics.realised_pnl_gross < 0 ? "text-stance-avoid" : "text-stance-buy"}
        />
        <Stat label="Closed Trades" value={String(closed.closed)} />
        <Stat
          label="Win Rate"
          value={closed.win_rate_pct === null ? "—" : `${closed.win_rate_pct}%`}
          hint="closed positions only"
        />
      </div>

      {attribution.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Alphabetical Strategy Activity
          </h3>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[460px] text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="pb-1.5 pr-3 font-normal">Strategy</th>
                  <th className="pb-1.5 pr-3 font-normal">Trades</th>
                  <th className="pb-1.5 pr-3 font-normal">Bought</th>
                  <th className="pb-1.5 pr-3 font-normal">Sold</th>
                  <th className="pb-1.5 font-normal">Activity Share</th>
                </tr>
              </thead>
              <tbody>
                {attribution
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([strategy, row]) => {
                    const barPct = Math.round((row.bought / maxBought) * 100);
                    return (
                      <tr key={strategy} className="border-t border-border-subtle">
                        <td className="py-2 pr-3 font-mono text-xs font-medium text-text-primary">
                          {strategy}
                        </td>
                        <td className="tabular-nums py-2 pr-3 font-mono">{row.trades}</td>
                        <td className="tabular-nums py-2 pr-3 font-mono">{money(row.bought)}</td>
                        <td className="tabular-nums py-2 pr-3 font-mono">{money(row.sold)}</td>
                        <td className="w-36 py-2">
                          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
                            <div className="h-full bg-accent" style={{ width: `${barPct}%` }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-text-muted">
            Ordered alphabetically — never ranked. Open positions are excluded from Win Rate.
          </p>
        </div>
      ) : null}

      {trades.length > 0 ? (
        <details className="mt-4 border-t border-border-subtle pt-3">
          <summary className="cursor-pointer text-xs font-medium text-text-muted hover:text-text-primary">
            Recorded Trade Journal ({trades.length})
          </summary>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[540px] text-left text-xs">
              <thead className="text-text-muted">
                <tr>
                  <th className="pb-1.5 pr-3 font-normal">Date</th>
                  <th className="pb-1.5 pr-3 font-normal">Ticker</th>
                  <th className="pb-1.5 pr-3 font-normal">Side</th>
                  <th className="pb-1.5 pr-3 font-normal">Qty</th>
                  <th className="pb-1.5 pr-3 font-normal">Price</th>
                  <th className="pb-1.5 pr-3 font-normal">Strategy</th>
                  <th className="pb-1.5 font-normal">Note</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice(0, 30).map((t) => (
                  <tr key={t.id} className="border-t border-border-subtle">
                    <td className="tabular-nums py-1.5 pr-3 font-mono text-text-muted">
                      {t.executed_at.slice(0, 10)}
                    </td>
                    <td className="py-1.5 pr-3 font-mono font-semibold">
                      <Link href={`/stock?symbol=${encodeURIComponent(t.ticker)}`} className="text-accent hover:underline">
                        {t.ticker}
                      </Link>
                    </td>
                    <td className={`py-1.5 pr-3 font-mono font-semibold ${t.side === "BUY" ? "text-stance-buy" : "text-stance-avoid"}`}>
                      {t.side}
                    </td>
                    <td className="tabular-nums py-1.5 pr-3 font-mono">{t.quantity}</td>
                    <td className="tabular-nums py-1.5 pr-3 font-mono">₹{t.price.toFixed(2)}</td>
                    <td className="py-1.5 pr-3 font-mono text-text-secondary">{t.strategy_id ?? "manual"}</td>
                    <td className="max-w-[14rem] truncate py-1.5 text-text-muted">{t.note ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  );
}

export default async function PerformancePage() {
  const results = await Promise.all(
    BOOKS.map(async (book) => {
      const [analytics, trades] = await Promise.all([fetchAnalytics(book), fetchTrades(book, 50)]);
      return { book, analytics, trades };
    }),
  );

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      <section className="hero-surface p-6">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
          Book &amp; Strategy Attribution
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text-primary">
          Performance
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Realised vs unrealised gross P&amp;L, closed-only win rates, alphabetical strategy activity, and recorded trade fills.
        </p>
      </section>

      {results.map(({ book, analytics, trades }) => (
        <div key={book}>
          {!analytics.ok ? (
            <Unavailable result={analytics} />
          ) : analytics.data.trade_count === 0 ? (
            <Empty>Nothing has been traded in the {book} book yet.</Empty>
          ) : (
            <BookCard
              book={book}
              analytics={analytics.data}
              trades={trades.ok ? trades.data.trades : []}
            />
          )}
        </div>
      ))}

      <GrossNote />
      <p className="text-xs text-text-muted">
        Historical replay lives at <code className="font-mono">POST /backtest/run</code>. It is omitted as a casual button so its biases are inspected intentionally.
      </p>
    </div>
  );
}
