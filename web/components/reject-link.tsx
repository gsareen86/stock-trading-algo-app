"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Rejecting a chain link.
 *
 * The control that makes a model-proposed link acceptable to display at all. A tier arrives
 * with reasoning a reader can judge; this is how they act on judging it wrong.
 *
 * The rejection persists across later runs. Without that, every run re-proposes the same wrong
 * link, the reader re-rejects it forever, and the surface becomes one they stop reading —
 * which is the failure this whole affordance exists to prevent.
 */

export function RejectLink({ linkId, label }: { linkId: number; label: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reject() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/backend/themes/links/${linkId}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason.trim() || null }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        setError(body.detail ?? `HTTP ${response.status}`);
        return;
      }
      setConfirming(false);
      router.refresh();
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="rounded-token border border-border-strong px-2.5 py-1 text-xs text-text-secondary"
      >
        This link is wrong
      </button>
    );
  }

  return (
    <div className="rounded-token bg-surface-sunken px-3 py-2">
      <p className="text-xs text-text-secondary">
        Reject <span className="font-medium">{label}</span>? It will stop contributing
        candidates and will not be re-proposed by a later run.
      </p>
      <input
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Why (optional)"
        aria-label="Reason for rejecting this link"
        className="mt-2 w-full rounded-token border border-border-subtle bg-surface-raised px-2 py-1 text-xs text-text-primary"
      />
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={reject}
          className="rounded-token bg-text-primary px-2.5 py-1 text-xs font-medium text-surface-sunken disabled:opacity-50"
        >
          {busy ? "Rejecting…" : "Reject"}
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="rounded-token border border-border-subtle px-2.5 py-1 text-xs text-text-secondary"
        >
          Cancel
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-xs text-stance-avoid">
          {error}
        </p>
      ) : null}
    </div>
  );
}
