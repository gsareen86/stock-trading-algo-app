"use client";

import Link from "next/link";
import { useState } from "react";

import { Empty, GrossNote, Unavailable } from "@/components/states";
import { TradeTicketDrawer } from "@/components/trade-ticket-drawer";
import type { BookHealth, Fetched, Position } from "@/lib/api";

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function bandTone(band: string): string {
  if (band === "healthy") return "border-stance-buy bg-stance-buy-soft text-stance-buy";
  if (band === "watch") return "border-stance-watch bg-stance-watch-soft text-stance-watch";
  return "border-stance-avoid bg-stance-avoid-soft text-stance-avoid";
}

export type BookBundle = {
  book: "swing" | "longterm";
  label: string;
  positions: Fetched<{ positions: Position[]; count: number }>;
  health: Fetched<BookHealth>;
};

export function PositionsBoard({ books }: { books: BookBundle[] }) {
  const [activeBook, setActiveBook] = useState<"swing" | "longterm">("swing");
  const [ticket, setTicket] = useState<{
    open: boolean;
    book: "swing" | "longterm";
    symbol: string;
    lastPrice: number | null;
    maxQty: number;
  }>({ open: false, book: "swing", symbol: "", lastPrice: null, maxQty: 0 });

  const current = books.find((b) => b.book === activeBook) ?? books[0];

  return (
    <div className="space-y-6">
      {/* Hero Portfolio Comparison Strip */}
      <section className="hero-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Paper Portfolio &amp; Structural Health
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text-primary">
              Positions
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Open holdings across Swing and Long-Term paper books, paired with deterministic structural health checks.
            </p>
          </div>

          <div className="flex gap-1 rounded-token bg-surface-sunken p-1 text-xs">
            {books.map((b) => (
              <button
                key={b.book}
                type="button"
                onClick={() => setActiveBook(b.book)}
                className={`rounded-token px-3 py-1.5 font-semibold transition-colors ${
                  activeBook === b.book
                    ? "bg-surface-raised text-text-primary shadow-xs"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                {b.label} ({b.positions.ok ? b.positions.data.count : "—"})
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          {books.map((b) => {
            const list = b.positions.ok ? b.positions.data.positions : [];
            const deployed = list.reduce((sum, p) => sum + p.cost_basis, 0);
            const hasAllPrices = list.every((p) => p.unrealised_pnl_gross !== null);
            const unrealised =
              list.length > 0 && hasAllPrices
                ? list.reduce((sum, p) => sum + (p.unrealised_pnl_gross ?? 0), 0)
                : null;
            const health = b.health.ok ? b.health.data : null;

            return (
              <button
                key={b.book}
                type="button"
                onClick={() => setActiveBook(b.book)}
                className={`rounded-token-lg border p-4 text-left transition-all ${
                  activeBook === b.book
                    ? "border-accent bg-surface-raised ring-2 ring-accent/20"
                    : "border-border-subtle bg-surface-raised/80 hover:border-border-strong"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-text-primary">{b.label} Book</span>
                  {health ? (
                    <span
                      className={`rounded-token border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${bandTone(
                        health.band,
                      )}`}
                    >
                      Health {health.score} · {health.band}
                    </span>
                  ) : null}
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <span className="block text-[11px] text-text-muted">Open</span>
                    <span className="tabular-nums font-mono text-base font-semibold text-text-primary">
                      {b.positions.ok ? b.positions.data.count : "—"}
                    </span>
                  </div>
                  <div>
                    <span className="block text-[11px] text-text-muted">Cost Basis</span>
                    <span className="tabular-nums font-mono text-base font-semibold text-text-primary">
                      {money(deployed)}
                    </span>
                  </div>
                  <div>
                    <span className="block text-[11px] text-text-muted">Unrealised (Gross)</span>
                    <span
                      className={`tabular-nums font-mono text-base font-semibold ${
                        (unrealised ?? 0) < 0 ? "text-stance-avoid" : "text-stance-buy"
                      }`}
                    >
                      {unrealised === null && list.length > 0 ? "partial" : money(unrealised ?? 0)}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Active Book Holdings Table */}
      <section className="card-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            {current.label} Open Positions
          </h2>
          <span className="text-xs text-text-muted">Gross of charges</span>
        </div>

        {!current.positions.ok ? (
          <div className="mt-4">
            <Unavailable result={current.positions} />
          </div>
        ) : current.positions.data.count === 0 ? (
          <div className="mt-4">
            <Empty>
              No open positions in the {current.label} book. Promote a setup from{" "}
              <Link href="/ideas" className="text-accent underline">
                Ideas
              </Link>{" "}
              or{" "}
              <Link href="/watchlist" className="text-accent underline">
                Watchlist
              </Link>
              .
            </Empty>
          </div>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="pb-2 pr-3 font-medium">Ticker</th>
                  <th className="pb-2 pr-3 font-medium">Qty</th>
                  <th className="pb-2 pr-3 font-medium">Avg Cost</th>
                  <th className="pb-2 pr-3 font-medium">Last</th>
                  <th className="pb-2 pr-3 font-medium">Cost Basis</th>
                  <th className="pb-2 pr-3 font-medium">Market Value</th>
                  <th className="pb-2 pr-3 font-medium">Unrealised (Gross)</th>
                  <th className="pb-2 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {current.positions.data.positions.map((pos) => (
                  <tr key={pos.ticker} className="border-t border-border-subtle">
                    <td className="py-2.5 pr-3">
                      <Link
                        href={`/stock?symbol=${encodeURIComponent(pos.ticker)}`}
                        className="font-mono font-semibold text-accent hover:underline"
                      >
                        {pos.ticker}
                      </Link>
                    </td>
                    <td className="tabular-nums py-2.5 pr-3 font-mono">{pos.quantity}</td>
                    <td className="tabular-nums py-2.5 pr-3 font-mono">{money(pos.average_cost)}</td>
                    <td className="tabular-nums py-2.5 pr-3 font-mono">{money(pos.last_price)}</td>
                    <td className="tabular-nums py-2.5 pr-3 font-mono">{money(pos.cost_basis)}</td>
                    <td className="tabular-nums py-2.5 pr-3 font-mono">{money(pos.market_value)}</td>
                    <td
                      className={`tabular-nums py-2.5 pr-3 font-mono font-medium ${
                        (pos.unrealised_pnl_gross ?? 0) < 0
                          ? "text-stance-avoid"
                          : "text-stance-buy"
                      }`}
                    >
                      {money(pos.unrealised_pnl_gross)}
                      {pos.unrealised_pct !== null ? (
                        <span className="ml-1 text-xs text-text-muted">
                          ({pos.unrealised_pct.toFixed(1)}%)
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() =>
                          setTicket({
                            open: true,
                            book: current.book,
                            symbol: pos.ticker,
                            lastPrice: pos.last_price,
                            maxQty: pos.quantity,
                          })
                        }
                        className="rounded-token border border-border-strong px-2.5 py-1 text-xs font-medium text-text-primary hover:bg-surface-sunken"
                      >
                        Preview Exit / Trim
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* 4-Component Structural Health Card */}
      {current.health.ok && current.positions.ok && current.positions.data.count > 0 ? (
        <section className="card-surface p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Book Structural Health ({current.label})
              </h2>
              <p className="mt-0.5 text-xs text-text-secondary">
                Measures portfolio shape (concentration, spread, deployment, broken theses) — never stock quality.
              </p>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="tabular-nums font-mono text-2xl font-bold text-text-primary">
                {current.health.data.score}
              </span>
              <span
                className={`rounded-token border px-2 py-0.5 text-[11px] font-semibold uppercase ${bandTone(
                  current.health.data.band,
                )}`}
              >
                {current.health.data.band}
              </span>
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {current.health.data.components.map((c) => (
              <div key={c.id} className="rounded-token bg-surface-sunken p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-text-secondary">{c.label}</span>
                  <span
                    className={`tabular-nums font-mono text-sm font-bold ${
                      c.healthy ? "text-stance-buy" : "text-stance-watch"
                    }`}
                  >
                    {c.score}
                  </span>
                </div>
                <p className="tabular-nums mt-1 font-mono text-[11px] text-text-primary">
                  {c.measurement}
                  {c.unit} vs {c.threshold}
                  {c.unit}
                </p>
                <p className="mt-0.5 text-[11px] text-text-muted">{c.detail}</p>
              </div>
            ))}
          </div>

          {current.health.data.guidance.length > 0 ? (
            <div className="mt-4 border-t border-border-subtle pt-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                Recommended Structural Actions
              </h3>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                {current.health.data.guidance.map((step, i) => (
                  <div key={i} className="rounded-token bg-surface-sunken px-3 py-2 text-xs">
                    <span className="font-mono font-semibold text-accent">{step.action}</span>
                    {step.ticker ? (
                      <Link
                        href={`/stock?symbol=${encodeURIComponent(step.ticker)}`}
                        className="ml-1.5 font-mono font-bold text-text-primary underline"
                      >
                        {step.ticker}
                      </Link>
                    ) : null}
                    <p className="mt-0.5 text-text-secondary">{step.detail}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      <GrossNote />

      <TradeTicketDrawer
        open={ticket.open}
        onClose={() => setTicket((prev) => ({ ...prev, open: false }))}
        symbol={ticket.symbol}
        side="SELL"
        defaultBook={ticket.book}
        lastPrice={ticket.lastPrice}
        maxSellQuantity={ticket.maxQty}
      />
    </div>
  );
}
