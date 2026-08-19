import { BrokerConnect } from "@/components/broker-connect";
import { Unavailable } from "@/components/states";
import { fetchBrokerStatus } from "@/lib/api";

/**
 * Connecting Zerodha.
 *
 * The login link is **generated on demand and expires quickly** — a link that sat in a chat
 * window for an hour returns "invalid authorize session", which reads as a broken integration
 * rather than a stale link. So the button mints one at the moment it is clicked and opens it
 * straight away, which removes the staleness entirely.
 *
 * Read-only. This screen cannot place an order and the platform stays paper-only; connecting
 * lets the strategies be asked what they think of what you actually hold.
 */

export const dynamic = "force-dynamic";

export default async function Page() {
  const status = await fetchBrokerStatus();

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Zerodha</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Read your real holdings, so the strategies can be asked what they think of them.
      </p>

      {!status.ok ? (
        <div className="mt-8">
          <Unavailable result={status} />
        </div>
      ) : (
        <BrokerConnect initial={status.data} />
      )}

      <div className="mt-10 space-y-3 text-sm text-text-secondary">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          What to expect
        </h2>
        <p>
          <strong className="text-text-primary">Nothing is ever bought or sold.</strong> This
          connection can only read. Your holdings are shown alongside the paper books and are
          never mixed into them.
        </p>
        <p>
          <strong className="text-text-primary">You sign in each day.</strong> Zerodha expires
          sessions daily — that is an exchange requirement, not something this app can avoid.
        </p>
        <p>
          <strong className="text-text-primary">The link is short-lived.</strong> Generate it
          and use it straight away; one left sitting for an hour will say &ldquo;invalid
          authorize session&rdquo;.
        </p>
      </div>
    </div>
  );
}
