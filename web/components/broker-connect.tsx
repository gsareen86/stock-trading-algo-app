"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { BrokerStatus } from "@/lib/api";

/**
 * Connect, and see whether it worked.
 *
 * The link is minted when the button is clicked and opened immediately, because these expire
 * in minutes. Anything that stores one — a bookmark, a message, a page rendered ten minutes
 * ago — hands the user a dead link and the error reads as a broken integration.
 */
export function BrokerConnect({ initial }: { initial: BrokerStatus }) {
  const router = useRouter();
  const [status, setStatus] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [awaiting, setAwaiting] = useState(false);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/backend/broker/connect", { method: "POST" });
      const body = await response.json();
      if (!response.ok) {
        setError(body.detail ?? `HTTP ${response.status}`);
        return;
      }
      // Opened at once, in a new tab, so the link is used within seconds of being issued.
      window.open(body.login_url, "_blank", "noopener");
      setStatus(body.status);
      setAwaiting(true);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function check() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/backend/broker/holdings");
      if (response.ok) {
        setAwaiting(false);
        router.refresh();
      } else {
        const body = await response.json();
        setError(body.detail ?? "Still not authorised.");
      }
      const fresh = await fetch("/api/backend/broker/status");
      if (fresh.ok) setStatus(await fresh.json());
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const connected = status.authorised;

  return (
    <section className="mt-8 rounded-token-lg border border-border-subtle bg-surface-raised p-5">
      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            connected ? "bg-status-ok" : "bg-status-degraded"
          }`}
          aria-hidden
        />
        <p className="text-sm font-medium text-text-primary">
          {connected ? "Connected to Zerodha" : "Not connected"}
        </p>
      </div>

      {connected && status.last_ok_at ? (
        <p className="mt-1 text-xs text-text-muted">
          Last read {new Date(status.last_ok_at).toLocaleString("en-IN")} · refreshed every{" "}
          {status.refresh_minutes} minutes
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={connect}
          disabled={busy}
          className="rounded-token bg-text-primary px-3 py-1.5 text-sm font-medium text-surface-sunken disabled:opacity-50"
        >
          {busy ? "Working…" : connected ? "Sign in again" : "Connect Zerodha"}
        </button>

        {awaiting ? (
          <button
            type="button"
            onClick={check}
            disabled={busy}
            className="rounded-token border border-border-strong px-3 py-1.5 text-sm text-text-primary disabled:opacity-50"
          >
            I&apos;ve signed in — check
          </button>
        ) : null}
      </div>

      {awaiting ? (
        <p className="mt-3 text-sm text-text-secondary">
          A Zerodha login has opened in a new tab. Sign in there, come back, and press{" "}
          <strong className="text-text-primary">check</strong>.
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="mt-3 text-sm text-stance-avoid">
          {error}
        </p>
      ) : null}
    </section>
  );
}
