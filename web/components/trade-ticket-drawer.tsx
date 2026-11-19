"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { Plan } from "@/lib/api";

export type TradeTicketProps = {
  open: boolean;
  onClose: () => void;
  symbol: string;
  companyName?: string | null;
  side?: "BUY" | "SELL";
  defaultBook?: "swing" | "longterm";
  defaultStrategyId?: string | null;
  plan?: Plan | null;
  lastPrice?: number | null;
  maxSellQuantity?: number | null;
  onSuccess?: () => void;
};

function money(val: number): string {
  return `₹${val.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function TradeTicketDrawer(props: TradeTicketProps) {
  if (!props.open) return null;
  const resetKey = `${props.symbol}-${props.side ?? "BUY"}-${props.defaultBook ?? "swing"}-${
    props.defaultStrategyId ?? ""
  }-${props.plan?.entry ?? ""}`;
  return <TradeTicketInner key={resetKey} {...props} />;
}

function TradeTicketInner({
  onClose,
  symbol,
  companyName,
  side: initialSide = "BUY",
  defaultBook = "swing",
  defaultStrategyId = null,
  plan = null,
  lastPrice = null,
  maxSellQuantity = null,
  onSuccess,
}: TradeTicketProps) {
  const router = useRouter();
  const [book, setBook] = useState<"swing" | "longterm">(defaultBook);
  const [side, setSide] = useState<"BUY" | "SELL">(initialSide);
  const [priceStr, setPriceStr] = useState(() => {
    const px =
      initialSide === "BUY"
        ? (plan?.entry ?? lastPrice ?? "")
        : (lastPrice ?? plan?.entry ?? "");
    return px ? String(px) : "";
  });
  const [qtyStr, setQtyStr] = useState(() =>
    initialSide === "SELL" && maxSellQuantity ? String(maxSellQuantity) : "",
  );
  const [strategyId, setStrategyId] = useState(defaultStrategyId ?? "");
  const [note, setNote] = useState("");
  const [capitalStr, setCapitalStr] = useState("1000000");
  const [riskPct, setRiskPct] = useState(1);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [doneMsg, setDoneMsg] = useState<string | null>(null);

  const price = Number.parseFloat(priceStr) || 0;
  const qty = Number.parseInt(qtyStr, 10) || 0;
  const capital = Number.parseFloat(capitalStr) || 0;
  const stopPx = plan?.stop ?? null;
  const perShareRisk =
    side === "BUY" && stopPx && price > stopPx ? price - stopPx : price * 0.06;
  const riskBudget = capital * (riskPct / 100);
  const suggestedQty =
    price > 0 && perShareRisk > 0 ? Math.max(1, Math.floor(riskBudget / perShareRisk)) : 0;
  const grossAmount = price * qty;

  async function confirmFill() {
    if (qty <= 0 || price <= 0) {
      setError("Quantity and price must both be positive.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/backend/books/${book}/fill`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: symbol.toUpperCase(),
          side,
          quantity: qty,
          price,
          strategy_id: strategyId.trim() || null,
          note: note.trim() || null,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(body.detail ?? `HTTP ${res.status}`);
        return;
      }
      setDoneMsg(
        `Recorded paper ${side} of ${qty} ${symbol.toUpperCase()} at ${money(price)} in ${book}.`,
      );
      setPreviewing(false);
      onSuccess?.();
      router.refresh();
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Paper trade ticket for ${symbol}`}
      className="fixed inset-0 z-50 flex justify-end bg-text-primary/30 backdrop-blur-xs"
      onClick={onClose}
    >
      <div
        className="drawer-surface flex h-full w-full max-w-md flex-col justify-between overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <div className="flex items-start justify-between gap-3 border-b border-border-subtle pb-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                Paper Execution Ledger · Preview Before Write
              </p>
              <h2 className="mt-1 text-xl font-semibold tracking-tight text-text-primary">
                {symbol.toUpperCase()}
              </h2>
              {companyName ? (
                <p className="text-xs text-text-secondary">{companyName}</p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-token border border-border-subtle px-2 py-1 text-xs text-text-muted hover:text-text-primary"
            >
              Close
            </button>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2">
            <div className="flex gap-1 rounded-token bg-surface-sunken p-1">
              {(["BUY", "SELL"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => {
                    setSide(s);
                    setPreviewing(false);
                  }}
                  className={`flex-1 rounded-token py-1.5 text-xs font-semibold transition-colors ${
                    side === s
                      ? s === "BUY"
                        ? "bg-stance-buy text-surface-raised"
                        : "bg-stance-avoid text-surface-raised"
                      : "text-text-secondary hover:text-text-primary"
                  }`}
                >
                  Paper {s}
                </button>
              ))}
            </div>

            <div className="flex gap-1 rounded-token bg-surface-sunken p-1">
              {(["swing", "longterm"] as const).map((b) => (
                <button
                  key={b}
                  type="button"
                  onClick={() => setBook(b)}
                  className={`flex-1 rounded-token py-1.5 text-xs font-medium capitalize transition-colors ${
                    book === b
                      ? "bg-surface-raised text-text-primary shadow-xs"
                      : "text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {b === "longterm" ? "Long-Term" : "Swing"}
                </button>
              ))}
            </div>
          </div>

          {plan ? (
            <div className="mt-4 rounded-token-lg border border-border-subtle bg-surface-sunken p-3">
              <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-text-muted">
                <span>Derived Plan Reference</span>
                {plan.risk_reward ? (
                  <span className="tabular-nums font-mono font-semibold text-text-primary">
                    {plan.risk_reward}:1 R:R
                  </span>
                ) : null}
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                <div>
                  <span className="text-text-muted">Entry</span>
                  <p className="tabular-nums font-mono font-medium text-text-primary">
                    {money(plan.entry)}
                  </p>
                </div>
                <div>
                  <span className="text-text-muted">Stop</span>
                  <p className="tabular-nums font-mono font-medium text-stance-avoid">
                    {money(plan.stop)}
                  </p>
                </div>
                <div>
                  <span className="text-text-muted">Target</span>
                  <p className="tabular-nums font-mono font-medium text-stance-buy">
                    {money(plan.target)}
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          {side === "BUY" ? (
            <div className="mt-4 rounded-token-lg border border-border-subtle bg-surface-sunken p-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Risk Sizing Calculator
                </span>
                {suggestedQty > 0 ? (
                  <button
                    type="button"
                    onClick={() => setQtyStr(String(suggestedQty))}
                    className="text-xs font-medium text-accent hover:underline"
                  >
                    Use {suggestedQty} shares →
                  </button>
                ) : null}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <label className="text-[11px] text-text-muted">
                  Book Capital (₹)
                  <input
                    type="number"
                    value={capitalStr}
                    onChange={(e) => setCapitalStr(e.target.value)}
                    className="tabular-nums mt-1 w-full rounded-token border border-border-subtle bg-surface-raised px-2 py-1 font-mono text-xs text-text-primary"
                  />
                </label>
                <div>
                  <span className="block text-[11px] text-text-muted">Risk / Trade</span>
                  <div className="mt-1 flex gap-1">
                    {[0.5, 1, 2].map((pct) => (
                      <button
                        key={pct}
                        type="button"
                        onClick={() => setRiskPct(pct)}
                        className={`flex-1 rounded-token border px-2 py-1 font-mono text-xs ${
                          riskPct === pct
                            ? "border-accent bg-accent-soft font-semibold text-accent"
                            : "border-border-subtle bg-surface-raised text-text-secondary"
                        }`}
                      >
                        {pct}%
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              {suggestedQty > 0 ? (
                <p className="mt-2 text-[11px] text-text-muted">
                  Risking {money(riskBudget)} across{" "}
                  <span className="tabular-nums font-mono">{money(perShareRisk)}</span>/sh
                  {stopPx ? " (to plan stop)" : " (6% default)"} suggests{" "}
                  <strong className="tabular-nums font-mono text-text-primary">
                    {suggestedQty}
                  </strong>{" "}
                  shares ({money(suggestedQty * price)} outlay).
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs text-text-secondary">
                Quantity
                <input
                  type="number"
                  min={1}
                  value={qtyStr}
                  onChange={(e) => {
                    setQtyStr(e.target.value);
                    setPreviewing(false);
                  }}
                  placeholder={suggestedQty ? String(suggestedQty) : "50"}
                  className="tabular-nums mt-1 w-full rounded-token border border-border-subtle bg-surface-sunken px-3 py-2 font-mono text-sm text-text-primary"
                />
              </label>

              <label className="text-xs text-text-secondary">
                Fill Price (₹)
                <input
                  type="number"
                  step="0.05"
                  min={0.05}
                  value={priceStr}
                  onChange={(e) => {
                    setPriceStr(e.target.value);
                    setPreviewing(false);
                  }}
                  placeholder="1420.00"
                  className="tabular-nums mt-1 w-full rounded-token border border-border-subtle bg-surface-sunken px-3 py-2 font-mono text-sm text-text-primary"
                />
              </label>
            </div>

            <label className="block text-xs text-text-secondary">
              Strategy Attribution
              <select
                value={strategyId}
                onChange={(e) => setStrategyId(e.target.value)}
                className="mt-1 w-full rounded-token border border-border-subtle bg-surface-sunken px-3 py-2 text-sm text-text-primary"
              >
                <option value="">Manual / discretionary</option>
                <option value="minervini">minervini</option>
                <option value="young_momentum">young_momentum</option>
                <option value="brahma_vishnu_mahesh">brahma_vishnu_mahesh</option>
                <option value="fun_tech_momentum">fun_tech_momentum</option>
              </select>
            </label>

            <label className="block text-xs text-text-secondary">
              Entry / Exit Thesis Note
              <textarea
                rows={2}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="VCP pivot breakout on 2.3x volume; stop below base low."
                className="mt-1 w-full rounded-token border border-border-subtle bg-surface-sunken px-3 py-2 text-sm text-text-primary"
              />
            </label>
          </div>

          {previewing ? (
            <div className="mt-4 rounded-token-lg border border-accent bg-accent-soft p-3.5">
              <p className="text-xs font-semibold text-accent">
                Preview Paper Fill — Verify Before Recording
              </p>
              <dl className="mt-2 grid grid-cols-2 gap-y-1 text-xs">
                <dt className="text-text-secondary">Book / Side</dt>
                <dd className="text-right font-mono font-semibold text-text-primary">
                  {book} · {side}
                </dd>
                <dt className="text-text-secondary">Order</dt>
                <dd className="tabular-nums text-right font-mono text-text-primary">
                  {qty} × {money(price)}
                </dd>
                <dt className="text-text-secondary">Gross Amount</dt>
                <dd className="tabular-nums text-right font-mono font-semibold text-text-primary">
                  {money(grossAmount)}
                </dd>
              </dl>
              <p className="mt-2 text-[11px] text-text-muted">
                Paper ledger only — no broker order is placed and figures are gross of charges.
              </p>
            </div>
          ) : null}

          {error ? (
            <p role="alert" className="mt-3 text-xs font-medium text-stance-avoid">
              {error}
            </p>
          ) : null}

          {doneMsg ? (
            <div className="mt-3 rounded-token-lg border border-stance-buy bg-stance-buy-soft p-3 text-xs font-medium text-stance-buy">
              {doneMsg}
            </div>
          ) : null}
        </div>

        <div className="mt-6 flex gap-2 border-t border-border-subtle pt-4">
          {!previewing ? (
            <button
              type="button"
              disabled={qty <= 0 || price <= 0}
              onClick={() => {
                setError(null);
                setPreviewing(true);
              }}
              className="flex-1 rounded-token bg-accent px-4 py-2 text-sm font-medium text-surface-raised transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              Preview Fill ({grossAmount > 0 ? money(grossAmount) : "enter size"})
            </button>
          ) : (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={confirmFill}
                className="flex-1 rounded-token bg-stance-buy px-4 py-2 text-sm font-semibold text-surface-raised disabled:opacity-50"
              >
                {busy ? "Recording…" : `Confirm Paper ${side}`}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setPreviewing(false)}
                className="rounded-token border border-border-strong px-3 py-2 text-sm text-text-secondary"
              >
                Edit
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
