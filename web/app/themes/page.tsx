import Link from "next/link";

import { Empty, Unavailable } from "@/components/states";
import { type Theme, type ThemeRun, fetchThemes } from "@/lib/api";

/**
 * Themes — what is emerging, and who is positioned to be paid by it.
 *
 * Answers a different question from Ideas. Ideas measures relative strength and asks what is
 * worth looking at *now*; this reads what companies and policy are saying and asks what is
 * worth looking at *next*. A theme says where to look before the price moves; rotation says
 * whether it has started, and disagreement between them is information.
 *
 * **Nothing here carries a stance.** A theme is a lens, not a verdict — every candidate it
 * surfaces gets the same four readings as any other name, on its own Stock surface.
 */

export const dynamic = "force-dynamic";

/** Three run states that look alike on a naive screen and mean entirely different things. */
function RunState({ run }: { run: ThemeRun | null }) {
  if (run === null) {
    return (
      <span className="text-xs text-text-muted">No theme run has completed yet.</span>
    );
  }

  if (run.outcome === "no_reading") {
    // The distinction this surface exists to preserve: nothing was read, so nothing is
    // known. Rendering it the same as "no themes found" would report a broken downloader
    // as a quiet market.
    return (
      <span className="text-xs text-stance-watch">
        Last run could read no sources ({run.sources_unavailable.join(", ") || "all"}) — this
        is not the same as finding nothing.
      </span>
    );
  }

  const missing =
    run.sources_unavailable.length > 0
      ? ` · could not read ${run.sources_unavailable.join(", ")}`
      : "";

  return (
    <span className="text-xs text-text-muted">
      Last run {run.outcome} · {run.documents_read} document(s) read{missing}
    </span>
  );
}

function ThemeCard({ theme }: { theme: Theme }) {
  return (
    <Link
      href={`/themes/${encodeURIComponent(theme.key)}`}
      className="block rounded-token-lg border border-border-subtle bg-surface-raised p-4 hover:border-border-strong"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-text-primary">{theme.label}</h3>
        <span className="font-mono text-[11px] text-text-muted">{theme.key}</span>
      </div>

      {/* The counts *are* the claim, so they lead. "Three companies across two sectors, in
          two periods" is something a reader can disagree with; "emerging theme" is not. */}
      <p className="mt-2 text-sm text-text-secondary">
        {theme.breadth} compan{theme.breadth === 1 ? "y" : "ies"} across {theme.sector_count}{" "}
        sector{theme.sector_count === 1 ? "" : "s"}, in {theme.persistence} period
        {theme.persistence === 1 ? "" : "s"}
      </p>

      <p className="mt-2 text-[11px] text-text-muted">
        from {theme.source_kinds.join(", ") || "no source"}
        {theme.first_seen_at ? ` · first seen ${theme.first_seen_at.slice(0, 10)}` : null}
      </p>
    </Link>
  );
}

export default async function ThemesPage() {
  const result = await fetchThemes();

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Themes</h1>
          <p className="mt-1 text-sm text-text-secondary">
            What is emerging, and who is positioned to be paid by it
          </p>
        </div>
        {result.ok ? <RunState run={result.data.latest_run} /> : null}
      </div>

      <div className="mt-8">
        {!result.ok ? (
          <Unavailable result={result} />
        ) : result.data.themes.length === 0 ? (
          <Empty>
            {result.data.latest_run === null
              ? "No theme run has completed. Run one to look for what is emerging."
              : "The last run read its sources and found nothing that cleared the thresholds."}
          </Empty>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {result.data.themes.map((theme) => (
              <ThemeCard key={theme.key} theme={theme} />
            ))}
          </div>
        )}
      </div>

      <p className="mt-10 text-xs text-text-muted">
        A theme surfaces on counted breadth and persistence, never on a model&apos;s opinion of
        what is interesting. Nothing on this page carries a stance — every candidate a theme
        surfaces is read by the same four strategies as any other name.
      </p>
    </div>
  );
}
