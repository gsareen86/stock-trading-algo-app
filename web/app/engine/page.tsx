import { type CallRecord, type Usage, fetchCalls, fetchUsage } from "@/lib/api";

/**
 * Engine — under the hood.
 *
 * Currently the LLM accounting panel. Config, run history, agent traces and the backtest lab
 * arrive with their own changes; what is here reads the platform's own `llm_calls` ledger, so
 * cost and failures are visible with no Langfuse account configured.
 */

export const dynamic = "force-dynamic";

const STATUS_TONE: Record<string, string> = {
  ok: "text-stance-buy",
  cached: "text-text-secondary",
  failed: "text-stance-avoid",
  rate_limited: "text-stance-watch",
  breaker_open: "text-stance-watch",
  budget_exceeded: "text-stance-watch",
};

/** A paisa — below this an amount is real but not renderable as a two-decimal figure. */
const PAISA = 0.01;

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "₹0.00";
  // A real spend must never render as ₹0.00. Below a paisa the exact figure is noise nobody
  // can act on — this panel answers "is this getting expensive", and the auditable amount is
  // the dollar figure the vendor actually billed, which the API returns alongside.
  if (Math.abs(value) < PAISA) return "< ₹0.01";
  return `₹${value.toFixed(2)}`;
}

function Card({
  title,
  children,
  right,
}: {
  title: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section className="rounded-token-lg border border-border-subtle bg-surface-raised p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          {title}
        </h2>
        {right}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-xs text-text-muted">{label}</p>
      <p className="mt-0.5 font-mono text-lg text-text-primary">{value}</p>
      {hint ? <p className="text-xs text-text-muted">{hint}</p> : null}
    </div>
  );
}

function BudgetBar({ budget }: { budget: Usage["budget"] }) {
  if (budget.cap_inr === null) {
    return (
      <p className="text-sm text-text-secondary">
        No daily cap set. Configure{" "}
        <code className="rounded-token bg-surface-sunken px-1.5 py-0.5 font-mono text-xs">
          LLM_DAILY_BUDGET_INR
        </code>{" "}
        to limit spend on paid providers.
      </p>
    );
  }

  const pct = Math.min(100, (budget.spent_today_inr / budget.cap_inr) * 100);
  const tone = budget.exhausted
    ? "bg-status-down"
    : pct > 75
      ? "bg-status-degraded"
      : "bg-status-ok";

  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-mono text-text-primary">
          {money(budget.spent_today_inr)} / {money(budget.cap_inr)}
        </span>
        <span className="text-xs text-text-secondary">
          {budget.exhausted ? "cap reached" : `${money(budget.remaining_inr)} left`}
        </span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      {budget.exhausted ? (
        <p className="mt-2 text-xs text-text-secondary">
          Paid providers are being refused. Tasks routed to local models still run.
        </p>
      ) : null}
    </div>
  );
}

function Breakdown({ title, buckets }: { title: string; buckets: Record<string, Usage["totals"]> }) {
  const entries = Object.entries(buckets);
  if (entries.length === 0) {
    return <p className="text-sm text-text-secondary">Nothing recorded yet.</p>;
  }
  return (
    <Card title={title}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[22rem] text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-text-muted">
              <th className="pb-2 font-medium">Name</th>
              <th className="pb-2 text-right font-medium">Calls</th>
              <th className="pb-2 text-right font-medium">Tokens</th>
              <th className="pb-2 text-right font-medium">Spend</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([name, bucket]) => (
              <tr key={name} className="border-t border-border-subtle">
                <td className="py-2 text-text-primary">{name}</td>
                <td className="py-2 text-right font-mono text-xs text-text-secondary">
                  {bucket.calls}
                  {bucket.failed_calls > 0 ? (
                    <span className="text-stance-avoid"> ({bucket.failed_calls} failed)</span>
                  ) : null}
                </td>
                <td className="py-2 text-right font-mono text-xs text-text-secondary">
                  {bucket.total_tokens.toLocaleString()}
                </td>
                <td className="py-2 text-right font-mono text-xs text-text-secondary">
                  {bucket.priced_calls === 0 ? "free" : money(bucket.spend_inr)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function RecentCalls({ calls }: { calls: CallRecord[] }) {
  if (calls.length === 0) {
    return (
      <Card title="Recent calls">
        <p className="text-sm text-text-secondary">
          No LLM calls recorded yet. They appear here as soon as any task runs — successes and
          failures alike.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Recent calls">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[38rem] text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-text-muted">
              <th className="pb-2 font-medium">When</th>
              <th className="pb-2 font-medium">Task</th>
              <th className="pb-2 font-medium">Model</th>
              <th className="pb-2 font-medium">Status</th>
              <th className="pb-2 text-right font-medium">Tokens</th>
              <th className="pb-2 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((call) => (
              <tr key={call.id} className="border-t border-border-subtle align-top">
                <td className="py-2 font-mono text-xs text-text-muted">
                  {new Date(call.created_at).toLocaleTimeString("en-IN", {
                    timeZone: "Asia/Kolkata",
                  })}
                </td>
                <td className="py-2 text-text-primary">{call.task}</td>
                <td className="py-2 font-mono text-xs text-text-secondary">
                  {call.model}
                  {call.used_fallback ? (
                    <span
                      className="ml-1 text-stance-watch"
                      title={`fell back from ${call.requested_model}`}
                    >
                      ↳ fallback
                    </span>
                  ) : null}
                </td>
                <td className={`py-2 font-mono text-xs ${STATUS_TONE[call.status] ?? ""}`}>
                  {call.status}
                  {call.error_msg ? (
                    <span className="block max-w-[16rem] truncate text-text-muted">
                      {call.error_msg}
                    </span>
                  ) : null}
                </td>
                <td className="py-2 text-right font-mono text-xs text-text-secondary">
                  {call.total_tokens ?? "—"}
                </td>
                <td className="py-2 text-right font-mono text-xs text-text-secondary">
                  {money(call.cost_inr)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default async function EnginePage() {
  const [usageResult, callsResult] = await Promise.all([fetchUsage(7), fetchCalls(20)]);

  if (!usageResult.ok) {
    return (
      <section className="mx-auto max-w-6xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Engine</h1>
        <div className="mt-8 rounded-token-lg border border-status-down bg-surface-raised p-5">
          <h2 className="text-sm font-medium text-text-primary">Cannot reach the backend</h2>
          <p className="mt-2 text-sm text-text-secondary">
            Tried{" "}
            <code className="rounded-token bg-surface-sunken px-1.5 py-0.5 font-mono text-xs">
              {usageResult.attemptedUrl}
            </code>{" "}
            and got <span className="font-mono text-xs">{usageResult.error}</span>.
          </p>
        </div>
      </section>
    );
  }

  const usage = usageResult.data;
  const calls = callsResult.ok ? callsResult.data.calls : [];
  const { totals } = usage;

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Engine</h1>
          <p className="mt-1 text-sm text-text-secondary">
            LLM cost and activity, from the platform&apos;s own ledger — last {usage.days} IST
            days
          </p>
          {/* Vendors bill in dollars; the rate that produced every ₹ figure here is stated
              rather than assumed, so any number can be traced back to what was charged. */}
          <p className="mt-0.5 text-xs text-text-muted">
            Converted at ₹{usage.usd_inr_rate.toFixed(2)} to the dollar (
            <code className="font-mono">USD_INR_RATE</code>)
          </p>
        </div>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <Card title="Spend">
          <div className="grid grid-cols-3 gap-4">
            <Stat
              label="Priced"
              value={money(totals.spend_inr)}
              hint={`${totals.priced_calls} call${totals.priced_calls === 1 ? "" : "s"}`}
            />
            <Stat
              label="Free"
              value={String(totals.unpriced_calls)}
              hint="local models"
            />
            <Stat label="Tokens" value={totals.total_tokens.toLocaleString()} />
          </div>
          {totals.unpriced_calls > 0 ? (
            <p className="mt-3 text-xs text-text-muted">
              Spend covers priced calls only. Local-model calls report no cost and are counted
              separately rather than as zero.
            </p>
          ) : null}
        </Card>

        <Card title="Today's budget">
          <BudgetBar budget={usage.budget} />
        </Card>

        <Breakdown title="By task" buckets={usage.by_task} />
        <Breakdown title="By provider" buckets={usage.by_provider} />
      </div>

      <div className="mt-4">
        <RecentCalls calls={calls} />
      </div>
    </div>
  );
}
