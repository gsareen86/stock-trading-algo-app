import { VerdictRow } from "@/components/verdict";
import { Empty, Unavailable } from "@/components/states";
import { evaluate } from "@/lib/api";
import type { Verdict } from "@/lib/api";

/**
 * Ideas — every strategy's verdict on a name, side by side.
 *
 * Deliberately **not** a ranked list. There is no consensus badge, no average conviction, and
 * no ordering by how many strategies agree: each of those is the confluence scorecard arriving
 * as a UI affordance after being kept out of the domain for fourteen increments. Agreement is
 * something the reader sees by looking across a row.
 */

export const dynamic = "force-dynamic";

/** Evaluating a universe on page load would be hundreds of price fetches. */
const DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK"];

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ symbols?: string }>;
}) {
  const params = await searchParams;
  const symbols = (params.symbols ?? DEFAULT_SYMBOLS.join(","))
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 8);

  const result = await evaluate(symbols);

  const byTicker = new Map<string, Verdict[]>();
  if (result.ok) {
    for (const verdict of result.data.verdicts) {
      const list = byTicker.get(verdict.ticker) ?? [];
      list.push(verdict);
      byTicker.set(verdict.ticker, list);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Ideas</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Every strategy&apos;s verdict, side by side. Disagreement is a visible outcome, never
        averaged away.
      </p>

      <form method="get" className="mt-5 flex gap-2">
        <input
          name="symbols"
          defaultValue={symbols.join(",")}
          placeholder="RELIANCE,TCS"
          aria-label="Comma-separated NSE symbols"
          className="w-full max-w-md rounded-token border border-border-subtle bg-surface-sunken px-3 py-1.5 font-mono text-sm text-text-primary"
        />
        <button
          type="submit"
          className="rounded-token border border-border-strong px-3 py-1.5 text-sm text-text-primary"
        >
          Evaluate
        </button>
      </form>

      {!result.ok ? (
        <div className="mt-8">
          <Unavailable result={result} />
        </div>
      ) : byTicker.size === 0 ? (
        <div className="mt-8">
          <Empty>No verdicts returned for those symbols.</Empty>
        </div>
      ) : (
        [...byTicker.entries()].map(([ticker, verdicts]) => (
          <VerdictRow key={ticker} ticker={ticker} verdicts={verdicts} />
        ))
      )}

      <p className="mt-10 text-xs text-text-muted">
        Conviction is scoped to its own strategy and is not comparable across them. Nothing on
        this page merges four verdicts into one answer.
      </p>
    </div>
  );
}
