/**
 * Backend client.
 *
 * The browser is not a database client here — everything reaches it through this API,
 * which holds the service-role credential server-side. Nothing in this file should ever
 * gain a Supabase key.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  spend_usd: number;
  total_tokens: number;
};

export type Usage = {
  days: number;
  totals: Bucket;
  by_day: Record<string, Bucket>;
  by_task: Record<string, Bucket>;
  by_provider: Record<string, Bucket>;
  budget: {
    cap_usd: number | null;
    spent_today_usd: number;
    remaining_usd: number | null;
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
  cost_usd: number | null;
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
  const url = `${API_BASE_URL}${path}`;
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      return { ok: false, error: `HTTP ${response.status}`, attemptedUrl: url };
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
