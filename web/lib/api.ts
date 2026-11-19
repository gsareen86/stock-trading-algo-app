/**
 * Backend client.
 *
 * The browser is not a database client here — everything reaches it through this API,
 * which holds the service-role credential server-side. Nothing in this file should ever
 * gain a Supabase key.
 */

/**
 * Everything goes through the Next.js proxy, never straight to the backend.
 *
 * The proxy attaches the access token from an httpOnly cookie, so no token is ever handled by
 * page code — and the browser never needs a cross-origin credential. `BACKEND_URL` (server
 * only) is where the proxy forwards to.
 */
export const API_BASE_URL = "/api/backend";

export type ProviderStatus = {
  name: string;
  configured: boolean;
  /** null when no probe was requested — reachability costs a round trip. */
  reachable: boolean | null;
  detail: string | null;
};

export type Health = {
  status: "ok" | "degraded";
  app: { version: string; env: string };
  database: {
    connected: boolean;
    migrations_current: boolean | null;
    current_revision: string | null;
    head_revision: string | null;
    reason: string | null;
  };
  llm: {
    providers: ProviderStatus[];
    any_configured: boolean;
    default_model: string;
    /** Whether the default model's own provider is configured — i.e. whether a task
     *  without an explicit route could actually run. */
    default_model_usable: boolean;
    routes: Record<string, string>;
  };
  observability: { provider: string; configured: boolean };
};

export type Bucket = {
  calls: number;
  priced_calls: number;
  /** Calls whose provider reported no cost — local models. Free, not missing. */
  unpriced_calls: number;
  failed_calls: number;
  spend_inr: number;
  total_tokens: number;
};

export type Usage = {
  days: number;
  totals: Bucket;
  by_day: Record<string, Bucket>;
  by_task: Record<string, Bucket>;
  by_provider: Record<string, Bucket>;
  /** Rate every INR figure below was converted at. Vendors bill in USD. */
  usd_inr_rate: number;
  budget: {
    cap_inr: number | null;
    spent_today_inr: number;
    remaining_inr: number | null;
    exhausted: boolean;
  };
};

export type CallRecord = {
  id: number;
  created_at: string;
  task: string;
  provider: string;
  model: string;
  requested_model: string;
  used_fallback: boolean;
  status: string;
  total_tokens: number | null;
  /** What the vendor bills, unconverted — the auditable amount. Null for local models. */
  cost_usd: number | null;
  /** The same amount in rupees, for display. Null when unpriced — never 0. */
  cost_inr: number | null;
  latency_ms: number | null;
  trace_id: string | null;
  error_msg: string | null;
};

export type Fetched<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; attemptedUrl: string };

export type HealthResult =
  | { ok: true; health: Health }
  | { ok: false; error: string; attemptedUrl: string };

/**
 * Fetch JSON from the backend without throwing.
 *
 * An unreachable backend is a state the surfaces render, not an error that blanks the
 * page — a broken seam should be visible, not fatal.
 */

/**
 * Where a request goes, and what it carries.
 *
 * On the **server** it goes straight to the backend with the access token read from the
 * cookie. Routing a server component through this app's own HTTP proxy would be a round trip
 * to itself — and worse, `fetch` on the server does not forward the incoming request's
 * cookies, so the proxy would see no session at all. That was a real bug: every surface
 * rendered as signed-out while the same URL worked from a terminal.
 *
 * On the **client** it goes to the proxy with a relative URL, and the browser attaches the
 * cookie. No token is ever visible to page script either way.
 */
async function resolve(path: string): Promise<{ url: string; headers: HeadersInit }> {
  if (typeof window !== "undefined") {
    return { url: `${API_BASE_URL}${path}`, headers: {} };
  }
  const { cookies } = await import("next/headers");
  const token = (await cookies()).get("sw_access")?.value;
  const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  return {
    url: `${backend}${path}`,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  };
}

async function getJson<T>(path: string): Promise<Fetched<T>> {
  const { url, headers } = await resolve(path);
  try {
    const response = await fetch(url, { cache: "no-store", headers });
    if (!response.ok) {
      const label = response.status === 401 ? "not signed in" : `HTTP ${response.status}`;
      return { ok: false, error: label, attemptedUrl: url };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, error: message, attemptedUrl: url };
  }
}

export function fetchUsage(days = 7): Promise<Fetched<Usage>> {
  return getJson<Usage>(`/llm/usage?days=${days}`);
}

export function fetchCalls(limit = 20): Promise<Fetched<{ calls: CallRecord[] }>> {
  return getJson<{ calls: CallRecord[] }>(`/llm/calls?limit=${limit}`);
}

/**
 * Fetch backend status.
 *
 * Never throws: an unreachable backend is a state the Today surface renders, not an
 * error that blanks the page. A broken seam should be visible, not fatal.
 */
export async function fetchHealth(): Promise<HealthResult> {
  const result = await getJson<Health>("/health");
  return result.ok ? { ok: true, health: result.data } : result;
}

// ── verdicts, positions, insights, health ─────────────────────────────────────
export type Evidence = {
  id: string;
  label: string;
  value: number | string | null;
  operator: string;
  threshold: number | string | null;
  passed: boolean | null;
  unit: string | null;
  source_ref: string;
};

export type Gate = {
  id: string;
  label: string;
  passed: boolean;
  reason: string;
  evidence_ids: string[];
};

export type Plan = {
  entry: number;
  stop: number;
  target: number;
  risk_reward: number | null;
  entry_kind: "pivot" | "breakout" | "pullback" | "close" | string;
  valid_until?: string | null;
  note?: string | null;
  horizon?: string | null;
};

export type Verdict = {
  strategy_id: string;
  ticker: string;
  as_of: string;
  stance: "BUY" | "WATCH" | "AVOID";
  /** Scoped to its own strategy. Never comparable to another strategy's. */
  conviction: number;
  gates_passed: boolean;
  gates: Gate[];
  evidence: Evidence[];
  plan?: Plan | null;
  plan_note?: string | null;
  narrative: string | null;
  trace_id: string | null;
};

export type Position = {
  book: string;
  ticker: string;
  quantity: number;
  average_cost: number;
  cost_basis: number;
  is_open: boolean;
  last_price: number | null;
  market_value: number | null;
  realised_pnl_gross: number;
  unrealised_pnl_gross: number | null;
  unrealised_pct: number | null;
  trade_count: number;
};

export type Insight = {
  id: number;
  kind: string;
  severity: "high" | "medium" | "low";
  ticker: string | null;
  title: string;
  body: string | null;
  payload: Record<string, unknown>;
  read: boolean;
  created_at: string | null;
  /** When the figures above were last established — distinct from when this was first
   *  raised. A number in the feed means nothing without knowing when it was checked. */
  measured_at: string | null;
  /** Set once the observation stopped being true. Absent from the default feed. */
  withdrawn_at: string | null;
  withdrawal_reason: string | null;
  actions: string[];
};

export type HealthComponent = {
  id: string;
  label: string;
  score: number;
  weight: number;
  measurement: number;
  threshold: number;
  unit: string;
  detail: string;
  healthy: boolean;
};

export type BookHealth = {
  score: number;
  band: string;
  components: HealthComponent[];
  guidance: { component: string; action: string; detail: string; ticker: string | null }[];
  book: string;
  capital_inr: number;
  charges_included: boolean;
};

export type BookAnalytics = {
  book: string;
  open_positions: number;
  cost_basis: number;
  market_value: number | null;
  realised_pnl_gross: number;
  unrealised_pnl_gross: number | null;
  concentration_pct: Record<string, number>;
  trade_count: number;
  charges_included: boolean;
  closed_trades: {
    closed: number;
    wins: number;
    losses: number;
    win_rate_pct: number | null;
  };
  attribution: Record<string, { trades: number; bought: number; sold: number }>;
};

export function fetchInsights(limit = 30): Promise<Fetched<{ insights: Insight[]; unread: number }>> {
  return getJson(`/insights?limit=${limit}`);
}

export function fetchPositions(book: string): Promise<Fetched<{ positions: Position[]; count: number }>> {
  return getJson(`/books/${book}/positions`);
}

export function fetchBookHealth(book: string): Promise<Fetched<BookHealth>> {
  return getJson(`/books/${book}/health`);
}

export function fetchAnalytics(book: string): Promise<Fetched<BookAnalytics>> {
  return getJson(`/books/${book}/analytics`);
}

export function fetchStrategies(): Promise<Fetched<{ strategies: { id: string; name: string }[] }>> {
  return getJson("/strategies");
}

/** Verdicts are evaluated on demand — this is a POST, so it does not use `getJson`. */
export async function evaluate(
  symbols: string[],
  narrate = false,
): Promise<Fetched<{ verdicts: Verdict[]; count: number }>> {
  const { url, headers } = await resolve("/verdicts/evaluate");
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({ symbols, narrate }),
      cache: "no-store",
    });
    if (!response.ok) {
      const label = response.status === 401 ? "not signed in" : `HTTP ${response.status}`;
      return { ok: false, error: label, attemptedUrl: url };
    }
    return { ok: true, data: await response.json() };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, error: message, attemptedUrl: url };
  }
}

export type BrokerStatus = {
  connected: boolean;
  authorised: boolean;
  url: string;
  session_id: string | null;
  connected_at: string | null;
  last_ok_at: string | null;
  refresh_minutes: number;
  cached: string[];
  last_error: string | null;
  read_only: boolean;
  next_step?: string;
};

export type BrokerHoldings = {
  count: number;
  invested: number;
  market_value: number | null;
  holdings: {
    symbol: string;
    quantity: number;
    average_price: number;
    last_price: number | null;
    value: number | null;
    pnl_reported_by_broker: number | null;
  }[];
  note: string;
};

export function fetchBrokerStatus(): Promise<Fetched<BrokerStatus>> {
  return getJson<BrokerStatus>("/broker/status");
}

export function fetchBrokerHoldings(): Promise<Fetched<BrokerHoldings>> {
  return getJson<BrokerHoldings>("/broker/holdings");
}

export type Theme = {
  key: string;
  label: string;
  /** Distinct companies referencing this. The counts are the claim, not a derived display. */
  breadth: number;
  /** Distinct periods it has persisted across. */
  persistence: number;
  sector_count: number;
  source_kinds: string[];
  first_seen_at: string | null;
  measured_at: string | null;
  withdrawn_at: string | null;
  withdrawal_reason: string | null;
};

export type ThemeRun = {
  id: number;
  trigger: string;
  /** `complete`, `failed`, `running`, or `no_reading` when every source was unavailable —
   *  which is emphatically not the same as finding no themes. */
  outcome: string;
  sources_unavailable: string[];
  documents_read: number;
  reason: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type ChainLink = {
  id: number;
  tier: number;
  label: string;
  supplies: string | null;
  reasoning: string;
  /** The model that proposed this link. Attribution is what stops it reading as a
   *  measurement the platform made. */
  proposed_by: string;
  supplier_descriptions: string[];
  rejected: boolean;
  rejected_reason: string | null;
  measured_by_platform: boolean;
};

export type ThemeCandidate = {
  id: number;
  tier: number;
  symbol: string;
  /** A named grade, never a number — a number would be sortable. */
  exposure: "established" | "claimed" | "unestablished";
  exposure_basis: string | null;
  matched_description: string | null;
};

export type ThemeDetail = Theme & {
  chain: ChainLink[];
  candidates: ThemeCandidate[];
  references: {
    symbol: string;
    period: string;
    kind: string;
    source_ref: string;
    excerpt: string | null;
    measured_by_platform: boolean;
  }[];
};

export function fetchThemes(): Promise<
  Fetched<{ themes: Theme[]; count: number; latest_run: ThemeRun | null }>
> {
  return getJson("/themes");
}

export function fetchTheme(key: string): Promise<Fetched<ThemeDetail>> {
  return getJson(`/themes/${encodeURIComponent(key)}`);
}

// ── Daily-driver types: briefing, discovery, RRG, quality, watchlist, stocks ──

export type Trade = {
  id: number;
  book: string;
  ticker: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  gross_amount: number;
  strategy_id: string | null;
  source: string;
  note: string | null;
  executed_at: string;
};

export function fetchTrades(book: string, limit = 100): Promise<Fetched<{ trades: Trade[]; count: number }>> {
  return getJson(`/books/${book}/trades?limit=${limit}`);
}

export type TrailPoint = {
  as_of: string;
  rs_ratio: number;
  rs_momentum: number;
  quadrant: string;
};

export type SectorPlacement = {
  key: string;
  nse_name: string;
  ticker: string;
  benchmark: string;
  quadrant: "Leading" | "Weakening" | "Improving" | "Lagging" | "unplaced" | string;
  rs_pct: number | null;
  rs_momentum_pp: number | null;
  rs_ratio: number | null;
  rs_momentum: number | null;
  window_bars?: number;
  trail?: TrailPoint[];
  reason?: string | null;
};

export type MoverSignal = {
  signal_id: string;
  label: string;
  observed: number;
  threshold: number;
  unit: string;
};

export type NotableMover = {
  symbol: string;
  name: string | null;
  sector?: string | null;
  sector_key?: string;
  close?: number | null;
  last_close?: number;
  signals?: MoverSignal[];
  triggers?: string[];
  rs_20d_pct?: number | null;
  volume_ratio?: number | null;
  pct_from_52w_high?: number | null;
};

export type QualityFacet = {
  key: string;
  label: string;
  status: "pass" | "watch" | "fail" | "not_applicable" | "unavailable" | string;
  value: number | null;
  threshold: string | number | null;
  unit: string;
  source?: string | null;
  reason?: string | null;
};

export type QualityReport = {
  symbol: string;
  sector_key: string | null;
  source: string;
  unavailable_reason: string | null;
  facets: QualityFacet[];
  summary: Record<string, number | string | null>;
};

export type ScanRunSummary = {
  id: number;
  trigger: string;
  universe_origin: string;
  index_name: string;
  benchmark: string;
  outcome: string;
  considered_count: number;
  eligible_count: number;
  unevaluable_count: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type CandidateThemeBadge = {
  key: string;
  label: string;
  exposure?: string | null;
};

export type DiscoveryCandidate = {
  symbol: string;
  name: string | null;
  sector: string | null;
  sector_key: string | null;
  universe_index: number;
  ranked_by: string;
  ranked_conviction: number;
  ranked_stance: "BUY" | "WATCH" | "AVOID" | string;
  buy_count: number;
  verdicts: Verdict[];
  quality: QualityReport;
  themes: CandidateThemeBadge[];
};

export type LatestDiscoveryResponse = {
  run: ScanRunSummary | null;
  sectors: SectorPlacement[];
  candidates: DiscoveryCandidate[];
  total_candidates: number;
  filtered_candidates: number;
  unevaluable: { symbol: string; reason: string }[];
  rank_policy: string;
};

export type IndexSnapshot = {
  symbol: string;
  label: string;
  available: boolean;
  close?: number;
  change_pct?: number;
  above_50dma?: boolean;
  above_200dma?: boolean | null;
  posture?: "constructive" | "cautious" | "risk_off" | string;
};

export type MorningBriefing = {
  market: {
    session: string;
    ist_timestamp: string;
    ist_time_label: string;
    nifty50: IndexSnapshot;
    nifty500: IndexSnapshot;
  };
  scan_status: {
    has_scan: boolean;
    run_id?: number;
    finished_at?: string | null;
    stale: boolean;
    stale_reason?: string | null;
    considered_count?: number;
    eligible_count?: number;
  };
  sectors_summary: {
    leading_count: number;
    improving_count: number;
    top_leading: SectorPlacement[];
    top_improving: SectorPlacement[];
    shifts: { sector_key: string; nse_name: string; from_quadrant: string; to_quadrant: string }[];
  };
  watchlist_pulse: {
    total_watched: number;
    flipped_buy_count: number;
    near_pivot_count: number;
    items: {
      symbol: string;
      book_intent: string;
      strategy_id: string | null;
      last_price: number | null;
      entry: number | null;
      stop: number | null;
      distance_pct: number;
      flipped_buy: boolean;
    }[];
  };
  books: {
    swing_open: number;
    longterm_open: number;
    total_open: number;
    swing_cost_basis: number;
    longterm_cost_basis: number;
  };
  top_themes: Theme[];
  unread_insights: number;
};

export type WatchlistItem = {
  id: number;
  symbol: string;
  name: string | null;
  sector: string | null;
  sector_key: string | null;
  book_intent: "swing" | "longterm";
  target_strategy_id: string | null;
  notes: string | null;
  added_price: number | null;
  last_price: number | null;
  distance_to_entry_pct: number | null;
  last_known_stances: Record<string, string>;
  current_stances: Record<string, string>;
  flipped_buy: boolean;
  flipped_strategies: string[];
  plan: Plan | null;
  verdicts: Verdict[];
  themes: CandidateThemeBadge[];
  created_at: string;
  updated_at: string;
};

export type UniverseSymbol = {
  symbol: string;
  name: string;
  sector: string | null;
  sector_key: string | null;
};

export type StockChartBar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema20: number | null;
  sma50: number | null;
  sma150: number | null;
  sma200: number | null;
};

export type StockChartResponse = {
  symbol: string;
  range: string;
  available: boolean;
  reason?: string | null;
  last_price: number | null;
  prev_close: number | null;
  change_pct: number | null;
  bars: StockChartBar[];
};

export type StockQualityResponse = QualityReport & {
  company_name: string;
  sector: string | null;
  industry: string | null;
  description: string | null;
  shareholding: {
    as_of: string;
    promoter_pct: number | null;
    fii_pct: number | null;
    dii_pct: number | null;
    pledge_pct: number | null;
    source: string;
  } | null;
  statements: Record<string, { period: string; value: number }[]>;
};

export type StockResearchResponse = {
  symbol: string;
  themes: {
    theme_key: string;
    label: string;
    tier: number;
    matched_description: string | null;
    exposure: string;
    exposure_basis: string | null;
    breadth: number;
  }[];
  concepts: {
    concept: string;
    period: string;
    kind: string;
    source_ref: string;
    excerpt: string | null;
    extracted_by: string;
  }[];
  filings: {
    available: boolean;
    items: {
      headline?: string;
      title?: string;
      filed_at?: string;
      category?: string;
      source_ref?: string;
      url?: string;
    }[];
  };
  news: {
    available: boolean;
    items: {
      headline?: string;
      title?: string;
      published_at?: string;
      source?: string;
      url?: string;
      source_ref?: string;
    }[];
  };
  concall_digest: {
    section?: string;
    summary?: string;
    quotes?: string[];
  }[];
};

export function fetchBriefing(): Promise<Fetched<MorningBriefing>> {
  return getJson<MorningBriefing>("/insights/briefing");
}

export function fetchDiscoverySectors(
  benchmark = "^CRSLDX",
): Promise<Fetched<{ benchmark: string; source_mode: string; sectors: SectorPlacement[]; count: number }>> {
  return getJson(`/discovery/sectors?benchmark=${encodeURIComponent(benchmark)}`);
}

export function fetchLatestDiscovery(params?: {
  sector?: string;
  strategy_id?: string;
  stance?: string;
  min_buy_count?: number;
  roe_min?: number;
  sales_yoy_min?: number;
  low_debt?: boolean;
  theme_backed?: boolean;
  limit?: number;
}): Promise<Fetched<LatestDiscoveryResponse>> {
  const qs = new URLSearchParams();
  if (params?.sector) qs.set("sector", params.sector);
  if (params?.strategy_id) qs.set("strategy_id", params.strategy_id);
  if (params?.stance) qs.set("stance", params.stance);
  if (params?.min_buy_count) qs.set("min_buy_count", String(params.min_buy_count));
  if (params?.roe_min !== undefined) qs.set("roe_min", String(params.roe_min));
  if (params?.sales_yoy_min !== undefined) qs.set("sales_yoy_min", String(params.sales_yoy_min));
  if (params?.low_debt) qs.set("low_debt", "true");
  if (params?.theme_backed) qs.set("theme_backed", "true");
  if (params?.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return getJson<LatestDiscoveryResponse>(`/discovery/runs/latest${suffix}`);
}

export function fetchDiscoveryRuns(
  limit = 10,
): Promise<Fetched<{ runs: ScanRunSummary[]; count: number }>> {
  return getJson(`/discovery/runs?limit=${limit}`);
}

export function fetchWatchlist(
  bookIntent?: string,
): Promise<Fetched<{ items: WatchlistItem[]; count: number }>> {
  const suffix = bookIntent ? `?book_intent=${encodeURIComponent(bookIntent)}` : "";
  return getJson(`/watchlist${suffix}`);
}

export function fetchStockChart(
  symbol: string,
  range: "3M" | "6M" | "1Y" | "3Y" = "1Y",
): Promise<Fetched<StockChartResponse>> {
  return getJson(`/stocks/${encodeURIComponent(symbol)}/chart?range=${range}`);
}

export function fetchStockQuality(symbol: string): Promise<Fetched<StockQualityResponse>> {
  return getJson(`/stocks/${encodeURIComponent(symbol)}/quality`);
}

export function fetchStockResearch(
  symbol: string,
  summarize = false,
): Promise<Fetched<StockResearchResponse>> {
  return getJson(
    `/stocks/${encodeURIComponent(symbol)}/research${summarize ? "?summarize=true" : ""}`,
  );
}

export function fetchUniverseSymbols(
  q?: string,
  limit = 750,
): Promise<Fetched<{ symbols: UniverseSymbol[]; count: number; total_universe: number }>> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (q) qs.set("q", q);
  return getJson(`/universe/symbols?${qs.toString()}`);
}

export type ToolInfo = {
  name: string;
  version: string;
  summary: string;
  tags: string[];
};

export function fetchTools(): Promise<
  Fetched<{ tools: ToolInfo[]; count: number; load_failures: { module: string; error: string }[] }>
> {
  return getJson("/tools");
}

export function fetchThemeRuns(
  limit = 10,
): Promise<Fetched<{ runs: ThemeRun[]; count: number }>> {
  return getJson(`/themes/runs?limit=${limit}`);
}

export function fetchMovers(
  sector: string,
  benchmark = "^CRSLDX",
): Promise<
  Fetched<{
    sector: string;
    benchmark: string;
    checked_instruments: number;
    movers: NotableMover[];
    count: number;
  }>
> {
  return getJson(
    `/discovery/movers?sector=${encodeURIComponent(sector)}&benchmark=${encodeURIComponent(benchmark)}`,
  );
}
