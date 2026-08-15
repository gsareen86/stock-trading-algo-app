import { type Health, fetchHealth } from "@/lib/api";

/**
 * Today — the insights feed.
 *
 * In the bootstrap change it carries no insights yet; what it does carry is the live seam
 * report from the backend. That is deliberate: this page is the proof that the
 * browser → API → database → LLM-gateway chain actually works end to end. A broken seam
 * shows up here immediately rather than in a log nobody reads.
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

      <div className="mt-8">
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
    </div>
  );
}
