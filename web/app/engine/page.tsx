import { Unavailable } from "@/components/states";
import {
  type CallRecord,
  type Usage,
  fetchCalls,
  fetchDiscoveryRuns,
  fetchHealth,
  fetchThemeRuns,
  fetchTools,
  fetchUsage,
} from "@/lib/api";

export const dynamic = "force-dynamic";

const STATUS_TONE: Record<string, string> = {
  ok: "text-stance-buy",
  cached: "text-text-secondary",
  failed: "text-stance-avoid",
  rate_limited: "text-stance-watch",
  breaker_open: "text-stance-watch",
  budget_exceeded: "text-stance-watch",
};

const PAISA = 0.01;

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "₹0.00";
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
    <section className="card-surface p-5">
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
    <div className="rounded-token bg-surface-sunken p-3">
      <p className="text-[11px] text-text-muted">{label}</p>
      <p className="tabular-nums mt-0.5 font-mono text-lg font-semibold text-text-primary">
        {value}
      </p>
      {hint ? <p className="text-[11px] text-text-muted">{hint}</p> : null}
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
        to bound spend on paid providers. Local Ollama calls remain unpriced and uncapped.
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
        <span className="tabular-nums font-mono font-semibold text-text-primary">
          {money(budget.spent_today_inr)} / {money(budget.cap_inr)}
        </span>
        <span className="text-xs text-text-secondary">
          {budget.exhausted ? "cap reached" : `${money(budget.remaining_inr)} left`}
        </span>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-surface-sunken">
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      {budget.exhausted ? (
        <p className="mt-2 text-xs text-text-secondary">
          Paid providers are refused for today. Local Ollama models still execute normally.
        </p>
      ) : null}
    </div>
  );
}

function Breakdown({ title, buckets }: { title: string; buckets: Record<string, Usage["totals"]> }) {
  const entries = Object.entries(buckets);
  return (
    <Card title={title}>
      {entries.length === 0 ? (
        <p className="text-sm text-text-secondary">Nothing recorded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[20rem] text-sm">
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
                  <td className="py-2 font-mono text-xs text-text-primary">{name}</td>
                  <td className="tabular-nums py-2 text-right font-mono text-xs text-text-secondary">
                    {bucket.calls}
                    {bucket.failed_calls > 0 ? (
                      <span className="text-stance-avoid"> ({bucket.failed_calls} failed)</span>
                    ) : null}
                  </td>
                  <td className="tabular-nums py-2 text-right font-mono text-xs text-text-secondary">
                    {bucket.total_tokens.toLocaleString()}
                  </td>
                  <td className="tabular-nums py-2 text-right font-mono text-xs text-text-secondary">
                    {bucket.priced_calls === 0 ? "free" : money(bucket.spend_inr)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function RecentCalls({ calls }: { calls: CallRecord[] }) {
  return (
    <Card title={`Recent LLM Calls (${calls.length})`}>
      {calls.length === 0 ? (
        <p className="text-sm text-text-secondary">
          No LLM calls recorded yet. Calls appear here as soon as narratives, research Q&amp;A, or theme agents execute.
        </p>
      ) : (
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
                  <td className="tabular-nums py-2 font-mono text-xs text-text-muted">
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
                  <td className="tabular-nums py-2 text-right font-mono text-xs text-text-secondary">
                    {call.total_tokens ?? "—"}
                  </td>
                  <td className="tabular-nums py-2 text-right font-mono text-xs text-text-secondary">
                    {money(call.cost_inr)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default async function EnginePage() {
  const [usageResult, callsResult, healthResult, toolsResult, scanRunsRes, themeRunsRes] =
    await Promise.all([
      fetchUsage(7),
      fetchCalls(20),
      fetchHealth(),
      fetchTools(),
      fetchDiscoveryRuns(5),
      fetchThemeRuns(5),
    ]);

  if (!usageResult.ok) {
    return (
      <section className="mx-auto max-w-6xl px-6 py-10">
        <Unavailable result={usageResult} />
      </section>
    );
  }

  const usage = usageResult.data;
  const calls = callsResult.ok ? callsResult.data.calls : [];
  const { totals } = usage;
  const routes = healthResult.ok ? Object.entries(healthResult.health.llm.routes) : [];
  const tools = toolsResult.ok ? toolsResult.data.tools : [];
  const scanRuns = scanRunsRes.ok ? scanRunsRes.data.runs : [];
  const themeRuns = themeRunsRes.ok ? themeRunsRes.data.runs : [];

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      {/* Hero Cost & Budget Strip */}
      <section className="hero-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Observability, Models &amp; Scheduler
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text-primary">
              Engine
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Last {usage.days} IST days from the platform&apos;s own ledger · USD converted at{" "}
              <span className="tabular-nums font-mono">₹{usage.usd_inr_rate.toFixed(2)}</span> (
              <code className="font-mono">USD_INR_RATE</code>).
            </p>
          </div>

          <div className="rounded-token border border-border-subtle bg-surface-raised px-3 py-1.5 text-xs text-text-secondary">
            Daily Scan Schedule: <strong className="font-mono text-text-primary">16:15 IST</strong>
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div className="grid grid-cols-3 gap-2.5">
            <Stat
              label="Priced Spend"
              value={money(totals.spend_inr)}
              hint={`${totals.priced_calls} call(s)`}
            />
            <Stat
              label="Free Local"
              value={String(totals.unpriced_calls)}
              hint="Ollama / llama.cpp"
            />
            <Stat label="Total Tokens" value={totals.total_tokens.toLocaleString()} />
          </div>

          <div className="rounded-token-lg border border-border-subtle bg-surface-raised p-4">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Today&apos;s Paid Provider Budget
            </p>
            <BudgetBar budget={usage.budget} />
          </div>
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <Card
          title="Agents, Task Routing & Registered Tools"
          right={<span className="font-mono text-xs text-text-muted">{tools.length} tools</span>}
        >
          <div className="space-y-3 text-xs">
            <div>
              <p className="font-semibold text-text-primary">
                Default Model:{" "}
                <span className="font-mono text-accent">
                  {healthResult.ok ? healthResult.health.llm.default_model : "—"}
                </span>
              </p>
              {routes.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {routes.map(([task, model]) => (
                    <span
                      key={task}
                      className="rounded-token border border-border-subtle bg-surface-sunken px-2 py-0.5 font-mono text-[11px] text-text-secondary"
                    >
                      {task} → {model}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>

            {tools.length > 0 ? (
              <div className="border-t border-border-subtle pt-3">
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Discovered Tools
                </p>
                <div className="flex flex-wrap gap-1">
                  {tools.map((t) => (
                    <span
                      key={t.name}
                      title={t.summary}
                      className="rounded-token bg-surface-sunken px-2 py-0.5 font-mono text-[11px] text-text-primary"
                    >
                      {t.name}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </Card>

        <Card title="Recent Nifty 750 & Theme Run History">
          <div className="space-y-2 text-xs">
            {scanRuns.length === 0 && themeRuns.length === 0 ? (
              <p className="text-text-secondary">No discovery scans or theme runs recorded yet.</p>
            ) : (
              <>
                {scanRuns.map((run) => (
                  <div
                    key={`scan-${run.id}`}
                    className="flex items-center justify-between gap-2 rounded-token bg-surface-sunken px-3 py-2"
                  >
                    <div>
                      <span className="font-mono font-semibold text-text-primary">
                        Scan #{run.id} ({run.trigger})
                      </span>
                      <p className="text-[11px] text-text-muted">
                        {run.eligible_count} ranked from {run.considered_count} · {run.benchmark}
                      </p>
                    </div>
                    <span
                      className={`font-mono text-[11px] font-semibold ${
                        run.outcome === "complete" ? "text-stance-buy" : "text-stance-watch"
                      }`}
                    >
                      {run.outcome}
                    </span>
                  </div>
                ))}
                {themeRuns.slice(0, 3).map((tr) => (
                  <div
                    key={`theme-${tr.id}`}
                    className="flex items-center justify-between gap-2 rounded-token border border-border-subtle px-3 py-2"
                  >
                    <div>
                      <span className="font-mono font-semibold text-text-primary">
                        Theme Run #{tr.id} ({tr.trigger})
                      </span>
                      <p className="text-[11px] text-text-muted">
                        {tr.documents_read} docs read
                      </p>
                    </div>
                    <span
                      className={`font-mono text-[11px] font-semibold ${
                        tr.outcome === "complete" ? "text-stance-buy" : "text-stance-watch"
                      }`}
                    >
                      {tr.outcome}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>
        </Card>

        <Breakdown title="By Task" buckets={usage.by_task} />
        <Breakdown title="By Provider" buckets={usage.by_provider} />
      </div>

      <RecentCalls calls={calls} />
    </div>
  );
}
