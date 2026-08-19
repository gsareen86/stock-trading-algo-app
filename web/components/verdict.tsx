import type { Evidence, Verdict } from "@/lib/api";

/**
 * One strategy's verdict, and the evidence under it.
 *
 * This component renders exactly one verdict and has no access to the others. That is the
 * design, not an accident: a component that received the full array would be one refactor away
 * from a consensus badge or an average conviction, which is the confluence scorecard arriving
 * as a UI affordance after fourteen increments of keeping it out of the domain.
 *
 * Conviction is rendered inside its own strategy's card and never on a shared axis, because it
 * is scoped to one strategy by definition.
 */

const STANCE_TONE: Record<string, string> = {
  BUY: "text-stance-buy border-stance-buy",
  WATCH: "text-stance-watch border-stance-watch",
  AVOID: "text-stance-avoid border-stance-avoid",
};

function formatValue(value: number | string | null, unit: string | null): string {
  if (value === null) return "—";
  if (typeof value === "string") return value;
  const rendered =
    unit === "INR"
      ? `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
      : value.toLocaleString("en-IN", { maximumFractionDigits: 4 });
  return unit && unit !== "INR" ? `${rendered}${unit}` : rendered;
}

function EvidenceRow({ row }: { row: Evidence }) {
  const tested = row.threshold !== null && row.operator !== "info";
  return (
    <tr className="border-t border-border-subtle align-top">
      <td className="py-1.5 pr-3 text-text-secondary">{row.label}</td>
      <td className="py-1.5 pr-3 font-mono text-text-primary">
        {formatValue(row.value, row.unit)}
      </td>
      <td className="py-1.5 pr-3 font-mono text-xs text-text-muted">
        {/* The comparison that was made, not just the number — "RS 12.4%" is a figure;
            "RS 12.4% >= 0% — passed" is an argument. */}
        {tested ? `${row.operator} ${formatValue(row.threshold, row.unit)}` : "—"}
      </td>
      <td className="py-1.5 pr-3 text-xs">
        {row.passed === null ? (
          <span className="text-text-muted">info</span>
        ) : row.passed ? (
          <span className="text-stance-buy">passed</span>
        ) : (
          <span className="text-stance-avoid">failed</span>
        )}
      </td>
      <td className="py-1.5 font-mono text-[11px] break-all text-text-muted">{row.source_ref}</td>
    </tr>
  );
}

export function VerdictCard({ verdict }: { verdict: Verdict }) {
  const failed = verdict.gates.filter((gate) => !gate.passed);

  return (
    <article className="rounded-token-lg border border-border-subtle bg-surface-raised p-4">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium text-text-primary">{verdict.strategy_id}</h3>
        <span
          className={`rounded-token border px-2 py-0.5 text-xs font-semibold ${
            STANCE_TONE[verdict.stance] ?? ""
          }`}
        >
          {verdict.stance}
        </span>
      </header>

      <p className="mt-2 text-xs text-text-muted">
        Conviction {verdict.conviction}/100
        <span className="ml-1">— within this strategy only</span>
      </p>

      {failed.length > 0 ? (
        <p className="mt-2 text-xs text-stance-avoid">
          Gate failed: {failed.map((gate) => gate.label).join(", ")} — {failed[0].reason}
        </p>
      ) : null}

      {verdict.narrative ? (
        <p className="mt-3 whitespace-pre-line text-sm text-text-secondary">
          {verdict.narrative}
        </p>
      ) : null}

      <details className="mt-3">
        {/* Collapsed by default — fourteen rows times four strategies is not a screen anyone
            reads. One click, not one navigation: "click through to see why" is a step people
            skip, and the traceability argument depends on the why being cheap to reach. */}
        <summary className="cursor-pointer text-xs text-text-muted hover:text-text-primary">
          {verdict.evidence.length} evidence rows
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[540px] text-left text-xs">
            <thead className="text-text-muted">
              <tr>
                <th className="pb-1 pr-3 font-normal">Metric</th>
                <th className="pb-1 pr-3 font-normal">Observed</th>
                <th className="pb-1 pr-3 font-normal">Tested against</th>
                <th className="pb-1 pr-3 font-normal">Result</th>
                <th className="pb-1 font-normal">Source</th>
              </tr>
            </thead>
            <tbody>
              {verdict.evidence.map((row) => (
                <EvidenceRow key={row.id} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </article>
  );
}

/**
 * Every strategy's verdict for one instrument, side by side.
 *
 * Agreement is something the reader sees by looking across the row. It is deliberately not
 * computed: no count of how many strategies agree, no average conviction, no sort by
 * consensus. Each card receives exactly one verdict.
 */
export function VerdictRow({ ticker, verdicts }: { ticker: string; verdicts: Verdict[] }) {
  const ordered = [...verdicts].sort((a, b) => a.strategy_id.localeCompare(b.strategy_id));

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold text-text-primary">{ticker}</h2>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {ordered.map((verdict) => (
          <VerdictCard key={verdict.strategy_id} verdict={verdict} />
        ))}
      </div>
    </section>
  );
}
