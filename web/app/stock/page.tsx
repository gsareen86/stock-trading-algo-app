import { VerdictCard } from "@/components/verdict";
import { Empty, Unavailable } from "@/components/states";
import { evaluate, fetchPositions } from "@/lib/api";

/**
 * Stock — everything known about one name.
 *
 * Four verdicts with their evidence, plus whether it is held. The four are rendered as four,
 * with no summary line above them: a "3 of 4 agree" badge here would be the blend this
 * platform exists to remove, arriving where it would look most helpful.
 */

export const dynamic = "force-dynamic";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ symbol?: string }>;
}) {
  const params = await searchParams;
  const symbol = (params.symbol ?? "RELIANCE").trim().toUpperCase();

  const [result, swing, longterm] = await Promise.all([
    evaluate([symbol], true),
    fetchPositions("swing"),
    fetchPositions("longterm"),
  ]);

  const held = [
    ...(swing.ok ? swing.data.positions : []),
    ...(longterm.ok ? longterm.data.positions : []),
  ].filter((position) => position.ticker === symbol);

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-text-primary">{symbol}</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Four independent readings, and the evidence behind each.
      </p>

      <form method="get" className="mt-5 flex gap-2">
        <input
          name="symbol"
          defaultValue={symbol}
          aria-label="NSE symbol"
          className="w-48 rounded-token border border-border-subtle bg-surface-sunken px-3 py-1.5 font-mono text-sm text-text-primary"
        />
        <button
          type="submit"
          className="rounded-token border border-border-strong px-3 py-1.5 text-sm text-text-primary"
        >
          Look up
        </button>
      </form>

      {held.length > 0 ? (
        <div className="mt-6 rounded-token-lg border border-border-subtle bg-surface-raised p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Held
          </h2>
          {held.map((position) => (
            <p key={position.book} className="mt-1 text-sm text-text-secondary">
              <span className="capitalize">{position.book}</span>: {position.quantity} at
              ₹{position.average_cost.toLocaleString("en-IN")} — unrealised{" "}
              {position.unrealised_pnl_gross === null
                ? "unavailable"
                : `₹${position.unrealised_pnl_gross.toLocaleString("en-IN", {
                    maximumFractionDigits: 0,
                  })} gross`}
            </p>
          ))}
        </div>
      ) : null}

      {!result.ok ? (
        <div className="mt-8">
          <Unavailable result={result} />
        </div>
      ) : result.data.verdicts.length === 0 ? (
        <div className="mt-8">
          <Empty>No strategy could form a verdict on {symbol}.</Empty>
        </div>
      ) : (
        <div className="mt-6 grid gap-3 md:grid-cols-2">
          {[...result.data.verdicts]
            .sort((a, b) => a.strategy_id.localeCompare(b.strategy_id))
            .map((verdict) => (
              <VerdictCard key={verdict.strategy_id} verdict={verdict} />
            ))}
        </div>
      )}
    </div>
  );
}
