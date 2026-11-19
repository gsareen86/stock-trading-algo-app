"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { LiveProgressCard, type ProgressStep, useSseStream } from "@/components/live-progress";
import { Empty } from "@/components/states";
import type { Theme, ThemeRun } from "@/lib/api";

const THEME_STEPS: ProgressStep[] = [
  { id: "concalls", label: "Scout & Concalls" },
  { id: "extract", label: "Extract Concepts" },
  { id: "chain", label: "Supply-Chain Tiers" },
  { id: "candidates", label: "Match NSE 750" },
];

type ThemeFilter = "all" | "multi_period" | "multi_sector" | "web_policy";

function RunStatePill({ run }: { run: ThemeRun | null }) {
  if (run === null) {
    return (
      <span className="rounded-token bg-surface-sunken px-2.5 py-1 text-xs text-text-muted">
        No theme run completed yet
      </span>
    );
  }
  if (run.outcome === "no_reading") {
    return (
      <span className="rounded-token border border-stance-watch bg-stance-watch-soft px-2.5 py-1 text-xs font-medium text-stance-watch">
        no_reading ({run.sources_unavailable.join(", ") || "sources unreachable"}) — not an empty market
      </span>
    );
  }
  const missing =
    run.sources_unavailable.length > 0
      ? ` · unavail: ${run.sources_unavailable.join(", ")}`
      : "";
  return (
    <span className="tabular-nums rounded-token border border-border-subtle bg-surface-raised px-2.5 py-1 text-xs text-text-secondary">
      Last run: <strong className="text-text-primary">{run.outcome}</strong> · {run.documents_read}{" "}
      doc(s) read{missing}
    </span>
  );
}

export function ThemesExplorer({
  themes,
  latestRun,
}: {
  themes: Theme[];
  latestRun: ThemeRun | null;
}) {
  const router = useRouter();
  const stream = useSseStream<Record<string, unknown>>();
  const [filter, setFilter] = useState<ThemeFilter>("all");
  const [doneMsg, setDoneMsg] = useState<string | null>(null);

  async function runThemeDiscovery() {
    setDoneMsg(null);
    await stream.start("/api/backend/themes/run/stream", { trigger: "requested" }, (data) => {
      const docs = typeof data.documents_read === "number" ? data.documents_read : 0;
      setDoneMsg(
        `Theme run ${String(data.outcome ?? "complete")} — ${docs} documents processed.`,
      );
      router.refresh();
    });
  }

  const filtered = useMemo(() => {
    if (filter === "multi_period") return themes.filter((t) => t.persistence >= 2);
    if (filter === "multi_sector") return themes.filter((t) => t.sector_count >= 2);
    if (filter === "web_policy") {
      return themes.filter((t) =>
        t.source_kinds.some((k) => k === "web_search" || k === "policy" || k === "filing"),
      );
    }
    return themes;
  }, [themes, filter]);

  return (
    <div className="space-y-6">
      {/* Themes Hero Card */}
      <section className="hero-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Supply-Chain &amp; Catalyst Lab
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text-primary">
              Emerging Themes
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-text-secondary">
              What companies, policy announcements, and concalls are surfacing — expanded into upstream &amp; downstream NSE supply chains without fabricating strategy verdicts.
            </p>
          </div>

          <button
            type="button"
            disabled={stream.running}
            onClick={runThemeDiscovery}
            className="rounded-token bg-accent px-4 py-2 text-xs font-semibold text-surface-raised transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {stream.running ? "Running Discovery…" : "Run Theme & Web Discovery"}
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-3">
          <RunStatePill run={latestRun} />
          <div className="flex flex-wrap gap-1.5">
            {(
              [
                { id: "all", label: `All (${themes.length})` },
                { id: "multi_period", label: "Multi-Period (2+)" },
                { id: "multi_sector", label: "Multi-Sector (2+)" },
                { id: "web_policy", label: "Policy / Web" },
              ] as const
            ).map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilter(f.id)}
                className={`rounded-token border px-2.5 py-1 text-xs font-medium ${
                  filter === f.id
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border-subtle bg-surface-raised text-text-secondary hover:text-text-primary"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <LiveProgressCard
          title="IdeaScout + Theme Discovery Run"
          steps={THEME_STEPS}
          running={stream.running}
          progress={stream.progress}
          elapsed={stream.elapsed}
          error={stream.error}
          completeSummary={doneMsg}
        />
      </section>

      {filtered.length === 0 ? (
        <Empty>
          {latestRun === null
            ? "No theme run has completed yet. Run discovery above to inspect emerging catalysts."
            : themes.length === 0
              ? "The last run read its sources and found nothing that cleared breadth thresholds."
              : "No themes match this filter."}
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filtered.map((theme) => (
            <Link
              key={theme.key}
              href={`/themes/${encodeURIComponent(theme.key)}`}
              className="card-surface card-interactive flex flex-col justify-between p-5"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <h2 className="text-base font-semibold text-text-primary">{theme.label}</h2>
                  <span className="shrink-0 rounded-token bg-surface-sunken px-2 py-0.5 font-mono text-[10px] text-text-muted">
                    {theme.key}
                  </span>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2">
                  <div className="rounded-token bg-surface-sunken px-2.5 py-2">
                    <span className="block text-[10px] uppercase text-text-muted">Breadth</span>
                    <span className="tabular-nums font-mono text-sm font-semibold text-text-primary">
                      {theme.breadth}
                    </span>
                  </div>
                  <div className="rounded-token bg-surface-sunken px-2.5 py-2">
                    <span className="block text-[10px] uppercase text-text-muted">Sectors</span>
                    <span className="tabular-nums font-mono text-sm font-semibold text-text-primary">
                      {theme.sector_count}
                    </span>
                  </div>
                  <div className="rounded-token bg-surface-sunken px-2.5 py-2">
                    <span className="block text-[10px] uppercase text-text-muted">Periods</span>
                    <span className="tabular-nums font-mono text-sm font-semibold text-text-primary">
                      {theme.persistence}
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-3 text-[11px] text-text-muted">
                <div className="flex flex-wrap gap-1">
                  {theme.source_kinds.map((sk) => (
                    <span
                      key={sk}
                      className="rounded-token border border-border-subtle bg-surface-base px-1.5 py-0.5 font-mono text-[10px] text-text-secondary"
                    >
                      {sk}
                    </span>
                  ))}
                </div>
                <span className="font-medium text-accent">Supply Chain →</span>
              </div>
            </Link>
          ))}
        </div>
      )}

      <p className="text-xs text-text-muted">
        A theme surfaces on counted breadth and persistence, never on a model&apos;s opinion of what is interesting. Nothing here carries a stance — click into any candidate to inspect the four strategies independently.
      </p>
    </div>
  );
}
