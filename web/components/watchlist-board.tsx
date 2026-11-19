"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Empty } from "@/components/states";
import { TradeTicketDrawer } from "@/components/trade-ticket-drawer";
import type { Plan, UniverseSymbol, WatchlistItem } from "@/lib/api";

type WatchFilter = "all" | "swing" | "longterm" | "near_pivot" | "flipped";

const STANCE_PILL: Record<string, string> = {
  BUY: "border-stance-buy bg-stance-buy-soft text-stance-buy",
  WATCH: "border-stance-watch bg-stance-watch-soft text-stance-watch",
  AVOID: "border-stance-avoid bg-stance-avoid-soft text-stance-avoid",
};

function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function WatchlistBoard({ initialItems }: { initialItems: WatchlistItem[] }) {
  const router = useRouter();
  const [items, setItems] = useState<WatchlistItem[]>(initialItems);
  const [filter, setFilter] = useState<WatchFilter>("all");

  // Quick-add state
  const [universe, setUniverse] = useState<UniverseSymbol[]>([]);
  const [addSymbol, setAddSymbol] = useState("");
  const [addBook, setAddBook] = useState<"swing" | "longterm">("swing");
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Inline note editing state
  const [editingNoteSymbol, setEditingNoteSymbol] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [savingNote, setSavingNote] = useState(false);

  // Ticket drawer state
  const [ticket, setTicket] = useState<{
    open: boolean;
    symbol: string;
    name: string | null;
    book: "swing" | "longterm";
    strategyId: string | null;
    plan: Plan | null;
    lastPrice: number | null;
  }>({
    open: false,
    symbol: "",
    name: null,
    book: "swing",
    strategyId: null,
    plan: null,
    lastPrice: null,
  });

  useEffect(() => {
    fetch("/api/backend/universe/symbols?limit=750")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && Array.isArray(d.symbols)) setUniverse(d.symbols);
      })
      .catch(() => {});
  }, []);

  const suggestions = useMemo(() => {
    const q = addSymbol.trim().toUpperCase();
    if (!q || q.length < 1) return [];
    return universe
      .filter((u) => u.symbol.includes(q) || (u.name ?? "").toUpperCase().includes(q))
      .slice(0, 6);
  }, [addSymbol, universe]);

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (filter === "swing") return item.book_intent === "swing";
      if (filter === "longterm") return item.book_intent === "longterm";
      if (filter === "flipped") return item.flipped_buy;
      if (filter === "near_pivot") {
        return (
          item.distance_to_entry_pct !== null &&
          Math.abs(item.distance_to_entry_pct) <= 3
        );
      }
      return true;
    });
  }, [items, filter]);

  async function handleAdd(symInput?: string) {
    const sym = (symInput ?? addSymbol).trim().toUpperCase();
    if (!sym) return;
    setAddBusy(true);
    setAddError(null);
    try {
      const res = await fetch("/api/backend/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym, book_intent: addBook }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setAddError(body.detail ?? `HTTP ${res.status}`);
        return;
      }
      setAddSymbol("");
      router.refresh();
    } catch {
      setAddError("Could not reach server.");
    } finally {
      setAddBusy(false);
    }
  }

  async function handleSaveNote(symbol: string) {
    setSavingNote(true);
    try {
      const res = await fetch(`/api/backend/watchlist/${encodeURIComponent(symbol)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: noteDraft }),
      });
      if (res.ok) {
        setItems((prev) =>
          prev.map((it) => (it.symbol === symbol ? { ...it, notes: noteDraft } : it)),
        );
        setEditingNoteSymbol(null);
        router.refresh();
      }
    } finally {
      setSavingNote(false);
    }
  }

  async function handleRemove(symbol: string) {
    const res = await fetch(`/api/backend/watchlist/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    });
    if (res.ok) {
      setItems((prev) => prev.filter((it) => it.symbol !== symbol));
      router.refresh();
    }
  }

  return (
    <div className="space-y-6">
      {/* Hero Header & Quick-Add Bar */}
      <section className="hero-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Setup Trigger &amp; Catalyst Tracker
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text-primary">
              Watchlist
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Track high-conviction setups approaching entry pivots, detect WATCH → BUY strategy flips automatically after each scan, and promote names straight to paper books.
            </p>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-4">
          <div className="flex flex-wrap gap-1.5">
            {(
              [
                { id: "all", label: `All (${items.length})` },
                { id: "flipped", label: "Flipped BUY" },
                { id: "near_pivot", label: "Near Pivot ≤ 3%" },
                { id: "swing", label: "Swing Intent" },
                { id: "longterm", label: "Long-Term Intent" },
              ] as const
            ).map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilter(f.id)}
                className={`rounded-token border px-2.5 py-1 text-xs font-medium ${
                  filter === f.id
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border-subtle bg-surface-raised text-text-secondary hover:text-text-primary"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          <div className="relative flex flex-wrap items-center gap-2">
            <div className="relative">
              <input
                value={addSymbol}
                onChange={(e) => setAddSymbol(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAdd();
                  }
                }}
                placeholder="Add NSE ticker…"
                aria-label="Add NSE symbol to watchlist"
                className="w-44 rounded-token border border-border-strong bg-surface-raised px-3 py-1.5 font-mono text-xs text-text-primary outline-none focus:border-accent"
              />
              {suggestions.length > 0 && addSymbol.trim().length > 0 ? (
                <div className="absolute left-0 top-9 z-30 w-64 overflow-hidden rounded-token-lg border border-border-strong bg-surface-elevated shadow-lg">
                  {suggestions.map((s) => (
                    <button
                      key={s.symbol}
                      type="button"
                      onClick={() => handleAdd(s.symbol)}
                      className="flex w-full items-center justify-between border-b border-border-subtle px-3 py-1.5 text-left text-xs last:border-b-0 hover:bg-surface-sunken"
                    >
                      <span className="font-mono font-semibold text-text-primary">{s.symbol}</span>
                      <span className="truncate pl-2 text-text-muted">{s.name}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            <select
              aria-label="Book intent"
              value={addBook}
              onChange={(e) => setAddBook(e.target.value as "swing" | "longterm")}
              className="rounded-token border border-border-subtle bg-surface-raised px-2 py-1.5 text-xs text-text-primary"
            >
              <option value="swing">Swing</option>
              <option value="longterm">Long-Term</option>
            </select>

            <button
              type="button"
              disabled={addBusy || !addSymbol.trim()}
              onClick={() => handleAdd()}
              className="rounded-token bg-accent px-3 py-1.5 text-xs font-semibold text-surface-raised disabled:opacity-40"
            >
              {addBusy ? "Adding…" : "+ Add"}
            </button>
          </div>
        </div>
        {addError ? (
          <p role="alert" className="mt-2 text-xs text-stance-avoid">
            {addError}
          </p>
        ) : null}
      </section>

      {filtered.length === 0 ? (
        <Empty>
          {items.length === 0
            ? "Your watchlist is empty. Add an NSE symbol above or click + Watchlist on Ideas or Stock."
            : "No watched setups match this filter."}
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {filtered.map((item) => {
            const plan = item.plan;
            const last = item.last_price;
            // Normalize current price position along [stop -> entry] for proximity visual
            let fillRatio = 50;
            if (plan && last && plan.entry > plan.stop) {
              fillRatio = Math.max(
                4,
                Math.min(100, Math.round(((last - plan.stop) / (plan.entry - plan.stop)) * 100)),
              );
            }

            return (
              <article key={item.symbol} className="card-surface flex flex-col justify-between p-5">
                <div>
                  <header className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Link
                          href={`/stock?symbol=${encodeURIComponent(item.symbol)}`}
                          className="font-mono text-base font-bold text-text-primary hover:text-accent"
                        >
                          {item.symbol}
                        </Link>
                        <span className="rounded-token bg-surface-sunken px-2 py-0.5 text-[11px] capitalize text-text-secondary">
                          {item.book_intent === "longterm" ? "Long-Term" : "Swing"}
                        </span>
                        {item.flipped_buy ? (
                          <span className="rounded-token border border-stance-buy bg-stance-buy-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-stance-buy">
                            WATCH → BUY ({item.flipped_strategies.join(", ")})
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-0.5 text-xs text-text-muted">
                        {item.name ?? item.symbol}
                        {item.sector ? ` · ${item.sector}` : ""}
                      </p>
                    </div>

                    <div className="text-right">
                      <p className="tabular-nums font-mono text-sm font-semibold text-text-primary">
                        {money(last)}
                      </p>
                      {item.distance_to_entry_pct !== null ? (
                        <p className="tabular-nums font-mono text-[11px] text-text-secondary">
                          {item.distance_to_entry_pct > 0
                            ? `${item.distance_to_entry_pct}% to entry`
                            : "At / above pivot"}
                        </p>
                      ) : null}
                    </div>
                  </header>

                  {/* Visual Stop -> Current -> Entry Proximity Bar */}
                  {plan ? (
                    <div className="mt-3 rounded-token bg-surface-sunken p-3">
                      <div className="flex items-center justify-between text-[11px] text-text-muted">
                        <span className="tabular-nums font-mono text-stance-avoid">
                          Stop {money(plan.stop)}
                        </span>
                        <span className="tabular-nums font-mono font-semibold text-text-primary">
                          Entry {money(plan.entry)}
                        </span>
                        <span className="tabular-nums font-mono text-stance-buy">
                          Target {money(plan.target)}
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-raised">
                        <div
                          className={`h-full ${
                            item.flipped_buy ? "bg-stance-buy" : "bg-accent"
                          }`}
                          style={{ width: `${fillRatio}%` }}
                        />
                      </div>
                    </div>
                  ) : null}

                  {/* Current unblended 4-strategy pills */}
                  {Object.keys(item.current_stances).length > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {Object.entries(item.current_stances).map(([sid, st]) => (
                        <span
                          key={sid}
                          className={`rounded-token border px-2 py-0.5 font-mono text-[10px] font-semibold ${
                            STANCE_PILL[st] ?? "border-border-subtle bg-surface-sunken text-text-muted"
                          }`}
                        >
                          {sid}: {st}
                        </span>
                      ))}
                    </div>
                  ) : null}

                  {item.themes.length > 0 ? (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {item.themes.map((t) => (
                        <Link
                          key={t.key}
                          href={`/themes/${encodeURIComponent(t.key)}`}
                          className="rounded-token border border-accent bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent"
                        >
                          {t.label}
                        </Link>
                      ))}
                    </div>
                  ) : null}

                  {/* Editable Personal Thesis Note */}
                  <div className="mt-3 border-t border-border-subtle pt-2.5">
                    {editingNoteSymbol === item.symbol ? (
                      <div className="space-y-2">
                        <textarea
                          rows={2}
                          value={noteDraft}
                          onChange={(e) => setNoteDraft(e.target.value)}
                          placeholder="Why am I watching this setup?"
                          className="w-full rounded-token border border-border-subtle bg-surface-sunken p-2 text-xs text-text-primary"
                        />
                        <div className="flex gap-2">
                          <button
                            type="button"
                            disabled={savingNote}
                            onClick={() => handleSaveNote(item.symbol)}
                            className="rounded-token bg-accent px-2.5 py-1 text-xs font-medium text-surface-raised"
                          >
                            {savingNote ? "Saving…" : "Save Note"}
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingNoteSymbol(null)}
                            className="rounded-token border border-border-subtle px-2.5 py-1 text-xs text-text-secondary"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start justify-between gap-2 text-xs">
                        <p className="text-text-secondary">
                          {item.notes ? item.notes : "No personal note recorded."}
                        </p>
                        <button
                          type="button"
                          onClick={() => {
                            setEditingNoteSymbol(item.symbol);
                            setNoteDraft(item.notes ?? "");
                          }}
                          className="shrink-0 text-[11px] font-medium text-accent hover:underline"
                        >
                          Edit note
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                <footer className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-3">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setTicket({
                          open: true,
                          symbol: item.symbol,
                          name: item.name,
                          book: item.book_intent,
                          strategyId: item.target_strategy_id,
                          plan: item.plan,
                          lastPrice: item.last_price,
                        })
                      }
                      className="rounded-token bg-text-primary px-2.5 py-1 text-xs font-medium text-surface-raised"
                    >
                      Promote to Paper Buy
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRemove(item.symbol)}
                      className="rounded-token border border-border-subtle px-2 py-1 text-xs text-text-muted hover:border-stance-avoid hover:text-stance-avoid"
                    >
                      Remove
                    </button>
                  </div>

                  <Link
                    href={`/stock?symbol=${encodeURIComponent(item.symbol)}`}
                    className="text-xs font-semibold text-accent hover:underline"
                  >
                    Inspect →
                  </Link>
                </footer>
              </article>
            );
          })}
        </div>
      )}

      <TradeTicketDrawer
        open={ticket.open}
        onClose={() => setTicket((prev) => ({ ...prev, open: false }))}
        symbol={ticket.symbol}
        companyName={ticket.name}
        side="BUY"
        defaultBook={ticket.book}
        defaultStrategyId={ticket.strategyId}
        plan={ticket.plan}
        lastPrice={ticket.lastPrice}
      />
    </div>
  );
}
