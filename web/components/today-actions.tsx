"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { LiveProgressCard, type ProgressStep, useSseStream } from "@/components/live-progress";

type RunnerKind = "scan" | "themes" | "cycle";

const STEPS_BY_RUNNER: Record<RunnerKind, { title: string; steps: ProgressStep[] }> = {
  scan: {
    title: "Nifty Total Market Discovery Scan",
    steps: [
      { id: "sectors", label: "Sector RRG" },
      { id: "screen", label: "Screen 750" },
      { id: "evaluate", label: "4 Strategies + Plans" },
      { id: "quality", label: "Quality Facets" },
      { id: "narrate", label: "Narrate Head" },
    ],
  },
  themes: {
    title: "Theme & Supply-Chain Discovery",
    steps: [
      { id: "concalls", label: "Scout & Concalls" },
      { id: "extract", label: "Extract Concepts" },
      { id: "chain", label: "Supply-Chain Tiers" },
      { id: "candidates", label: "Match NSE 750" },
    ],
  },
  cycle: {
    title: "Full Research & Book Cycle",
    steps: [
      { id: "market", label: "Market Read" },
      { id: "screen", label: "Screen Candidates" },
      { id: "evaluate", label: "Strategies" },
      { id: "research", label: "Research & Themes" },
      { id: "insights", label: "Surface Insights" },
    ],
  },
};

export function TodayActions() {
  const router = useRouter();
  const stream = useSseStream<Record<string, unknown>>();
  const [activeRunner, setActiveRunner] = useState<RunnerKind | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  async function trigger(kind: RunnerKind) {
    setActiveRunner(kind);
    setSummary(null);
    const endpoint =
      kind === "scan"
        ? "/api/backend/discovery/scan/stream"
        : kind === "themes"
          ? "/api/backend/themes/run/stream"
          : "/api/backend/cycles/run/stream";
    const payload =
      kind === "scan"
        ? { trigger: "requested", narrate: true, narrate_head: 10 }
        : kind === "themes"
          ? { trigger: "requested" }
          : { narrate: false, persist: true, surface_insights: true };

    const res = await stream.start(endpoint, payload, (data) => {
      if (kind === "scan") {
        const eligible = typeof data.eligible_count === "number" ? data.eligible_count : 0;
        const considered = typeof data.considered_count === "number" ? data.considered_count : 0;
        setSummary(`Scan finished: ${eligible} setups persisted from ${considered} evaluated.`);
      } else if (kind === "themes") {
        const docs = typeof data.documents_read === "number" ? data.documents_read : 0;
        setSummary(`Theme run finished (${String(data.outcome ?? "complete")}): ${docs} docs read.`);
      } else {
        setSummary("Cycle finished and insights refreshed.");
      }
      router.refresh();
    });
    if (!res) {
      setSummary(null);
    }
  }

  const config = activeRunner ? STEPS_BY_RUNNER[activeRunner] : null;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={stream.running}
          onClick={() => trigger("scan")}
          className="rounded-token bg-accent px-3.5 py-2 text-xs font-semibold text-surface-raised transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {stream.running && activeRunner === "scan" ? "Scanning Nifty 750…" : "Run Daily Scan"}
        </button>

        <button
          type="button"
          disabled={stream.running}
          onClick={() => trigger("themes")}
          className="rounded-token border border-border-strong bg-surface-raised px-3 py-2 text-xs font-medium text-text-primary transition-colors hover:bg-surface-sunken disabled:opacity-50"
        >
          {stream.running && activeRunner === "themes" ? "Discovering…" : "Discover Themes"}
        </button>

        <button
          type="button"
          disabled={stream.running}
          onClick={() => trigger("cycle")}
          className="rounded-token border border-border-subtle bg-surface-sunken px-3 py-2 text-xs font-medium text-text-secondary transition-colors hover:text-text-primary disabled:opacity-50"
        >
          {stream.running && activeRunner === "cycle" ? "Running Cycle…" : "Run Full Cycle"}
        </button>
      </div>

      {config ? (
        <LiveProgressCard
          title={config.title}
          steps={config.steps}
          running={stream.running}
          progress={stream.progress}
          elapsed={stream.elapsed}
          error={stream.error}
          completeSummary={summary}
        />
      ) : null}
    </div>
  );
}
