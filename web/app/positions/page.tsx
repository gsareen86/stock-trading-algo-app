import { Empty, GrossNote, Unavailable } from "@/components/states";
import { fetchBookHealth, fetchPositions } from "@/lib/api";
import type { BookHealth, Position } from "@/lib/api";

/**
 * Positions — what is owned, across both books, and whether the book's shape is healthy.
 *
 * The health score here measures the **book's structure**: concentration, spread, deployment,
 * broken theses. It is not a score about the stocks in it, and it never ranks them.
 */

export const dynamic = "force-dynamic";

const BOOKS = ["swing", "longterm"] as const;

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function PositionTable({ positions }: { positions: Position[] }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="text-xs text-text-muted">
          <tr>
            <th className="pb-2 pr-3 font-normal">Ticker</th>
            <th className="pb-2 pr-3 font-normal">Qty</th>
            <th className="pb-2 pr-3 font-normal">Avg cost</th>
            <th className="pb-2 pr-3 font-normal">Last</th>
            <th className="pb-2 pr-3 font-normal">Cost basis</th>
            <th className="pb-2 pr-3 font-normal">Market value</th>
            <th className="pb-2 font-normal">Unrealised (gross)</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={position.ticker} className="border-t border-border-subtle">
              <td className="py-2 pr-3 font-medium text-text-primary">{position.ticker}</td>
              <td className="py-2 pr-3 font-mono">{position.quantity}</td>
              <td className="py-2 pr-3 font-mono">{money(position.average_cost)}</td>
              {/* Nullable rather than zero: "unknown" and "nothing" are different facts. */}
              <td className="py-2 pr-3 font-mono">{money(position.last_price)}</td>
              <td className="py-2 pr-3 font-mono">{money(position.cost_basis)}</td>
              <td className="py-2 pr-3 font-mono">{money(position.market_value)}</td>
              <td
                className={`py-2 font-mono ${
                  (position.unrealised_pnl_gross ?? 0) < 0
                    ? "text-stance-avoid"
                    : "text-stance-buy"
                }`}
              >
                {money(position.unrealised_pnl_gross)}
                {position.unrealised_pct !== null ? (
                  <span className="ml-1 text-xs text-text-muted">
                    ({position.unrealised_pct.toFixed(1)}%)
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HealthPanel({ health }: { health: BookHealth }) {
  const tone =
    health.band === "healthy"
      ? "text-stance-buy"
      : health.band === "watch"
        ? "text-stance-watch"
        : "text-stance-avoid";

  return (
    <div className="mt-4 rounded-token-lg border border-border-subtle bg-surface-raised p-4">
      <div className="flex items-baseline gap-3">
        <span className={`font-mono text-2xl ${tone}`}>{health.score}</span>
        <span className="text-xs uppercase tracking-wider text-text-muted">
          {health.band} · structure only
        </span>
      </div>

      {/* The headline never appears without its components. A single number invites optimising
          the number; four measurements with thresholds invite fixing the one that is low. */}
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {health.components.map((component) => (
          <div key={component.id} className="rounded-token bg-surface-sunken px-3 py-2">
            <div className="flex items-baseline justify-between">
              <span className="text-xs text-text-secondary">{component.label}</span>
              <span
                className={`font-mono text-sm ${
                  component.healthy ? "text-text-primary" : "text-stance-watch"
                }`}
              >
                {component.score}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-text-muted">
              {component.measurement}
              {component.unit} vs {component.threshold}
              {component.unit} — {component.detail}
            </p>
          </div>
        ))}
      </div>

      {health.guidance.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Next steps
          </h3>
          <ul className="mt-2 space-y-2">
            {health.guidance.map((step, index) => (
              <li key={index} className="text-sm text-text-secondary">
                <span className="font-mono text-xs text-accent">{step.action}</span>{" "}
                {step.ticker ? <strong className="text-text-primary">{step.ticker}</strong> : null}{" "}
                — {step.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

async function BookSection({ book }: { book: string }) {
  const [positions, health] = await Promise.all([fetchPositions(book), fetchBookHealth(book)]);

  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold capitalize text-text-primary">{book}</h2>

      {!positions.ok ? (
        <div className="mt-3">
          <Unavailable result={positions} />
        </div>
      ) : positions.data.count === 0 ? (
        <div className="mt-3">
          <Empty>No open positions in this book.</Empty>
        </div>
      ) : (
        <PositionTable positions={positions.data.positions} />
      )}

      {health.ok && positions.ok && positions.data.count > 0 ? (
        <HealthPanel health={health.data} />
      ) : null}
    </section>
  );
}

export default function Page() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Positions</h1>
      <p className="mt-1 text-sm text-text-secondary">What I own, across both books.</p>

      {BOOKS.map((book) => (
        <BookSection key={book} book={book} />
      ))}

      <GrossNote />
    </div>
  );
}
