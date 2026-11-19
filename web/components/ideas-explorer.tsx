"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { LiveProgressCard, type ProgressStep, useSseStream } from "@/components/live-progress";
import { SectorRrgPlot } from "@/components/sector-rrg-plot";
import { Empty } from "@/components/states";
import { TradeTicketDrawer } from "@/components/trade-ticket-drawer";
import type {
  DiscoveryCandidate,
  IndexSnapshot,
  LatestDiscoveryResponse,
  NotableMover,
  Plan,
  SectorPlacement,
  Verdict,
} from "@/lib/api";

const SCAN_STEPS: ProgressStep[] = [
  { id: "sectors", label: "Sector RRG" },
  { id: "screen", label: "Screen 750" },
  { id: "evaluate", label: "4 Strategies + Plans" },
  { id: "quality", label: "Quality Facets" },
  { id: "narrate", label: "Narrate Head" },
];

const STANCE_CHIP: Record<string, string> = {
  BUY: "border-stance-buy bg-stance-buy-soft text-stance-buy",
  WATCH: "border-stance-watch bg-stance-watch-soft text-stance-watch",
  AVOID: "border-stance-avoid bg-stance-avoid-soft text-stance-avoid",
};

const QUADRANT_CHIP: Record<string, string> = {
  Leading: "bg-quadrant-leading-soft text-quadrant-leading",
  Improving: "bg-quadrant-improving-soft text-quadrant-improving",
  Weakening: "bg-quadrant-weakening-soft text-quadrant-weakening",
  Lagging: "bg-quadrant-lagging-soft text-quadrant-lagging",
  unplaced: "bg-surface-sunken text-text-muted",
};

const STRATEGY_SHORT: Record<string, string> = {
  minervini: "Minervini",
  young_momentum: "YoungMom",
  brahma_vishnu_mahesh: "BVM",
  fun_tech_momentum: "Fun-Tech",
};

function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function regimeText(idx?: IndexSnapshot): string {
  if (!idx || !idx.available) return "Unavailable";
  const c = typeof idx.close === "number" ? idx.close.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "—";
  const p =
    typeof idx.change_pct === "number"
      ? `${idx.change_pct >= 0 ? "+" : ""}${idx.change_pct.toFixed(2)}%`
      : "";
  return `${c} ${p}`.trim();
}

export function IdeasExplorer({
  initialLatest,
  initialSectors,
  initialWatchedSymbols,
  nifty50,
  nifty500,
}: {
  initialLatest: LatestDiscoveryResponse | null;
  initialSectors: SectorPlacement[];
  initialWatchedSymbols: string[];
  nifty50?: IndexSnapshot;
  nifty500?: IndexSnapshot;
}) {
  const router = useRouter();
  const stream = useSseStream<Record<string, unknown>>();

  const [benchmark, setBenchmark] = useState<"^CRSLDX" | "^NSEI">("^CRSLDX");
  const [sectors, setSectors] = useState<SectorPlacement[]>(initialSectors);
  const [selectedSectorKey, setSelectedSectorKey] = useState<string | null>(null);
  const [movers, setMovers] = useState<NotableMover[]>([]);
  const [loadedMoversKey, setLoadedMoversKey] = useState<string | null>(null);

  // Multi-facet filter state (client-side refinement of latest server-ranked run)
  const [strategyFilter, setStrategyFilter] = useState<string>("");
  const [stanceFilter, setStanceFilter] = useState<string>("");
  const [minBuyFilter, setMinBuyFilter] = useState<number | null>(null);
  const [roeMin, setRoeMin] = useState(false);
  const [salesMin, setSalesMin] = useState(false);
  const [lowDebt, setLowDebt] = useState(false);
  const [themeOnly, setThemeOnly] = useState(false);

  // Per-card active strategy tab + optimistic watchlist tracking
  const [selectedStrategyMap, setSelectedStrategyMap] = useState<Record<string, string>>({});
  const [watchedSet, setWatchedSet] = useState<Set<string>>(() => new Set(initialWatchedSymbols));
  const [watchBusy, setWatchBusy] = useState<string | null>(null);
  const [scanSummary, setScanSummary] = useState<string | null>(null);

  // Slide-over Trade Ticket Drawer state
  const [ticketState, setTicketState] = useState<{
    open: boolean;
    symbol: string;
    name: string | null;
    strategyId: string;
    plan: Plan | null;
  }>({ open: false, symbol: "", name: null, strategyId: "", plan: null });

  const defaultSpotlight = useMemo(() => {
    return (
      sectors.find((s) => s.quadrant === "Improving") ??
      sectors.find((s) => s.quadrant === "Leading") ??
      sectors[0] ??
      null
    );
  }, [sectors]);

  const spotlight = useMemo(() => {
    if (selectedSectorKey) {
      return sectors.find((s) => s.key === selectedSectorKey) ?? defaultSpotlight;
    }
    return defaultSpotlight;
  }, [sectors, selectedSectorKey, defaultSpotlight]);

  const moversRequestKey = spotlight?.key ? `${spotlight.key}:${benchmark}` : null;
  const loadingMovers = Boolean(moversRequestKey && loadedMoversKey !== moversRequestKey);

  useEffect(() => {
    if (!spotlight?.key || !moversRequestKey) return;
    let cancelled = false;
    fetch(
      `/api/backend/discovery/movers?sector=${encodeURIComponent(spotlight.key)}&benchmark=${encodeURIComponent(benchmark)}`,
    )
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data && Array.isArray(data.movers)) {
          setMovers(data.movers.slice(0, 6));
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadedMoversKey(moversRequestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [spotlight?.key, benchmark, moversRequestKey]);

  async function switchBenchmark(nextBench: "^CRSLDX" | "^NSEI") {
    setBenchmark(nextBench);
    const res = await fetch(
      `/api/backend/discovery/sectors?benchmark=${encodeURIComponent(nextBench)}`,
    );
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.sectors)) {
        setSectors(data.sectors);
      }
    }
  }

  async function runScan() {
    setScanSummary(null);
    await stream.start(
      "/api/backend/discovery/scan/stream",
      { trigger: "requested", benchmark, narrate: true, narrate_head: 10 },
      (data) => {
        const eligible = typeof data.eligible_count === "number" ? data.eligible_count : 0;
        setScanSummary(`Discovery scan complete: ${eligible} setups ranked.`);
        router.refresh();
      },
    );
  }

  async function toggleWatchlist(candidate: DiscoveryCandidate) {
    const sym = candidate.symbol;
    const isWatched = watchedSet.has(sym);
    setWatchBusy(sym);
    try {
      if (isWatched) {
        const res = await fetch(`/api/backend/watchlist/${encodeURIComponent(sym)}`, {
          method: "DELETE",
        });
        if (res.ok) {
          setWatchedSet((prev) => {
            const next = new Set(prev);
            next.delete(sym);
            return next;
          });
        }
      } else {
        const res = await fetch("/api/backend/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbol: sym,
            book_intent: candidate.ranked_by === "brahma_vishnu_mahesh" ? "longterm" : "swing",
            target_strategy_id: candidate.ranked_by,
          }),
        });
        if (res.ok) {
          setWatchedSet((prev) => new Set(prev).add(sym));
        }
      }
    } finally {
      setWatchBusy(null);
    }
  }

  const allCandidates = useMemo(() => initialLatest?.candidates ?? [], [initialLatest]);

  const filteredCandidates = useMemo(() => {
    return allCandidates.filter((c) => {
      if (selectedSectorKey && c.sector_key !== selectedSectorKey) return false;
      if (minBuyFilter !== null && c.buy_count < minBuyFilter) return false;
      if (themeOnly && c.themes.length === 0) return false;

      if (strategyFilter || stanceFilter) {
        const match = c.verdicts.some((v) => {
          if (strategyFilter && v.strategy_id !== strategyFilter) return false;
          if (stanceFilter && v.stance !== stanceFilter) return false;
          return true;
        });
        if (!match) return false;
      }

      if (roeMin) {
        const roe = c.quality?.facets?.find((f) => f.key === "roe")?.value;
        if (typeof roe !== "number" || roe < 15) return false;
      }
      if (salesMin) {
        const sales = c.quality?.facets?.find((f) => f.key === "sales_yoy")?.value;
        if (typeof sales !== "number" || sales < 15) return false;
      }
      if (lowDebt) {
        const debtFacet = c.quality?.facets?.find((f) => f.key === "debt_equity");
        if (
          debtFacet &&
          debtFacet.status !== "not_applicable" &&
          (typeof debtFacet.value !== "number" || debtFacet.value > 0.5)
        ) {
          return false;
        }
      }
      return true;
    });
  }, [
    allCandidates,
    selectedSectorKey,
    strategyFilter,
    stanceFilter,
    minBuyFilter,
    roeMin,
    salesMin,
    lowDebt,
    themeOnly,
  ]);

  const hasScan = Boolean(initialLatest?.run);

  return (
    <div className="space-y-6">
      {/* Market Regime & Benchmark Strip */}
      <section className="hero-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Sector-First Discovery Funnel
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text-primary">
              Ideas &amp; Sector Rotation
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Start from rotating Nifty sectors, isolate clean setups across four independent strategies, and verify business quality without blended scores.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1 rounded-token bg-surface-sunken p-1 text-xs">
              <button
                type="button"
                onClick={() => switchBenchmark("^CRSLDX")}
                className={`rounded-token px-2.5 py-1 font-medium ${
                  benchmark === "^CRSLDX"
                    ? "bg-surface-raised text-text-primary shadow-xs"
                    : "text-text-secondary"
                }`}
              >
                vs Nifty 500
              </button>
              <button
                type="button"
                onClick={() => switchBenchmark("^NSEI")}
                className={`rounded-token px-2.5 py-1 font-medium ${
                  benchmark === "^NSEI"
                    ? "bg-surface-raised text-text-primary shadow-xs"
                    : "text-text-secondary"
                }`}
              >
                vs Nifty 50
              </button>
            </div>

            <button
              type="button"
              disabled={stream.running}
              onClick={runScan}
              className="rounded-token bg-accent px-3.5 py-2 text-xs font-semibold text-surface-raised transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {stream.running ? "Scanning 750…" : "Run Nifty 750 Scan"}
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4 border-t border-border-subtle pt-3 text-xs">
          <span className="tabular-nums font-mono text-text-primary">
            Nifty 50: {regimeText(nifty50)}
          </span>
          <span className="tabular-nums font-mono text-text-secondary">
            Nifty 500: {regimeText(nifty500)}
          </span>
          {initialLatest?.run ? (
            <span className="ml-auto text-text-muted">
              Scan #{initialLatest.run.id} · {initialLatest.run.eligible_count} ranked from{" "}
              {initialLatest.run.considered_count} stocks
            </span>
          ) : null}
        </div>

        <LiveProgressCard
          title="Nifty Total Market Scan Progress"
          steps={SCAN_STEPS}
          running={stream.running}
          progress={stream.progress}
          elapsed={stream.elapsed}
          error={stream.error}
          completeSummary={scanSummary}
        />
      </section>

      {/* 2-Card Hero Split: RRG Plot + Active Sector Spotlight */}
      <section className="grid gap-5 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <SectorRrgPlot
            sectors={sectors}
            selectedSectorKey={selectedSectorKey}
            onSelectSector={setSelectedSectorKey}
          />
        </div>

        <div className="card-surface flex flex-col justify-between p-5 lg:col-span-5">
          {spotlight ? (
            <div>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    {selectedSectorKey ? "Selected Sector Spotlight" : "Leading / Improving Spotlight"}
                  </p>
                  <h2 className="mt-1 text-lg font-semibold text-text-primary">
                    {spotlight.nse_name}
                  </h2>
                </div>
                <span
                  className={`rounded-token px-2.5 py-0.5 text-xs font-semibold ${
                    QUADRANT_CHIP[spotlight.quadrant] ?? QUADRANT_CHIP.unplaced
                  }`}
                >
                  {spotlight.quadrant}
                </span>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-token bg-surface-sunken p-3">
                  <span className="text-[11px] text-text-muted">RS-Ratio</span>
                  <p className="tabular-nums mt-0.5 font-mono text-base font-semibold text-text-primary">
                    {spotlight.rs_ratio !== null ? spotlight.rs_ratio.toFixed(2) : "—"}
                  </p>
                </div>
                <div className="rounded-token bg-surface-sunken p-3">
                  <span className="text-[11px] text-text-muted">RS-Momentum</span>
                  <p className="tabular-nums mt-0.5 font-mono text-base font-semibold text-text-primary">
                    {spotlight.rs_momentum !== null ? spotlight.rs_momentum.toFixed(2) : "—"}
                  </p>
                </div>
              </div>

              <div className="mt-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    Notable Sector Movers
                  </h3>
                  {loadingMovers ? (
                    <span className="text-[11px] text-text-muted">Checking…</span>
                  ) : null}
                </div>
                {movers.length === 0 && !loadingMovers ? (
                  <p className="mt-2 text-xs text-text-muted">
                    No constituent crossed 52W-high / 2x-volume thresholds today.
                  </p>
                ) : (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {movers.map((m) => {
                      const labels =
                        m.triggers && m.triggers.length > 0
                          ? m.triggers
                          : (m.signals ?? []).map((s) =>
                              s.signal_id === "near_52w_high"
                                ? "Near 52W High"
                                : s.signal_id === "volume_expansion"
                                  ? `${s.observed}x Vol`
                                  : s.signal_id === "one_month_rs_surge"
                                    ? `+${s.observed}pp RS`
                                    : s.label,
                            );
                      const tooltip =
                        m.signals && m.signals.length > 0
                          ? m.signals
                              .map((s) => `${s.label}: ${s.observed}${s.unit}`)
                              .join(" · ")
                          : labels.join(" · ");
                      return (
                        <Link
                          key={m.symbol}
                          href={`/stock?symbol=${encodeURIComponent(m.symbol)}`}
                          className="rounded-token border border-border-subtle bg-surface-sunken px-2.5 py-1 text-xs transition-colors hover:border-accent"
                          title={tooltip || m.symbol}
                        >
                          <span className="font-mono font-semibold text-text-primary">
                            {m.symbol}
                          </span>
                          <span className="ml-1.5 text-[11px] text-text-muted">
                            {labels[0] ?? "mover"}
                          </span>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <Empty>Sector history unavailable.</Empty>
          )}

          <div className="mt-4 flex items-center justify-between border-t border-border-subtle pt-3 text-xs">
            <span className="text-text-muted">
              {selectedSectorKey
                ? `Filtering setups to ${spotlight?.nse_name ?? selectedSectorKey}`
                : "Click a dot on the RRG chart to filter"}
            </span>
            {spotlight ? (
              <button
                type="button"
                onClick={() =>
                  setSelectedSectorKey(selectedSectorKey === spotlight.key ? null : spotlight.key)
                }
                className="font-medium text-accent hover:underline"
              >
                {selectedSectorKey === spotlight.key ? "Show all sectors" : "Filter to sector →"}
              </button>
            ) : null}
          </div>
        </div>
      </section>

      {/* No-Scan Onboarding Hero OR Multi-Facet Filter + Candidate Cards */}
      {!hasScan ? (
        <section className="hero-surface p-8 text-center">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Ready for First Universe Scan
          </p>
          <h2 className="mt-2 text-xl font-semibold text-text-primary">
            Run your first Nifty Total Market 750 Discovery Scan
          </h2>
          <p className="mx-auto mt-2 max-w-lg text-sm text-text-secondary">
            The discovery engine evaluates all four independent strategies, attaches deterministic Entry / Stop / Target plans, and reads business quality across the Nifty 750.
          </p>
          <button
            type="button"
            disabled={stream.running}
            onClick={runScan}
            className="mt-5 rounded-token bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised disabled:opacity-50"
          >
            {stream.running ? "Scanning…" : "Run First Nifty 750 Scan"}
          </button>
        </section>
      ) : (
        <>
          {/* Sticky Multi-Facet Filter & Attribution Bar */}
          <section className="card-surface sticky top-[5.5rem] z-20 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <select
                aria-label="Filter by sector"
                value={selectedSectorKey ?? ""}
                onChange={(e) => setSelectedSectorKey(e.target.value || null)}
                className="rounded-token border border-border-subtle bg-surface-sunken px-2.5 py-1.5 text-xs text-text-primary"
              >
                <option value="">All Sectors</option>
                {sectors.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.nse_name} ({s.quadrant})
                  </option>
                ))}
              </select>

              <select
                aria-label="Filter by strategy"
                value={strategyFilter}
                onChange={(e) => setStrategyFilter(e.target.value)}
                className="rounded-token border border-border-subtle bg-surface-sunken px-2.5 py-1.5 text-xs text-text-primary"
              >
                <option value="">All Strategies</option>
                <option value="minervini">Minervini VCP</option>
                <option value="young_momentum">Young Momentum</option>
                <option value="brahma_vishnu_mahesh">Brahma-Vishnu-Mahesh</option>
                <option value="fun_tech_momentum">Fun-Tech Momentum</option>
              </select>

              <div className="flex items-center gap-1 rounded-token bg-surface-sunken p-1 text-xs">
                {[
                  { val: "", label: "Any Stance" },
                  { val: "BUY", label: "BUY" },
                  { val: "WATCH", label: "WATCH" },
                ].map((opt) => (
                  <button
                    key={opt.label}
                    type="button"
                    onClick={() => setStanceFilter(opt.val)}
                    className={`rounded-token px-2 py-0.5 font-medium ${
                      stanceFilter === opt.val
                        ? "bg-surface-raised text-text-primary shadow-xs"
                        : "text-text-secondary"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-1 rounded-token bg-surface-sunken p-1 text-xs">
                {[
                  { val: null, label: "All BUY counts" },
                  { val: 2, label: "2+ BUY" },
                  { val: 3, label: "3+ BUY" },
                ].map((opt) => (
                  <button
                    key={opt.label}
                    type="button"
                    onClick={() => setMinBuyFilter(opt.val)}
                    className={`rounded-token px-2 py-0.5 font-medium ${
                      minBuyFilter === opt.val
                        ? "bg-surface-raised text-text-primary shadow-xs"
                        : "text-text-secondary"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              <button
                type="button"
                onClick={() => setRoeMin((v) => !v)}
                className={`rounded-token border px-2.5 py-1 text-xs font-medium ${
                  roeMin
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border-subtle bg-surface-sunken text-text-secondary"
                }`}
              >
                ROE ≥ 15%
              </button>

              <button
                type="button"
                onClick={() => setSalesMin((v) => !v)}
                className={`rounded-token border px-2.5 py-1 text-xs font-medium ${
                  salesMin
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border-subtle bg-surface-sunken text-text-secondary"
                }`}
              >
                Sales YoY ≥ 15%
              </button>

              <button
                type="button"
                onClick={() => setLowDebt((v) => !v)}
                className={`rounded-token border px-2.5 py-1 text-xs font-medium ${
                  lowDebt
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border-subtle bg-surface-sunken text-text-secondary"
                }`}
              >
                Low D/E
              </button>

              <button
                type="button"
                onClick={() => setThemeOnly((v) => !v)}
                className={`rounded-token border px-2.5 py-1 text-xs font-medium ${
                  themeOnly
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border-subtle bg-surface-sunken text-text-secondary"
                }`}
              >
                Theme-Backed Only
              </button>
            </div>

            <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-2 text-[11px] text-text-muted">
              <span>
                Ordered by each stock&apos;s highest-conviction named strategy — never blended or averaged.
              </span>
              <span className="tabular-nums font-mono text-text-primary">
                Showing {filteredCandidates.length} of {allCandidates.length} setups
              </span>
            </div>
          </section>

          {/* Interactive Candidate Setup Cards */}
          {filteredCandidates.length === 0 ? (
            <Empty>No setups match the active filters. Loosen stance, quality, or sector criteria.</Empty>
          ) : (
            <section className="grid gap-4 lg:grid-cols-2">
              {filteredCandidates.map((cand) => {
                const activeSid = selectedStrategyMap[cand.symbol] ?? cand.ranked_by;
                const activeVerdict: Verdict | undefined =
                  cand.verdicts.find((v) => v.strategy_id === activeSid) ?? cand.verdicts[0];
                const plan = activeVerdict?.plan ?? null;
                const isWatched = watchedSet.has(cand.symbol);

                return (
                  <article key={cand.symbol} className="card-surface card-interactive flex flex-col justify-between p-5">
                    <div>
                      <header className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Link
                              href={`/stock?symbol=${encodeURIComponent(cand.symbol)}`}
                              className="font-mono text-base font-bold text-text-primary hover:text-accent"
                            >
                              {cand.symbol}
                            </Link>
                            {cand.sector ? (
                              <span className="rounded-token bg-surface-sunken px-2 py-0.5 text-[11px] text-text-secondary">
                                {cand.sector}
                              </span>
                            ) : null}
                            {cand.themes.map((th) => (
                              <Link
                                key={th.key}
                                href={`/themes/${encodeURIComponent(th.key)}`}
                                className="rounded-token border border-accent bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent"
                              >
                                {th.label}
                              </Link>
                            ))}
                          </div>
                          {cand.name ? (
                            <p className="mt-0.5 truncate text-xs text-text-muted">{cand.name}</p>
                          ) : null}
                        </div>

                        <span className="tabular-nums shrink-0 rounded-token border border-border-subtle bg-surface-sunken px-2 py-0.5 font-mono text-[11px] text-text-secondary">
                          Ranked by {STRATEGY_SHORT[cand.ranked_by] ?? cand.ranked_by} ·{" "}
                          {cand.ranked_conviction}/100
                        </span>
                      </header>

                      {/* Side-by-side 4-Strategy Interactive Pills */}
                      <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                        {cand.verdicts.map((v) => {
                          const selected = v.strategy_id === activeVerdict?.strategy_id;
                          return (
                            <button
                              key={v.strategy_id}
                              type="button"
                              onClick={() =>
                                setSelectedStrategyMap((prev) => ({
                                  ...prev,
                                  [cand.symbol]: v.strategy_id,
                                }))
                              }
                              className={`rounded-token border px-2 py-1.5 text-left transition-all ${
                                selected ? "ring-2 ring-accent/40" : ""
                              } ${STANCE_CHIP[v.stance] ?? "border-border-subtle bg-surface-sunken text-text-muted"}`}
                            >
                              <span className="block truncate text-[10px] font-medium opacity-80">
                                {STRATEGY_SHORT[v.strategy_id] ?? v.strategy_id}
                              </span>
                              <span className="tabular-nums font-mono text-xs font-bold">
                                {v.stance} {v.conviction}
                              </span>
                            </button>
                          );
                        })}
                      </div>

                      {/* Selected Strategy Plan Strip */}
                      {plan ? (
                        <div className="mt-3 grid grid-cols-4 gap-2 rounded-token bg-surface-sunken px-3 py-2 text-xs">
                          <div>
                            <span className="block text-[10px] uppercase text-text-muted">
                              Entry
                            </span>
                            <span className="tabular-nums font-mono font-semibold text-text-primary">
                              {money(plan.entry)}
                            </span>
                          </div>
                          <div>
                            <span className="block text-[10px] uppercase text-text-muted">
                              Stop
                            </span>
                            <span className="tabular-nums font-mono font-semibold text-stance-avoid">
                              {money(plan.stop)}
                            </span>
                          </div>
                          <div>
                            <span className="block text-[10px] uppercase text-text-muted">
                              Target
                            </span>
                            <span className="tabular-nums font-mono font-semibold text-stance-buy">
                              {money(plan.target)}
                            </span>
                          </div>
                          <div>
                            <span className="block text-[10px] uppercase text-text-muted">
                              R:R
                            </span>
                            <span className="tabular-nums font-mono font-semibold text-text-primary">
                              {plan.risk_reward ? `${plan.risk_reward}:1` : "—"}
                            </span>
                          </div>
                        </div>
                      ) : (
                        <p className="mt-3 rounded-token bg-surface-sunken px-3 py-2 text-xs text-text-muted">
                          {activeVerdict?.strategy_id}: no active entry plan on {activeVerdict?.stance}.
                        </p>
                      )}

                      {/* Concise Business Quality Facets */}
                      {cand.quality?.facets && cand.quality.facets.length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {cand.quality.facets.slice(0, 4).map((f) => (
                            <span
                              key={f.key}
                              className="tabular-nums rounded-token border border-border-subtle bg-surface-base px-2 py-0.5 font-mono text-[11px] text-text-secondary"
                              title={f.reason ?? undefined}
                            >
                              {f.label}:{" "}
                              {f.status === "not_applicable"
                                ? "N/A"
                                : f.status === "unavailable" || f.value === null
                                  ? "unavail"
                                  : `${f.value}${f.unit}`}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>

                    <footer className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-3">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          disabled={watchBusy === cand.symbol}
                          onClick={() => toggleWatchlist(cand)}
                          className={`rounded-token border px-2.5 py-1 text-xs font-medium transition-colors ${
                            isWatched
                              ? "border-accent bg-accent-soft text-accent"
                              : "border-border-subtle bg-surface-sunken text-text-secondary hover:text-text-primary"
                          }`}
                        >
                          {isWatched ? "✓ Watching" : "+ Watchlist"}
                        </button>

                        <button
                          type="button"
                          onClick={() =>
                            setTicketState({
                              open: true,
                              symbol: cand.symbol,
                              name: cand.name,
                              strategyId: activeVerdict?.strategy_id ?? cand.ranked_by,
                              plan,
                            })
                          }
                          className="rounded-token bg-text-primary px-2.5 py-1 text-xs font-medium text-surface-raised transition-opacity hover:opacity-90"
                        >
                          Preview Paper Buy
                        </button>
                      </div>

                      <Link
                        href={`/stock?symbol=${encodeURIComponent(cand.symbol)}`}
                        className="text-xs font-semibold text-accent hover:underline"
                      >
                        Deep-Dive →
                      </Link>
                    </footer>
                  </article>
                );
              })}
            </section>
          )}
        </>
      )}

      <TradeTicketDrawer
        open={ticketState.open}
        onClose={() => setTicketState((prev) => ({ ...prev, open: false }))}
        symbol={ticketState.symbol}
        companyName={ticketState.name}
        side="BUY"
        defaultBook={
          ticketState.strategyId === "brahma_vishnu_mahesh" ? "longterm" : "swing"
        }
        defaultStrategyId={ticketState.strategyId}
        plan={ticketState.plan}
      />
    </div>
  );
}
