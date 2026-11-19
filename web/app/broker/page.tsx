import Link from "next/link";

import { BrokerConnect } from "@/components/broker-connect";
import { Empty, Unavailable } from "@/components/states";
import { fetchBrokerHoldings, fetchBrokerStatus } from "@/lib/api";

export const dynamic = "force-dynamic";

function money(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return `₹${val.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export default async function BrokerPage() {
  const [statusRes, holdingsRes] = await Promise.all([
    fetchBrokerStatus(),
    fetchBrokerHoldings(),
  ]);

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 py-8">
      <section className="hero-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <span className="rounded-token border border-stance-buy bg-stance-buy-soft px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-stance-buy">
              Read-Only Mirror · Order Execution Disabled
            </span>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-text-primary">
              Zerodha Kite
            </h1>
            <p className="mt-1 max-w-xl text-sm text-text-secondary">
              Cross-check your real holdings against the four strategies without mixing real accounts into paper books. Order placement verbs are permanently blocked at MCP discovery.
            </p>
          </div>
        </div>
      </section>

      {!statusRes.ok ? (
        <Unavailable result={statusRes} />
      ) : (
        <BrokerConnect initial={statusRes.data} />
      )}

      {holdingsRes.ok ? (
        <section className="card-surface p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
              Real Holdings ({holdingsRes.data.count})
            </h2>
            <div className="tabular-nums font-mono text-xs text-text-secondary">
              Invested {money(holdingsRes.data.invested)} · Value{" "}
              {money(holdingsRes.data.market_value)}
            </div>
          </div>

          {holdingsRes.data.holdings.length === 0 ? (
            <div className="mt-3">
              <Empty>No equity holdings reported by Zerodha Kite.</Empty>
            </div>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[540px] text-left text-sm">
                <thead className="text-xs text-text-muted">
                  <tr>
                    <th className="pb-2 pr-3 font-medium">Symbol</th>
                    <th className="pb-2 pr-3 font-medium">Qty</th>
                    <th className="pb-2 pr-3 font-medium">Avg Cost</th>
                    <th className="pb-2 pr-3 font-medium">Last</th>
                    <th className="pb-2 pr-3 font-medium">Reported P&amp;L</th>
                    <th className="pb-2 text-right font-medium">Inspect</th>
                  </tr>
                </thead>
                <tbody>
                  {holdingsRes.data.holdings.map((h) => (
                    <tr key={h.symbol} className="border-t border-border-subtle">
                      <td className="py-2 pr-3 font-mono font-semibold text-text-primary">
                        {h.symbol}
                      </td>
                      <td className="tabular-nums py-2 pr-3 font-mono">{h.quantity}</td>
                      <td className="tabular-nums py-2 pr-3 font-mono">{money(h.average_price)}</td>
                      <td className="tabular-nums py-2 pr-3 font-mono">{money(h.last_price)}</td>
                      <td
                        className={`tabular-nums py-2 pr-3 font-mono font-medium ${
                          (h.pnl_reported_by_broker ?? 0) < 0
                            ? "text-stance-avoid"
                            : "text-stance-buy"
                        }`}
                      >
                        {money(h.pnl_reported_by_broker)}
                      </td>
                      <td className="py-2 text-right">
                        <Link
                          href={`/stock?symbol=${encodeURIComponent(h.symbol)}`}
                          className="text-xs font-semibold text-accent hover:underline"
                        >
                          Stock Deep-Dive →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      <section className="card-surface p-5 text-sm text-text-secondary">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          What to expect
        </h2>
        <div className="mt-3 grid gap-4 md:grid-cols-3">
          <div>
            <p className="font-semibold text-text-primary">Zero order capability</p>
            <p className="mt-1 text-xs">
              This connection can only read holdings and quotes. Paper fills stay isolated in Swing &amp; Long-Term books.
            </p>
          </div>
          <div>
            <p className="font-semibold text-text-primary">Daily exchange expiry</p>
            <p className="mt-1 text-xs">
              Zerodha invalidates Kite sessions each day per exchange regulations.
            </p>
          </div>
          <div>
            <p className="font-semibold text-text-primary">On-demand login URLs</p>
            <p className="mt-1 text-xs">
              Login links are minted at click time so they never arrive pre-expired.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
