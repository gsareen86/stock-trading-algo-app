import Link from "next/link";

import { TodayActions } from "@/components/today-actions";
import { TodayInsights } from "@/components/today-insights";
import {
  type Health,
  type IndexSnapshot,
  fetchBriefing,
  fetchHealth,
  fetchInsights,
} from "@/lib/api";

export const dynamic = "force-dynamic";

type SeamState = "ok" | "degraded" | "down" | "off";

function StatusDot({ state }: { state: SeamState }) {
  const color =
    state === "ok"
      ? "bg-status-ok"
      : state === "degraded"
        ? "bg-status-degraded"
        : state === "off"
          ? "bg-border-strong"
          : "bg-status-down";
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${color}`} aria-hidden />;
}

function SeamRow({
  label,
  value,
  state,
  detail,
}: {
  label: string;
  value: string;
  state: SeamState;
  detail?: string | null;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border-subtle py-2 last:border-b-0">
      <div className="min-w-0">
        <p className="text-xs font-medium text-text-primary">{label}</p>
        {detail ? <p className="mt-0.5 truncate text-[11px] text-text-muted">{detail}</p> : null}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <StatusDot state={state} />
        <span className="font-mono text-[11px] text-text-secondary">{value}</span>
      </div>
    </div>
  );
}

function indexTone(snap?: IndexSnapshot): string {
  if (!snap || !snap.available) return "text-text-muted";
  if (snap.posture === "constructive") return "text-stance-buy";
  if (snap.posture === "cautious") return "text-stance-watch";
  return "text-stance-avoid";
}

function formatIndexLine(snap?: IndexSnapshot): string {
  if (!snap || !snap.available) return "Unavailable";
  const pct =
    typeof snap.change_pct === "number"
      ? `${snap.change_pct >= 0 ? "+" : ""}${snap.change_pct.toFixed(2)}%`
      : "";
  const close =
    typeof snap.close === "number" ? snap.close.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "—";
  return `${close} ${pct}`.trim();
}

function defaultProvider(health: Health): string {
  return health.llm.default_model.split("/")[0];
}

export default async function TodayPage() {
  const [healthRes, feedRes, briefingRes] = await Promise.all([
    fetchHealth(),
    fetchInsights(),
    fetchBriefing(),
  ]);

  const briefing = briefingRes.ok ? briefingRes.data : null;
  const sessionLabel = briefing?.market.session ?? "NSE Research Window";
  const istLabel = briefing?.market.ist_time_label ?? "IST";
  const scan = briefing?.scan_status;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      {/* Morning Briefing Hero Card */}
      <section className="hero-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-token border border-border-subtle bg-surface-raised px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-accent">
                {sessionLabel}
              </span>
              <span className="font-mono text-xs text-text-muted">{istLabel}</span>
              {scan?.has_scan ? (
                <span
                  className={`rounded-token px-2 py-0.5 text-[11px] font-medium ${
                    scan.stale
                      ? "bg-stance-watch-soft text-stance-watch"
                      : "bg-stance-buy-soft text-stance-buy"
                  }`}
                >
                  {scan.stale
                    ? scan.stale_reason ?? "Scan catch-up recommended"
                    : `Scan #${scan.run_id} fresh (${scan.eligible_count ?? 0} setups)`}
                </span>
              ) : (
                <span className="rounded-token bg-surface-sunken px-2 py-0.5 text-[11px] text-text-muted">
                  No Nifty 750 scan recorded yet
                </span>
              )}
            </div>
            <h1 className="mt-2.5 text-2xl font-semibold tracking-tight text-text-primary">
              Morning Briefing
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Market regime, sector rotations, watchlist pivot triggers, and what needs your decision today.
            </p>
          </div>

          {healthRes.ok ? (
            <div className="flex items-center gap-2 rounded-token border border-border-subtle bg-surface-raised px-3 py-1.5 text-xs text-text-secondary">
              <StatusDot state={healthRes.health.status === "ok" ? "ok" : "degraded"} />
              <span>
                Backend {healthRes.health.status} · v{healthRes.health.app.version}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-token border border-status-down bg-surface-raised px-3 py-1.5 text-xs text-stance-avoid">
              <StatusDot state="down" />
              <span>Backend unreachable</span>
            </div>
          )}
        </div>

        <div className="mt-5">
          <TodayActions />
        </div>

        {/* 4-Tile Bento KPI Strip */}
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-token-lg border border-border-subtle bg-surface-raised p-3.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Market Regime
            </p>
            <p className={`tabular-nums mt-1.5 font-mono text-base font-semibold ${indexTone(briefing?.market.nifty50)}`}>
              N50: {formatIndexLine(briefing?.market.nifty50)}
            </p>
            <p className="tabular-nums mt-0.5 font-mono text-xs text-text-secondary">
              N500: {formatIndexLine(briefing?.market.nifty500)}
            </p>
          </div>

          <Link
            href="/ideas"
            className="card-interactive rounded-token-lg border border-border-subtle bg-surface-raised p-3.5"
          >
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Rotating Sectors
            </p>
            <p className="tabular-nums mt-1.5 font-mono text-base font-semibold text-text-primary">
              {briefing ? `${briefing.sectors_summary.leading_count} Leading` : "—"}
              <span className="ml-2 text-xs font-medium text-quadrant-improving">
                {briefing ? `· ${briefing.sectors_summary.improving_count} Improving` : ""}
              </span>
            </p>
            <p className="mt-0.5 truncate text-xs text-text-secondary">
              {briefing && briefing.sectors_summary.shifts.length > 0
                ? `${briefing.sectors_summary.shifts.length} recent rotation shift(s)`
                : "Open Sector RRG & Setups →"}
            </p>
          </Link>

          <Link
            href="/watchlist"
            className="card-interactive rounded-token-lg border border-border-subtle bg-surface-raised p-3.5"
          >
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Watchlist Triggers
            </p>
            <p className="tabular-nums mt-1.5 font-mono text-base font-semibold text-text-primary">
              {briefing ? `${briefing.watchlist_pulse.flipped_buy_count} BUY Flips` : "—"}
            </p>
            <p className="mt-0.5 text-xs text-text-secondary">
              {briefing
                ? `${briefing.watchlist_pulse.near_pivot_count} near pivot · ${briefing.watchlist_pulse.total_watched} tracked`
                : "Track pivot proximity →"}
            </p>
          </Link>

          <Link
            href="/positions"
            className="card-interactive rounded-token-lg border border-border-subtle bg-surface-raised p-3.5"
          >
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Paper Books
            </p>
            <p className="tabular-nums mt-1.5 font-mono text-base font-semibold text-text-primary">
              {briefing ? `${briefing.books.total_open} Open Positions` : "—"}
            </p>
            <p className="tabular-nums mt-0.5 text-xs text-text-secondary">
              {briefing
                ? `Swing ${briefing.books.swing_open} · Long-Term ${briefing.books.longterm_open}`
                : "Inspect books & health →"}
            </p>
          </Link>
        </div>
      </section>

      {/* Main 12-Col Workspace */}
      <div className="grid gap-6 lg:grid-cols-12">
        <section className="lg:col-span-8">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
              Prioritized Attention Feed
            </h2>
          </div>
          <TodayInsights feed={feedRes} />
        </section>

        <aside className="space-y-5 lg:col-span-4">
          {/* Watchlist Pulse Sidebar Card */}
          <section className="card-surface p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Watchlist Pulse
              </h2>
              <Link href="/watchlist" className="text-xs font-medium text-accent hover:underline">
                View all →
              </Link>
            </div>

            {briefing && briefing.watchlist_pulse.items.length > 0 ? (
              <div className="mt-3 space-y-2.5">
                {briefing.watchlist_pulse.items.slice(0, 5).map((item) => (
                  <Link
                    key={item.symbol}
                    href={`/stock?symbol=${encodeURIComponent(item.symbol)}`}
                    className="block rounded-token border border-border-subtle bg-surface-sunken p-2.5 transition-colors hover:border-border-strong"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs font-semibold text-text-primary">
                        {item.symbol}
                      </span>
                      {item.flipped_buy ? (
                        <span className="rounded-token bg-stance-buy-soft px-1.5 py-0.5 text-[10px] font-semibold text-stance-buy">
                          WATCH → BUY
                        </span>
                      ) : (
                        <span className="tabular-nums font-mono text-[11px] text-text-secondary">
                          {item.distance_pct >= 0 ? `${item.distance_pct}% to entry` : "extended"}
                        </span>
                      )}
                    </div>
                    <p className="tabular-nums mt-1 font-mono text-[11px] text-text-muted">
                      Last ₹{item.last_price ?? "—"} · Entry ₹{item.entry ?? "—"} · Stop ₹
                      {item.stop ?? "—"}
                    </p>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-xs text-text-secondary">
                No watched stocks near pivot yet. Add candidates from{" "}
                <Link href="/ideas" className="text-accent underline">
                  Ideas
                </Link>{" "}
                or{" "}
                <Link href="/watchlist" className="text-accent underline">
                  Watchlist
                </Link>
                .
              </p>
            )}
          </section>

          {/* Quiet 4-State Seam Health Card */}
          <section className="card-surface p-5">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
              System Seams
            </h2>
            {healthRes.ok ? (
              <div className="mt-3">
                <SeamRow
                  label="Supabase / Postgres"
                  value={
                    !healthRes.health.database.connected
                      ? "unreachable"
                      : healthRes.health.database.migrations_current
                        ? (healthRes.health.database.current_revision ?? "current")
                        : "behind head"
                  }
                  state={
                    !healthRes.health.database.connected
                      ? "down"
                      : healthRes.health.database.migrations_current
                        ? "ok"
                        : "degraded"
                  }
                  detail={healthRes.health.database.reason}
                />
                <SeamRow
                  label="Default LLM"
                  value={healthRes.health.llm.default_model}
                  state={healthRes.health.llm.default_model_usable ? "ok" : "degraded"}
                  detail={
                    healthRes.health.llm.default_model_usable
                      ? null
                      : `${defaultProvider(healthRes.health)} not configured`
                  }
                />
                <SeamRow
                  label={healthRes.health.observability.provider}
                  value={healthRes.health.observability.configured ? "tracing" : "off"}
                  state={healthRes.health.observability.configured ? "ok" : "off"}
                />
                {healthRes.health.llm.providers
                  .filter((p) => p.configured || p.name === "ollama")
                  .map((p) => (
                    <SeamRow
                      key={p.name}
                      label={`LLM: ${p.name}`}
                      value={
                        !p.configured
                          ? "off"
                          : p.reachable === false
                            ? "unreachable"
                            : "ready"
                      }
                      state={
                        !p.configured ? "off" : p.reachable === false ? "down" : "ok"
                      }
                      detail={p.detail}
                    />
                  ))}
              </div>
            ) : (
              <div className="mt-3 rounded-token border border-status-down bg-surface-sunken p-3 text-xs text-text-secondary">
                <p className="font-semibold text-stance-avoid">Backend unreachable</p>
                <p className="mt-1 font-mono text-[11px]">{healthRes.error}</p>
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
