"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { Insight } from "@/lib/api";

/**
 * Acting on an insight.
 *
 * The whole client-side interactivity budget of this app is here and in the login form. Every
 * action previews first: the backend re-derives quantity from the ledger, so what the preview
 * shows is what will happen — the same function with a flag, not a separate estimator.
 */

const LABEL: Record<string, string> = {
  exit: "Exit position",
  trim: "Trim to target",
  buy: "Buy proposed size",
  review: "Mark reviewed",
};

export function InsightActions({ insight }: { insight: Insight }) {
  const router = useRouter();
  const [plan, setPlan] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function call(action: string, preview: boolean) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/backend/insights/${insight.id}/act`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, book: "swing", preview }),
      });
      const body = await response.json();

      if (!response.ok) {
        // A stale insight is a 409 — an ordinary outcome, worth reading rather than a failure.
        setError(body.detail ?? `HTTP ${response.status}`);
        setPlan(null);
        return;
      }

      if (preview) {
        setPlan(body.plan.description);
        setPending(action);
      } else {
        setPlan(null);
        setPending(null);
        router.refresh();
      }
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3">
      <div className="flex flex-wrap gap-2">
        {insight.actions.map((action) => (
          <button
            key={action}
            type="button"
            disabled={busy}
            onClick={() => call(action, action !== "review")}
            className="rounded-token border border-border-strong px-2.5 py-1 text-xs text-text-primary disabled:opacity-50"
          >
            {LABEL[action] ?? action}
          </button>
        ))}
      </div>

      {plan && pending ? (
        <div className="mt-2 rounded-token bg-surface-sunken px-3 py-2">
          <p className="text-xs text-text-secondary">{plan}</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => call(pending, false)}
              className="rounded-token bg-text-primary px-2.5 py-1 text-xs font-medium text-surface-sunken disabled:opacity-50"
            >
              Confirm
            </button>
            <button
              type="button"
              onClick={() => {
                setPlan(null);
                setPending(null);
              }}
              className="rounded-token border border-border-subtle px-2.5 py-1 text-xs text-text-secondary"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2 text-xs text-stance-avoid">
          {error}
        </p>
      ) : null}
    </div>
  );
}
