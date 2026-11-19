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
      <p className="text-sm font-semibold text-text-primary">
        {signedOut ? "Not signed in" : "Could not reach the backend"}
      </p>
      <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
        {signedOut ? (
          <>
            This session has expired.{" "}
            <a
              href="/login"
              className="font-medium text-accent underline underline-offset-2"
            >
              Sign in again
            </a>
            .
          </>
        ) : (
          <>
            {result.error} — tried{" "}
            <code className="rounded-token bg-surface-raised px-1.5 py-0.5 font-mono text-xs">
              {result.attemptedUrl}
            </code>
            . This is a broken seam, not an empty result: nothing is being hidden.
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
    <p className="mt-4 text-xs text-text-muted">
      All P&amp;L figures are gross — no brokerage, STT, stamp duty or GST is modelled.
    </p>
  );
}

export function PageSkeleton({ cards = 4 }: { cards?: number }) {
  return (
    <div className="mx-auto max-w-6xl animate-pulse space-y-6 px-6 py-10">
      <div className="hero-surface p-6">
        <div className="h-3 w-28 rounded-token bg-surface-sunken" />
        <div className="mt-3 h-7 w-64 rounded-token bg-surface-sunken" />
        <div className="mt-2 h-4 w-96 max-w-full rounded-token bg-surface-sunken" />
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((idx) => (
            <div key={idx} className="h-20 rounded-token-lg bg-surface-sunken" />
          ))}
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: cards }).map((_, idx) => (
          <div key={idx} className="h-44 rounded-token-lg bg-surface-raised border border-border-subtle p-5">
            <div className="h-4 w-36 rounded-token bg-surface-sunken" />
            <div className="mt-3 h-3 w-full rounded-token bg-surface-sunken" />
            <div className="mt-2 h-3 w-2/3 rounded-token bg-surface-sunken" />
          </div>
        ))}
      </div>
    </div>
  );
}
