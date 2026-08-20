"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Starting a cycle from the application.
 *
 * `POST /cycles/run` has existed since `agent-graph-and-a2a` and nothing called it, which is
 * the whole reason a feed could sit unchanged for days: the only way to refresh it was a
 * terminal. A feed that can only be refreshed by someone who remembers the curl incantation
 * will go stale again by Thursday.
 *
 * It **blocks while the run happens**, deliberately. A button that waits honestly is better
 * than no button, and `progress-visibility` is the change that has real steps to stream —
 * inventing a job record here would only be something that change immediately replaced.
 */

type Outcome = {
  written: number;
  suppressed: number;
  refreshed: number;
  withdrawn: number;
  truncated: number;
};

function summarise(outcome: Outcome): string {
  // Named counts rather than a total: "nothing written" and "nothing changed" are different
  // results, and a run that withdrew three stale insights did real work.
  const parts = [
    outcome.written ? `${outcome.written} new` : null,
    outcome.refreshed ? `${outcome.refreshed} updated` : null,
    outcome.withdrawn ? `${outcome.withdrawn} withdrawn` : null,
  ].filter(Boolean);

  return parts.length > 0 ? parts.join(", ") : "nothing changed";
}

export function RunCycle() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch("/api/backend/cycles/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ narrate: false, persist: true, surface_insights: true }),
      });
      const body = await response.json();

      if (!response.ok) {
        // The existing feed stays on screen. Replacing a populated feed with an empty state
        // because a refresh failed is the "empty book vs dead backend" confusion again.
        setError(body.detail ?? `HTTP ${response.status}`);
        return;
      }

      setResult(summarise(body.insights ?? {}));
      router.refresh();
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={run}
        disabled={busy}
        aria-busy={busy}
        className="rounded-token border border-border-strong px-3 py-1.5 text-sm text-text-primary disabled:opacity-50"
      >
        {busy ? "Scanning…" : "Run scan"}
      </button>

      {busy ? (
        <span className="text-xs text-text-muted">
          Reading the market, your book and the strategies. This takes a minute.
        </span>
      ) : null}

      {result && !busy ? <span className="text-xs text-text-secondary">{result}</span> : null}

      {error ? (
        <span role="alert" className="text-xs text-stance-avoid">
          {error}
        </span>
      ) : null}
    </div>
  );
}
