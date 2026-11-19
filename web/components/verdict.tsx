import type { Evidence, Plan, Verdict } from "@/lib/api";

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
  BUY: "border-stance-buy bg-stance-buy-soft text-stance-buy",
  WATCH: "border-stance-watch bg-stance-watch-soft text-stance-watch",
  AVOID: "border-stance-avoid bg-stance-avoid-soft text-stance-avoid",
};

const BORDER_ACCENT: Record<string, string> = {
  BUY: "border-l-4 border-l-stance-buy",
  WATCH: "border-l-4 border-l-stance-watch",
  AVOID: "border-l-4 border-l-stance-avoid",
};

const BAR_FILL: Record<string, string> = {
  BUY: "bg-stance-buy",
  WATCH: "bg-stance-watch",
  AVOID: "bg-stance-avoid",
};

const STRATEGY_LABEL: Record<string, string> = {
  minervini: "Minervini VCP",
  young_momentum: "Young Momentum",
  brahma_vishnu_mahesh: "Brahma-Vishnu-Mahesh",
  fun_tech_momentum: "Fun-Tech Momentum",
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
      <td className="tabular-nums py-1.5 pr-3 font-mono text-text-primary">
        {formatValue(row.value, row.unit)}
      </td>
      <td className="tabular-nums py-1.5 pr-3 font-mono text-xs text-text-muted">
        {tested ? `${row.operator} ${formatValue(row.threshold, row.unit)}` : "—"}
      </td>
      <td className="py-1.5 pr-3 text-xs">
        {row.passed === null ? (
          <span className="text-text-muted">info</span>
        ) : row.passed ? (
          <span className="font-medium text-stance-buy">passed</span>
        ) : (
          <span className="font-medium text-stance-avoid">failed</span>
        )}
      </td>
      <td className="py-1.5 font-mono text-[11px] break-all text-text-muted">{row.source_ref}</td>
    </tr>
  );
}

export function VerdictCard({
  verdict,
  onPreviewPlan,
}: {
  verdict: Verdict;
  onPreviewPlan?: (strategyId: string, plan: Plan) => void;
}) {
  const failed = verdict.gates.filter((gate) => !gate.passed);
  const plan = verdict.plan ?? null;
  const pct = Math.max(0, Math.min(100, verdict.conviction));

  return (
    <article
      className={`card-surface p-5 ${BORDER_ACCENT[verdict.stance] ?? ""}`}
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">
            {STRATEGY_LABEL[verdict.strategy_id] ?? verdict.strategy_id}
          </h3>
          <p className="font-mono text-[11px] text-text-muted">{verdict.strategy_id}</p>
        </div>
        <span
          className={`rounded-token border px-2.5 py-0.5 text-xs font-semibold ${
            STANCE_TONE[verdict.stance] ?? ""
          }`}
        >
          {verdict.stance}
        </span>
      </header>

      <div className="mt-3">
        <div className="flex items-baseline justify-between text-xs">
          <span className="tabular-nums font-mono font-medium text-text-primary">
            Conviction {verdict.conviction}/100
          </span>
          <span className="text-[11px] text-text-muted">
            scoped to {verdict.strategy_id} only
          </span>
        </div>
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div
            className={`h-full transition-all ${BAR_FILL[verdict.stance] ?? "bg-accent"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {plan ? (
        <div className="mt-3 rounded-token bg-surface-sunken p-3">
          <div className="grid grid-cols-4 gap-2 text-xs">
            <div>
              <span className="block text-[11px] text-text-muted">Entry</span>
              <span className="tabular-nums font-mono font-semibold text-text-primary">
                ₹{plan.entry.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
            <div>
              <span className="block text-[11px] text-text-muted">Stop</span>
              <span className="tabular-nums font-mono font-semibold text-stance-avoid">
                ₹{plan.stop.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
            <div>
              <span className="block text-[11px] text-text-muted">Target</span>
              <span className="tabular-nums font-mono font-semibold text-stance-buy">
                ₹{plan.target.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
            <div>
              <span className="block text-[11px] text-text-muted">R:R</span>
              <span className="tabular-nums font-mono font-semibold text-text-primary">
                {plan.risk_reward ? `${plan.risk_reward}:1` : "—"}
              </span>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-text-muted">
            <span>
              {plan.entry_kind}
              {plan.horizon ? ` · ${plan.horizon}` : ""}
            </span>
            {onPreviewPlan ? (
              <button
                type="button"
                onClick={() => onPreviewPlan(verdict.strategy_id, plan)}
                className="font-medium text-accent hover:underline"
              >
                Preview Paper Buy →
              </button>
            ) : null}
          </div>
        </div>
      ) : verdict.plan_note ? (
        <p className="mt-2.5 text-xs text-text-muted">{verdict.plan_note}</p>
      ) : null}

      {failed.length > 0 ? (
        <p className="mt-3 rounded-token bg-stance-avoid-soft px-2.5 py-1.5 text-xs text-stance-avoid">
          Gate failed: {failed.map((gate) => gate.label).join(", ")} — {failed[0].reason}
        </p>
      ) : null}

      {verdict.narrative ? (
        <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-text-secondary">
          {verdict.narrative}
        </p>
      ) : null}

      <details className="mt-3 border-t border-border-subtle pt-2.5">
        <summary className="cursor-pointer text-xs font-medium text-text-muted hover:text-text-primary">
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
 * computed: no count of how many strategies agree, no average conviction, no ordering by
 * consensus. Each card receives exactly one verdict.
 */
export function VerdictRow({ ticker, verdicts }: { ticker: string; verdicts: Verdict[] }) {
  const ordered = [...verdicts].sort((a, b) => a.strategy_id.localeCompare(b.strategy_id));

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold text-text-primary">{ticker}</h2>
      <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {ordered.map((verdict) => (
          <VerdictCard key={verdict.strategy_id} verdict={verdict} />
        ))}
      </div>
    </section>
  );
}
