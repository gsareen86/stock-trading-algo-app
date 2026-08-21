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
