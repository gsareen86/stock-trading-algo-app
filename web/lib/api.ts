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
async function getJson<T>(path: string): Promise<Fetched<T>> {
  // Relative on the client; absolute on the server, where `fetch` has no origin to resolve
  // against. Both land on the same proxy route.
  const base = typeof window === "undefined"
    ? `${process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"}${API_BASE_URL}`
    : API_BASE_URL;
  const url = `${base}${path}`;
  try {
    const response = await fetch(url, { cache: "no-store" });
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
