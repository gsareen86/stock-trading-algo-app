import { InsightActions } from "@/components/insight-actions";
import { Empty, Unavailable } from "@/components/states";
import { type Health, type Insight, fetchHealth, fetchInsights } from "@/lib/api";

/**
 * Today — what needs attention right now.
 *
 * The insight feed, with the seam report kept underneath it. The feed leads because that is
 * what the surface is named for; the seam report stays because a broken seam should show up
 * here immediately rather than in a log nobody reads, and an empty feed caused by a dead
 * backend must not read as "nothing to do".
 *
 * Severity is a property of the insight *kind*, declared in the backend. Nothing here computes
 * an importance score or re-orders by one.
 */

// Rendered per request. Without this the page would be prerendered at build time, when the
// backend is not running, and the build would bake in a connection failure.
export const dynamic = "force-dynamic";

function StatusDot({ state }: { state: "ok" | "degraded" | "down" }) {
  const color =
    state === "ok"
      ? "bg-status-ok"
      : state === "degraded"
        ? "bg-status-degraded"
        : "bg-status-down";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} aria-hidden />;
}

function Row({
  label,
  value,
  state,
  detail,
}: {
  label: string;
  value: string;
  state: "ok" | "degraded" | "down";
  detail?: string | null;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border-subtle py-2.5 last:border-b-0">
      <div className="min-w-0">
        <p className="text-sm text-text-primary">{label}</p>
        {detail ? <p className="mt-0.5 text-xs text-text-muted">{detail}</p> : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <StatusDot state={state} />
        <span className="font-mono text-xs text-text-secondary">{value}</span>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-token-lg border border-border-subtle bg-surface-raised p-5">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        {title}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** Provider prefix of the model used for any task without an explicit route. */
function defaultProvider(health: Health): string {
  return health.llm.default_model.split("/")[0];
}

function SeamReport({ health }: { health: Health }) {
  const db = health.database;
  const dbState = !db.connected ? "down" : db.migrations_current ? "ok" : "degraded";
  const dbValue = !db.connected
    ? "unreachable"
    : db.migrations_current
      ? (db.current_revision ?? "current")
      : "behind head";

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card title="Database">
        <Row
          label="Connection"
          value={db.connected ? "connected" : "failed"}
          state={db.connected ? "ok" : "down"}
          detail={db.reason}
        />
        <Row
          label="Schema"
          value={dbValue}
          state={dbState}
          detail={
            db.connected && !db.migrations_current && db.head_revision
              ? `head is ${db.head_revision}`
              : null
          }
        />
      </Card>

      <Card title="Observability">
        <Row
          label={health.observability.provider}
          value={health.observability.configured ? "tracing" : "not configured"}
          state={health.observability.configured ? "ok" : "degraded"}
          detail={
            health.observability.configured
              ? null
              : "Traces, token counts and cost are not being recorded"
          }
        />
        {/* The default model's own provider decides this light — not whether *some*
            provider happens to be configured. A green dot beside a default that cannot
            actually run is precisely the kind of thing this page exists to catch. */}
        <Row
          label="Default model"
          value={health.llm.default_model}
          state={health.llm.default_model_usable ? "ok" : "degraded"}
          detail={
            health.llm.default_model_usable
              ? null
              : `${defaultProvider(health)} is not configured — tasks without an explicit route cannot run`
          }
        />
      </Card>

      <Card title="LLM providers">
        {health.llm.providers.map((provider) => (
          <Row
            key={provider.name}
            label={provider.name}
            value={
              !provider.configured
                ? "not configured"
                : provider.reachable === false
                  ? "unreachable"
                  : "configured"
            }
            state={
              !provider.configured
                ? "degraded"
                : provider.reachable === false
                  ? "down"
                  : "ok"
            }
            detail={provider.detail}
          />
        ))}
      </Card>

      <Card title="Feed">
        <p className="text-sm text-text-secondary">
          No insights yet. The agent cycle that produces them arrives with{" "}
          <code className="rounded-token bg-surface-sunken px-1.5 py-0.5 font-mono text-xs text-accent">
            insights-feed
          </code>
          .
        </p>
      </Card>
    </div>
  );
}


const SEVERITY_TONE: Record<string, string> = {
  high: "border-stance-avoid text-stance-avoid",
  medium: "border-stance-watch text-stance-watch",
  low: "border-border-strong text-text-muted",
};

function InsightCard({ insight }: { insight: Insight }) {
  return (
    <article
      className={`rounded-token-lg border bg-surface-raised p-4 ${
        insight.read ? "border-border-subtle opacity-70" : "border-border-strong"
      }`}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-text-primary">{insight.title}</h3>
        <span
          className={`rounded-token border px-2 py-0.5 text-[11px] uppercase tracking-wider ${
            SEVERITY_TONE[insight.severity] ?? ""
          }`}
        >
          {insight.severity}
        </span>
      </header>

      {insight.body ? (
        <p className="mt-2 text-sm text-text-secondary">{insight.body}</p>
      ) : null}

      <p className="mt-2 text-[11px] text-text-muted">
        {insight.kind}
        {insight.payload?.measured_by_platform === false ? (
          // A headline a model found is a different thing from a measurement this platform
          // made, and a reader deciding whether to sell needs to know which they are reading.
          <span className="ml-2 text-stance-watch">reported by a tool, not measured here</span>
        ) : null}
      </p>

      {!insight.read ? <InsightActions insight={insight} /> : null}
    </article>
  );
}

async function Feed() {
  const result = await fetchInsights();

  if (!result.ok) return <Unavailable result={result} />;
  if (result.data.insights.length === 0) {
    return <Empty>Nothing needs attention. Run a cycle to look for something.</Empty>;
  }

  return (
    <div className="space-y-3">
      {/* Order is the backend's — newest first, severity declared per kind. Nothing here
          re-ranks by a computed importance. */}
      {result.data.insights.map((insight) => (
        <InsightCard key={insight.id} insight={insight} />
      ))}
    </div>
  );
}

export default async function TodayPage() {
  const result = await fetchHealth();

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Today</h1>
          <p className="mt-1 text-sm text-text-secondary">
            What needs my attention right now
          </p>
        </div>
        {result.ok ? (
          <span className="flex items-center gap-2 text-xs text-text-secondary">
            <StatusDot state={result.health.status === "ok" ? "ok" : "degraded"} />
            backend {result.health.status} · v{result.health.app.version} ·{" "}
            {result.health.app.env}
          </span>
        ) : null}
      </div>

      <section className="mt-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Insights
        </h2>
        <div className="mt-3">
          <Feed />
        </div>
      </section>

      <details className="mt-10">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-text-muted">
          Seam report
        </summary>
        <div className="mt-3">
        {result.ok ? (
          <SeamReport health={result.health} />
        ) : (
          <div className="rounded-token-lg border border-status-down bg-surface-raised p-5">
            <div className="flex items-center gap-2">
              <StatusDot state="down" />
              <h2 className="text-sm font-medium text-text-primary">
                Cannot reach the backend
              </h2>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
              Tried{" "}
              <code className="rounded-token bg-surface-sunken px-1.5 py-0.5 font-mono text-xs">
                {result.attemptedUrl}
              </code>{" "}
              and got <span className="font-mono text-xs">{result.error}</span>.
            </p>
            <p className="mt-2 text-xs text-text-muted">
              Start it with{" "}
              <code className="font-mono">uvicorn app.main:app --reload</code> from{" "}
              <code className="font-mono">backend/</code>, or point{" "}
              <code className="font-mono">NEXT_PUBLIC_API_BASE_URL</code> elsewhere.
            </p>
          </div>
        )}
        </div>
      </details>
    </div>
  );
}
