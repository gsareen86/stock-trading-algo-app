"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { rememberSymbol } from "@/components/command-palette";
import { Empty } from "@/components/states";
import { type PlanOption, StockChart } from "@/components/stock-chart";
import { TradeTicketDrawer } from "@/components/trade-ticket-drawer";
import { VerdictCard } from "@/components/verdict";
import type {
  Plan,
  Position,
  StockChartResponse,
  StockQualityResponse,
  StockResearchResponse,
  UniverseSymbol,
  Verdict,
} from "@/lib/api";

type CopilotTurn = {
  role: "user" | "assistant";
  content: string;
  toolCalls?: { tool: string; arguments: Record<string, unknown>; ok: boolean }[];
};

function money(val: number | null | undefined, digits = 2): string {
  if (val === null || val === undefined) return "—";
  return `₹${val.toLocaleString("en-IN", { maximumFractionDigits: digits })}`;
}

export function StockLookupHero({
  quickPicks,
}: {
  quickPicks: { symbol: string; tag: string }[];
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [universe, setUniverse] = useState<UniverseSymbol[]>([]);
  const [recent, setRecent] = useState<string[]>([]);

  useEffect(() => {
    fetch("/api/backend/universe/symbols?limit=750")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && Array.isArray(d.symbols)) setUniverse(d.symbols);
        try {
          const raw = window.localStorage.getItem("sw_recent_symbols");
          if (raw) {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) setRecent(parsed.slice(0, 5));
          }
        } catch {}
      })
      .catch(() => {});
  }, []);

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return [];
    const exactOrPrefix: UniverseSymbol[] = [];
    const contains: UniverseSymbol[] = [];
    for (const u of universe) {
      const sym = u.symbol.toUpperCase();
      const name = (u.name ?? "").toUpperCase();
      if (sym === q) {
        exactOrPrefix.unshift(u);
      } else if (sym.startsWith(q)) {
        exactOrPrefix.push(u);
      } else if (sym.includes(q) || name.includes(q)) {
        contains.push(u);
      }
    }
    return [...exactOrPrefix, ...contains].slice(0, 8);
  }, [query, universe]);

  function openSymbol(sym: string) {
    rememberSymbol(sym);
    router.push(`/stock?symbol=${encodeURIComponent(sym.trim().toUpperCase())}`);
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <section className="hero-surface p-8 text-center">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
          Single-Name Deep-Dive Workstation
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-text-primary">
          Inspect any NSE Nifty 750 Stock
        </h1>
        <p className="mx-auto mt-1.5 max-w-lg text-sm text-text-secondary">
          Interactive OHLCV + DMA chart, deterministic Entry / Stop / Target plans, all four independent strategy verdicts, quality ratios, concall digest, and AI Research Copilot.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            const q = query.trim().toUpperCase();
            if (!q) return;
            const exact = universe.find((u) => u.symbol.toUpperCase() === q);
            openSymbol(exact?.symbol ?? matches[0]?.symbol ?? q);
          }}
          className="mx-auto mt-6 flex max-w-md gap-2"
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type ticker or company (e.g. TRENT, BEL, TCS)…"
            aria-label="NSE symbol lookup"
            autoFocus
            className="w-full rounded-token border border-border-strong bg-surface-raised px-3.5 py-2 font-mono text-sm text-text-primary outline-none focus:border-accent"
          />
          <button
            type="submit"
            disabled={!query.trim()}
            className="shrink-0 cursor-pointer rounded-token bg-accent px-4 py-2 text-sm font-semibold text-surface-raised disabled:opacity-40"
          >
            Open →
          </button>
        </form>

        {matches.length > 0 ? (
          <div className="mx-auto mt-2 max-w-md overflow-hidden rounded-token-lg border border-border-subtle bg-surface-raised text-left shadow-md">
            {matches.map((m) => (
              <Link
                key={m.symbol}
                href={`/stock?symbol=${encodeURIComponent(m.symbol.toUpperCase())}`}
                onClick={() => rememberSymbol(m.symbol)}
                className="flex w-full cursor-pointer items-center justify-between border-b border-border-subtle px-3.5 py-2 text-xs last:border-b-0 hover:bg-surface-sunken"
              >
                <span>
                  <strong className="font-mono text-text-primary">{m.symbol}</strong>
                  <span className="ml-2 text-text-secondary">{m.name}</span>
                </span>
                {m.sector ? <span className="text-text-muted">{m.sector}</span> : null}
              </Link>
            ))}
          </div>
        ) : null}

        {recent.length > 0 ? (
          <div className="mt-6">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Recent Lookups
            </p>
            <div className="mt-2 flex flex-wrap justify-center gap-2">
              {recent.map((sym) => (
                <button
                  key={sym}
                  type="button"
                  onClick={() => openSymbol(sym)}
                  className="rounded-token border border-border-subtle bg-surface-raised px-3 py-1 font-mono text-xs font-medium text-text-primary hover:border-accent hover:text-accent"
                >
                  {sym}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {quickPicks.length > 0 ? (
          <div className="mt-6 border-t border-border-subtle pt-5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              From Your Watchlist &amp; Latest Scan
            </p>
            <div className="mt-2.5 flex flex-wrap justify-center gap-2">
              {quickPicks.map((item) => (
                <button
                  key={item.symbol}
                  type="button"
                  onClick={() => openSymbol(item.symbol)}
                  className="rounded-token border border-border-subtle bg-surface-sunken px-3 py-1.5 text-xs hover:border-accent"
                >
                  <span className="font-mono font-semibold text-text-primary">{item.symbol}</span>
                  <span className="ml-1.5 text-[11px] text-text-muted">{item.tag}</span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

export function StockWorkstation({
  symbol,
  verdicts,
  chart,
  quality,
  initialResearch,
  heldPositions,
  initiallyWatched,
}: {
  symbol: string;
  verdicts: Verdict[];
  chart: StockChartResponse | null;
  quality: StockQualityResponse | null;
  initialResearch: StockResearchResponse | null;
  heldPositions: Position[];
  initiallyWatched: boolean;
}) {
  const copilotSectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    rememberSymbol(symbol);
  }, [symbol]);

  const orderedVerdicts = useMemo(
    () => [...verdicts].sort((a, b) => a.strategy_id.localeCompare(b.strategy_id)),
    [verdicts],
  );

  const planOptions: PlanOption[] = useMemo(
    () =>
      orderedVerdicts
        .filter((v): v is Verdict & { plan: Plan } => Boolean(v.plan))
        .map((v) => ({ strategyId: v.strategy_id, stance: v.stance, plan: v.plan })),
    [orderedVerdicts],
  );

  const [selectedPlanStrategy, setSelectedPlanStrategy] = useState<string | null>(
    () => planOptions.find((p) => p.stance === "BUY")?.strategyId ?? planOptions[0]?.strategyId ?? null,
  );

  // Watchlist toggle
  const [watched, setWatched] = useState(initiallyWatched);
  const [watchBusy, setWatchBusy] = useState(false);

  // Plan sizing preview card inputs
  const [calcCap, setCalcCap] = useState("1000000");
  const [calcRiskPct, setCalcRiskPct] = useState(1);

  // Trade drawer
  const [ticket, setTicket] = useState<{
    open: boolean;
    side: "BUY" | "SELL";
    book: "swing" | "longterm";
    strategyId: string | null;
    plan: Plan | null;
    maxSell?: number | null;
  }>({ open: false, side: "BUY", book: "swing", strategyId: null, plan: null });

  // Research tabs: Concall | Filings & News | AI Copilot
  const [intelTab, setIntelTab] = useState<"concall" | "filings" | "copilot">("concall");
  const [research, setResearch] = useState<StockResearchResponse | null>(initialResearch);
  const [summarizingConcall, setSummarizingConcall] = useState(false);

  // Copilot multi-turn Q&A
  const [question, setQuestion] = useState("");
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotTurns, setCopilotTurns] = useState<CopilotTurn[]>([]);
  const [copilotError, setCopilotError] = useState<string | null>(null);

  const activePlanObj =
    planOptions.find((p) => p.strategyId === selectedPlanStrategy) ?? planOptions[0] ?? null;

  const capital = Number.parseFloat(calcCap) || 0;
  const riskPerShare = activePlanObj
    ? Math.max(0.01, activePlanObj.plan.entry - activePlanObj.plan.stop)
    : 0;
  const suggestedShares =
    activePlanObj && capital > 0 && riskPerShare > 0
      ? Math.max(1, Math.floor((capital * (calcRiskPct / 100)) / riskPerShare))
      : 0;

  async function toggleWatchlist() {
    setWatchBusy(true);
    try {
      if (watched) {
        const res = await fetch(`/api/backend/watchlist/${encodeURIComponent(symbol)}`, {
          method: "DELETE",
        });
        if (res.ok) setWatched(false);
      } else {
        const res = await fetch("/api/backend/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbol,
            book_intent:
              activePlanObj?.strategyId === "brahma_vishnu_mahesh" ? "longterm" : "swing",
            target_strategy_id: activePlanObj?.strategyId ?? null,
          }),
        });
        if (res.ok) setWatched(true);
      }
    } finally {
      setWatchBusy(false);
    }
  }

  async function loadConcallDigest() {
    setSummarizingConcall(true);
    try {
      const res = await fetch(
        `/api/backend/stocks/${encodeURIComponent(symbol)}/research?summarize=true`,
      );
      if (res.ok) {
        const body = (await res.json()) as StockResearchResponse;
        setResearch(body);
      }
    } finally {
      setSummarizingConcall(false);
    }
  }

  async function askCopilot(promptText: string) {
    const clean = promptText.trim();
    if (!clean) return;
    setCopilotBusy(true);
    setCopilotError(null);
    setCopilotTurns((prev) => [...prev, { role: "user", content: clean }]);
    setQuestion("");

    try {
      const res = await fetch("/api/backend/research/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: `${symbol}: ${clean}` }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setCopilotError(body.detail ?? `HTTP ${res.status}`);
        return;
      }
      setCopilotTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          content: body.answer ?? "No response returned.",
          toolCalls: Array.isArray(body.tool_calls) ? body.tool_calls : [],
        },
      ]);
    } catch {
      setCopilotError("Could not reach the research agent.");
    } finally {
      setCopilotBusy(false);
    }
  }

  const lastPx = chart?.last_price ?? null;
  const changePct = chart?.change_pct ?? null;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      {/* Instrument Hero Header Card */}
      <section className="hero-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
              <Link href="/stock" className="hover:text-text-primary">
                Lookup
              </Link>
              {quality?.sector ? (
                <>
                  <span>/</span>
                  <span>{quality.sector}</span>
                </>
              ) : null}
              {quality?.industry && quality.industry !== quality.sector ? (
                <>
                  <span>/</span>
                  <span>{quality.industry}</span>
                </>
              ) : null}
            </div>

            <div className="mt-1.5 flex flex-wrap items-baseline gap-3">
              <h1 className="font-mono text-3xl font-bold tracking-tight text-text-primary">
                {symbol}
              </h1>
              {quality?.company_name ? (
                <span className="text-base font-medium text-text-secondary">
                  {quality.company_name}
                </span>
              ) : null}
            </div>

            {research && research.themes.length > 0 ? (
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {research.themes.map((t) => (
                  <Link
                    key={t.theme_key}
                    href={`/themes/${encodeURIComponent(t.theme_key)}`}
                    className="rounded-token border border-accent bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent hover:underline"
                  >
                    Theme: {t.label} · {t.exposure}
                  </Link>
                ))}
              </div>
            ) : null}
          </div>

          <div className="flex flex-col items-end gap-3">
            {lastPx !== null ? (
              <div className="text-right">
                <p className="tabular-nums font-mono text-2xl font-bold text-text-primary">
                  {money(lastPx)}
                </p>
                {changePct !== null ? (
                  <p
                    className={`tabular-nums font-mono text-xs font-semibold ${
                      changePct >= 0 ? "text-stance-buy" : "text-stance-avoid"
                    }`}
                  >
                    {changePct >= 0 ? "+" : ""}
                    {changePct.toFixed(2)}% (1D)
                  </p>
                ) : null}
              </div>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={watchBusy}
                onClick={toggleWatchlist}
                className={`rounded-token border px-3 py-1.5 text-xs font-medium ${
                  watched
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border-strong bg-surface-raised text-text-primary"
                }`}
              >
                {watched ? "✓ On Watchlist" : "+ Watchlist"}
              </button>

              <button
                type="button"
                onClick={() =>
                  setTicket({
                    open: true,
                    side: "BUY",
                    book:
                      activePlanObj?.strategyId === "brahma_vishnu_mahesh" ? "longterm" : "swing",
                    strategyId: activePlanObj?.strategyId ?? null,
                    plan: activePlanObj?.plan ?? null,
                  })
                }
                className="rounded-token bg-accent px-3 py-1.5 text-xs font-semibold text-surface-raised"
              >
                Log Paper Trade
              </button>

              <button
                type="button"
                onClick={() => {
                  setIntelTab("copilot");
                  copilotSectionRef.current?.scrollIntoView({ behavior: "smooth" });
                }}
                className="rounded-token border border-border-subtle bg-surface-sunken px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary"
              >
                Ask Copilot
              </button>
            </div>
          </div>
        </div>

        {/* Held Position Strip (only when actually held) */}
        {heldPositions.length > 0 ? (
          <div className="mt-4 grid gap-2 border-t border-border-subtle pt-4 sm:grid-cols-2">
            {heldPositions.map((pos) => (
              <div
                key={pos.book}
                className="flex flex-wrap items-center justify-between gap-2 rounded-token-lg border border-border-subtle bg-surface-raised px-4 py-2.5 text-xs"
              >
                <div>
                  <span className="font-semibold capitalize text-text-primary">
                    Held in {pos.book}
                  </span>
                  <span className="tabular-nums ml-2 font-mono text-text-secondary">
                    {pos.quantity} sh @ {money(pos.average_cost)}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span
                    className={`tabular-nums font-mono font-semibold ${
                      (pos.unrealised_pnl_gross ?? 0) >= 0
                        ? "text-stance-buy"
                        : "text-stance-avoid"
                    }`}
                  >
                    {pos.unrealised_pnl_gross === null
                      ? "P&L unavail"
                      : `${money(pos.unrealised_pnl_gross, 0)} gross`}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setTicket({
                        open: true,
                        side: "SELL",
                        book: pos.book === "longterm" ? "longterm" : "swing",
                        strategyId: null,
                        plan: null,
                        maxSell: pos.quantity,
                      })
                    }
                    className="rounded-token border border-border-strong px-2 py-0.5 font-medium text-text-primary hover:bg-surface-sunken"
                  >
                    Trim / Exit
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      {/* Tier 1: Interactive Chart + Trade Plan & Sizing Split */}
      <div className="grid gap-5 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <StockChart
            key={symbol}
            symbol={symbol}
            initialChart={chart}
            plans={planOptions}
            selectedPlanStrategy={selectedPlanStrategy}
            onSelectPlanStrategy={setSelectedPlanStrategy}
          />
        </div>

        <aside className="card-surface flex flex-col justify-between p-5 lg:col-span-4">
          <div>
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Trade Plan &amp; Sizing
              </h2>
              {activePlanObj ? (
                <span className="rounded-token bg-surface-sunken px-2 py-0.5 font-mono text-[11px] text-text-primary">
                  {activePlanObj.strategyId}
                </span>
              ) : null}
            </div>

            {planOptions.length > 1 ? (
              <div className="mt-3 flex flex-wrap gap-1">
                {planOptions.map((opt) => (
                  <button
                    key={opt.strategyId}
                    type="button"
                    onClick={() => setSelectedPlanStrategy(opt.strategyId)}
                    className={`rounded-token border px-2 py-1 text-[11px] font-medium ${
                      activePlanObj?.strategyId === opt.strategyId
                        ? "border-accent bg-accent-soft text-accent"
                        : "border-border-subtle bg-surface-sunken text-text-secondary"
                    }`}
                  >
                    {opt.strategyId}
                  </button>
                ))}
              </div>
            ) : null}

            {activePlanObj ? (
              <div className="mt-4 space-y-3">
                <div className="grid grid-cols-2 gap-2.5">
                  <div className="rounded-token bg-surface-sunken p-2.5">
                    <span className="text-[11px] text-text-muted">Entry ({activePlanObj.plan.entry_kind})</span>
                    <p className="tabular-nums mt-0.5 font-mono text-base font-semibold text-text-primary">
                      {money(activePlanObj.plan.entry)}
                    </p>
                  </div>
                  <div className="rounded-token bg-surface-sunken p-2.5">
                    <span className="text-[11px] text-text-muted">Stop Loss</span>
                    <p className="tabular-nums mt-0.5 font-mono text-base font-semibold text-stance-avoid">
                      {money(activePlanObj.plan.stop)}
                    </p>
                  </div>
                  <div className="rounded-token bg-surface-sunken p-2.5">
                    <span className="text-[11px] text-text-muted">Initial Target</span>
                    <p className="tabular-nums mt-0.5 font-mono text-base font-semibold text-stance-buy">
                      {money(activePlanObj.plan.target)}
                    </p>
                  </div>
                  <div className="rounded-token bg-surface-sunken p-2.5">
                    <span className="text-[11px] text-text-muted">Risk : Reward</span>
                    <p className="tabular-nums mt-0.5 font-mono text-base font-semibold text-text-primary">
                      {activePlanObj.plan.risk_reward ? `${activePlanObj.plan.risk_reward}:1` : "—"}
                    </p>
                  </div>
                </div>

                {activePlanObj.plan.note ? (
                  <p className="text-xs text-text-secondary">{activePlanObj.plan.note}</p>
                ) : null}

                <div className="rounded-token-lg border border-border-subtle bg-surface-sunken p-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    Position Sizing Calculator
                  </p>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <label className="text-[11px] text-text-muted">
                      Book Capital (₹)
                      <input
                        type="number"
                        value={calcCap}
                        onChange={(e) => setCalcCap(e.target.value)}
                        className="tabular-nums mt-1 w-full rounded-token border border-border-subtle bg-surface-raised px-2 py-1 font-mono text-xs text-text-primary"
                      />
                    </label>
                    <label className="text-[11px] text-text-muted">
                      Risk %
                      <select
                        value={calcRiskPct}
                        onChange={(e) => setCalcRiskPct(Number(e.target.value))}
                        className="mt-1 w-full rounded-token border border-border-subtle bg-surface-raised px-2 py-1 font-mono text-xs text-text-primary"
                      >
                        <option value={0.5}>0.5%</option>
                        <option value={1}>1.0%</option>
                        <option value={1.5}>1.5%</option>
                        <option value={2}>2.0%</option>
                      </select>
                    </label>
                  </div>
                  <p className="mt-2 text-xs text-text-secondary">
                    Suggested size:{" "}
                    <strong className="tabular-nums font-mono text-text-primary">
                      {suggestedShares} shares
                    </strong>{" "}
                    ({money(suggestedShares * activePlanObj.plan.entry, 0)} outlay)
                  </p>
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded-token bg-surface-sunken p-4 text-xs text-text-secondary">
                No strategy currently holds an active BUY/WATCH entry plan on {symbol}.
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() =>
              setTicket({
                open: true,
                side: "BUY",
                book:
                  activePlanObj?.strategyId === "brahma_vishnu_mahesh" ? "longterm" : "swing",
                strategyId: activePlanObj?.strategyId ?? null,
                plan: activePlanObj?.plan ?? null,
              })
            }
            className="mt-4 w-full rounded-token bg-text-primary px-4 py-2 text-xs font-semibold text-surface-raised hover:opacity-90"
          >
            Preview Paper Order →
          </button>
        </aside>
      </div>

      {/* Tier 2: Four Independent Strategy Verdicts */}
      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Four Independent Strategy Readings
          </h2>
          <p className="text-xs text-text-muted">
            Conviction is scoped to each strategy independently — never blended.
          </p>
        </div>

        {orderedVerdicts.length === 0 ? (
          <Empty>No strategy could form a verdict on {symbol}.</Empty>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {orderedVerdicts.map((v) => (
              <VerdictCard
                key={v.strategy_id}
                verdict={v}
                onPreviewPlan={(sid, plan) =>
                  setTicket({
                    open: true,
                    side: "BUY",
                    book: sid === "brahma_vishnu_mahesh" ? "longterm" : "swing",
                    strategyId: sid,
                    plan,
                  })
                }
              />
            ))}
          </div>
        )}
      </section>

      {/* Tier 3: Fundamental Quality & AI Intelligence Split */}
      <div className="grid gap-5 lg:grid-cols-12" ref={copilotSectionRef}>
        {/* Business Quality KPI & Shareholding Card */}
        <section className="card-surface p-5 lg:col-span-5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
              Business Quality &amp; Profile
            </h2>
            {quality?.source ? (
              <span className="font-mono text-[11px] text-text-muted">{quality.source}</span>
            ) : null}
          </div>

          {quality && quality.facets.length > 0 ? (
            <div className="mt-4 grid grid-cols-2 gap-2.5">
              {quality.facets.map((f) => (
                <div key={f.key} className="rounded-token bg-surface-sunken p-3">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[11px] text-text-muted">{f.label}</span>
                    <span
                      className={`text-[10px] font-semibold uppercase ${
                        f.status === "pass"
                          ? "text-stance-buy"
                          : f.status === "fail"
                            ? "text-stance-avoid"
                            : "text-text-muted"
                      }`}
                    >
                      {f.status.replace("_", " ")}
                    </span>
                  </div>
                  <p className="tabular-nums mt-1 font-mono text-base font-semibold text-text-primary">
                    {f.status === "not_applicable"
                      ? "N/A"
                      : f.value === null
                        ? "Unavailable"
                        : `${f.value}${f.unit}`}
                  </p>
                  {f.reason ? (
                    <p className="mt-0.5 text-[10px] text-text-muted">{f.reason}</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-xs text-text-muted">
              {quality?.unavailable_reason ?? "Quality metrics unavailable."}
            </p>
          )}

          {quality?.shareholding ? (
            <div className="mt-4 border-t border-border-subtle pt-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                Shareholding ({quality.shareholding.source})
              </p>
              <div className="mt-2 grid grid-cols-4 gap-2 text-xs">
                <div>
                  <span className="block text-[10px] text-text-muted">Promoter</span>
                  <span className="tabular-nums font-mono text-text-primary">
                    {quality.shareholding.promoter_pct !== null
                      ? `${quality.shareholding.promoter_pct}%`
                      : "Unavail"}
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-text-muted">FII</span>
                  <span className="tabular-nums font-mono text-text-primary">
                    {quality.shareholding.fii_pct !== null
                      ? `${quality.shareholding.fii_pct}%`
                      : "Unavail"}
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-text-muted">DII</span>
                  <span className="tabular-nums font-mono text-text-primary">
                    {quality.shareholding.dii_pct !== null
                      ? `${quality.shareholding.dii_pct}%`
                      : "Unavail"}
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-text-muted">Pledge</span>
                  <span
                    className="tabular-nums font-mono text-text-muted"
                    title="Requires IndianAPI when absent from Yahoo Finance"
                  >
                    {quality.shareholding.pledge_pct !== null
                      ? `${quality.shareholding.pledge_pct}%`
                      : "Unavail"}
                  </span>
                </div>
              </div>
            </div>
          ) : null}

          {quality?.description ? (
            <details className="mt-4 border-t border-border-subtle pt-3">
              <summary className="cursor-pointer text-xs font-medium text-text-muted hover:text-text-primary">
                Company business summary
              </summary>
              <p className="mt-2 text-xs leading-relaxed text-text-secondary">
                {quality.description}
              </p>
            </details>
          ) : null}
        </section>

        {/* Tabbed Intelligence & Copilot Card */}
        <section className="card-surface flex flex-col p-5 lg:col-span-7">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle pb-3">
            <div className="flex gap-1 rounded-token bg-surface-sunken p-1 text-xs">
              {(
                [
                  { id: "concall", label: "Concall Digest" },
                  { id: "filings", label: "Filings & News" },
                  { id: "copilot", label: "AI Research Copilot" },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setIntelTab(tab.id)}
                  className={`rounded-token px-3 py-1 font-medium transition-colors ${
                    intelTab === tab.id
                      ? "bg-surface-raised text-text-primary shadow-xs"
                      : "text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {intelTab === "concall" ? (
            <div className="mt-4 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-text-secondary">
                  Extracted concall themes &amp; on-demand management transcript digest
                </p>
                <button
                  type="button"
                  disabled={summarizingConcall}
                  onClick={loadConcallDigest}
                  className="rounded-token border border-border-strong bg-surface-sunken px-3 py-1.5 text-xs font-medium text-text-primary hover:border-accent disabled:opacity-50"
                >
                  {summarizingConcall ? "Reading latest transcript…" : "Summarize Latest Concall"}
                </button>
              </div>

              {research && research.concall_digest.length > 0 ? (
                <div className="space-y-2.5">
                  {research.concall_digest.map((sec, idx) => (
                    <div key={idx} className="rounded-token bg-surface-sunken p-3">
                      <p className="text-xs font-semibold text-text-primary">
                        {sec.section ?? "Section"}
                      </p>
                      <p className="mt-1 text-xs text-text-secondary">
                        {sec.summary ?? "Not discussed by management"}
                      </p>
                    </div>
                  ))}
                </div>
              ) : null}

              {research && research.concepts.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    Extracted Document Concepts ({research.concepts.length})
                  </p>
                  {research.concepts.map((c, idx) => (
                    <div
                      key={idx}
                      className="rounded-token border border-border-subtle bg-surface-sunken p-3 text-xs"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-text-primary">{c.concept}</span>
                        <span className="font-mono text-[11px] text-text-muted">
                          {c.period} · {c.kind}
                        </span>
                      </div>
                      {c.excerpt ? (
                        <p className="mt-1 text-text-secondary">&ldquo;{c.excerpt}&rdquo;</p>
                      ) : null}
                      <p className="mt-1 text-[10px] text-stance-watch">
                        Extracted by {c.extracted_by} — quoted from document, not measured
                      </p>
                    </div>
                  ))}
                </div>
              ) : research?.concall_digest.length === 0 ? (
                <p className="text-xs text-text-muted">
                  No stored concall excerpts yet. Click &ldquo;Summarize Latest Concall&rdquo; above or ask the AI Copilot.
                </p>
              ) : null}
            </div>
          ) : null}

          {intelTab === "filings" ? (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  BSE / NSE Filings
                </h3>
                {research?.filings.items.length ? (
                  <ul className="mt-2 space-y-2">
                    {research.filings.items.map((item, idx) => (
                      <li
                        key={idx}
                        className="rounded-token border border-border-subtle bg-surface-sunken p-2.5 text-xs"
                      >
                        <p className="font-medium text-text-primary">
                          {item.headline ?? item.title ?? "Filing"}
                        </p>
                        <p className="mt-1 text-[11px] text-text-muted">
                          {item.filed_at ?? ""} {item.category ? `· ${item.category}` : ""}
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-xs text-text-muted">
                    {research?.filings.available
                      ? "No recent corporate announcements found."
                      : "Filings source unavailable right now."}
                  </p>
                )}
              </div>

              <div>
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Financial News
                </h3>
                {research?.news.items.length ? (
                  <ul className="mt-2 space-y-2">
                    {research.news.items.map((item, idx) => (
                      <li
                        key={idx}
                        className="rounded-token border border-border-subtle bg-surface-sunken p-2.5 text-xs"
                      >
                        <p className="font-medium text-text-primary">
                          {item.title ?? item.headline ?? "News item"}
                        </p>
                        <p className="mt-1 text-[11px] text-text-muted">
                          {item.source ?? "Feed"} {item.published_at ? `· ${item.published_at}` : ""}
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-xs text-text-muted">
                    No matching news articles found for {symbol} in last 7 days.
                  </p>
                )}
              </div>
            </div>
          ) : null}

          {intelTab === "copilot" ? (
            <div className="mt-4 flex flex-1 flex-col justify-between space-y-3">
              <div>
                <p className="rounded-token bg-surface-sunken px-3 py-2 text-[11px] text-text-muted">
                  Research Copilot invokes the 18-tool registry (concalls, filings, sector rotation, company quality, peers, web search). It cannot emit BUY/SELL advice or touch orders.
                </p>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {[
                    "Summarize recent concall capex & guidance vs peers",
                    "Check sector rotation and policy catalysts",
                    "What risks appear in recent filings and debt profile?",
                  ].map((starter) => (
                    <button
                      key={starter}
                      type="button"
                      disabled={copilotBusy}
                      onClick={() => askCopilot(starter)}
                      className="rounded-token border border-border-subtle bg-surface-sunken px-2.5 py-1 text-[11px] text-text-secondary hover:border-accent hover:text-text-primary"
                    >
                      {starter}
                    </button>
                  ))}
                </div>

                {copilotTurns.length > 0 ? (
                  <div className="mt-4 max-h-80 space-y-3 overflow-y-auto pr-1">
                    {copilotTurns.map((turn, idx) => (
                      <div
                        key={idx}
                        className={`rounded-token-lg p-3 text-xs ${
                          turn.role === "user"
                            ? "ml-8 bg-accent-soft text-text-primary"
                            : "mr-4 border border-border-subtle bg-surface-sunken text-text-secondary"
                        }`}
                      >
                        <p className="whitespace-pre-line leading-relaxed">{turn.content}</p>
                        {turn.toolCalls && turn.toolCalls.length > 0 ? (
                          <details className="mt-2 border-t border-border-subtle pt-1.5">
                            <summary className="cursor-pointer text-[10px] font-medium text-text-muted">
                              {turn.toolCalls.length} tool call provenance
                            </summary>
                            <div className="mt-1 flex flex-wrap gap-1">
                              {turn.toolCalls.map((tc, tIdx) => (
                                <span
                                  key={tIdx}
                                  className="rounded-token border border-border-subtle bg-surface-raised px-1.5 py-0.5 font-mono text-[10px] text-text-muted"
                                >
                                  {tc.tool} ({tc.ok ? "ok" : "err"})
                                </span>
                              ))}
                            </div>
                          </details>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}

                {copilotError ? (
                  <p role="alert" className="mt-2 text-xs text-stance-avoid">
                    {copilotError}
                  </p>
                ) : null}
              </div>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  askCopilot(question);
                }}
                className="flex gap-2 border-t border-border-subtle pt-3"
              >
                <input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={`Ask Research Copilot about ${symbol}…`}
                  className="flex-1 rounded-token border border-border-subtle bg-surface-sunken px-3 py-2 text-xs text-text-primary outline-none focus:border-accent"
                />
                <button
                  type="submit"
                  disabled={copilotBusy || question.trim().length < 2}
                  className="rounded-token bg-accent px-3.5 py-2 text-xs font-semibold text-surface-raised disabled:opacity-40"
                >
                  {copilotBusy ? "Thinking…" : "Ask"}
                </button>
              </form>
            </div>
          ) : null}
        </section>
      </div>

      <TradeTicketDrawer
        open={ticket.open}
        onClose={() => setTicket((prev) => ({ ...prev, open: false }))}
        symbol={symbol}
        companyName={quality?.company_name}
        side={ticket.side}
        defaultBook={ticket.book}
        defaultStrategyId={ticket.strategyId}
        plan={ticket.plan}
        lastPrice={lastPx}
        maxSellQuantity={ticket.maxSell}
      />
    </div>
  );
}
