import type { Fetched } from "@/lib/api";

/**
 * How a surface renders something other than data.
 *
 * An empty book and an unreachable backend look identical on a naive screen, and confusing
 * them on a trading platform is how someone concludes they hold nothing. So they read
 * differently by construction.
 */

export function Unavailable({ result }: { result: Extract<Fetched<unknown>, { ok: false }> }) {
  const signedOut = result.error === "not signed in";
  return (
    <div className="rounded-token-lg border border-dashed border-border-strong bg-surface-sunken px-6 py-8 text-center">
      <p className="text-sm font-medium text-text-primary">
        {signedOut ? "Not signed in" : "Could not reach the backend"}
      </p>
      <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
        {signedOut ? (
          <>
            This session has expired.{" "}
            <a href="/login" className="text-accent underline">
              Sign in again
            </a>
            .
          </>
        ) : (
          <>
            {result.error} — tried{" "}
            <code className="font-mono text-xs">{result.attemptedUrl}</code>. This is a broken
            seam, not an empty result: nothing is being hidden.
          </>
        )}
      </p>
    </div>
  );
}

/** Genuinely empty — and saying so, rather than rendering a zeroed row that looks real. */
export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-token-lg border border-border-subtle bg-surface-sunken px-6 py-8 text-center">
      <p className="text-sm text-text-secondary">{children}</p>
    </div>
  );
}

export function GrossNote() {
  return (
    <p className="mt-3 text-xs text-text-muted">
      All P&amp;L figures are gross — no brokerage, STT, stamp duty or GST is modelled.
    </p>
  );
}
