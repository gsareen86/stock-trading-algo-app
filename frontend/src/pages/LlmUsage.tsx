import { ComposedChart, Area, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { fmtIST, fmtNum } from "../api";
import { Panel, StatCard, useApi, Badge, DataTable, EmptyState, Help, RefreshBtn } from "../components/ui";

export default function LlmUsage() {
  const totals = useApi<any>("/api/llm/observability/totals");
  const models = useApi<any[]>("/api/llm/observability/models");
  const daily = useApi<any[]>("/api/llm/observability/daily");
  const callers = useApi<any[]>("/api/llm/observability/callers");
  const calls = useApi<any[]>("/api/llm/observability/calls?limit=100");

  const t = totals.data;
  const reloadAll = () => { totals.reload(); models.reload(); daily.reload(); callers.reload(); calls.reload(); };

  return (
    <div className="space-y-6">
      <Help text="Every LLM call the system makes is logged here live: which provider and exact model, how many tokens, how long it took, and whether it hit the cache. Use 'Usage by Model' to verify cheap models handle the high-frequency work (sentiment, veto, tagging) while strong models do the low-frequency research." />

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard label="Active Provider / Model" tone="accent"
          value={<span className="capitalize text-base">{t?.provider ?? "—"}</span>}
          sub={<span className="font-mono">{t?.model ?? ""}</span>} />
        <StatCard label="Calls Today (IST)" value={t?.calls_today ?? 0}
          sub={`${t?.ok_today ?? 0} ok · ${t?.cached_today ?? 0} cached · ${t?.errors_today ?? 0} failed`} />
        <StatCard label="Tokens Today (IST)" value={(t?.tokens_today ?? 0).toLocaleString()}
          sub={`${(t?.prompt_tokens_today ?? 0).toLocaleString()} prompt / ${(t?.completion_tokens_today ?? 0).toLocaleString()} completion`} />
        <StatCard label="Est. Cost Today" value={`$${(t?.est_cost_today_usd ?? 0).toFixed(4)}`}
          tone={(t?.est_cost_today_usd ?? 0) > 0 ? "bad" : "good"}
          sub={t?.provider === "ollama" ? "Local model — always $0" : (t?.pricing_incomplete ? "some models lack pricing — add to LLM_PRICING in config.py" : "from per-model rates in config.py")} />
        <StatCard label="All-Time Totals" value={(t?.calls_total ?? 0).toLocaleString()}
          sub={`calls · ${(t?.tokens_total ?? 0).toLocaleString()} tokens · est. $${(t?.est_cost_total_usd ?? 0).toFixed(2)}`} />
        <StatCard label="Success Rate" value={`${t?.success_rate_pct ?? 100}%`}
          tone={(t?.success_rate_pct ?? 100) >= 90 ? "good" : "bad"} sub="API calls only — cache hits excluded" />
      </div>

      <Panel title="Usage by Model — Last 7 Days" subtitle="Exact provider + model id per call"
        actions={<RefreshBtn onClick={reloadAll} loading={models.loading} />}>
        <DataTable
          rows={models.data ?? []}
          empty={<EmptyState>No LLM calls recorded yet — rows appear the moment any LLM feature (sentiment, veto, research, news-impact, guidance) runs.</EmptyState>}
          cols={[
            { key: "provider", label: "Provider", render: (r) => <span className="capitalize font-semibold text-slate-100">{r.provider}</span> },
            { key: "model", label: "Model", render: (r) => <span className="text-indigo-300">{r.model}</span> },
            { key: "calls", label: "Calls", align: "right" },
            { key: "ok", label: "OK", align: "right", render: (r) => <span className="text-emerald-400">{r.ok}</span> },
            { key: "cached", label: "Cached", align: "right" },
            { key: "errors", label: "Failed", align: "right", render: (r) => <span className={r.errors > 0 ? "text-rose-400" : "text-slate-600"}>{r.errors}</span> },
            { key: "prompt_tokens", label: "Prompt Tok", align: "right", render: (r) => (r.prompt_tokens ?? 0).toLocaleString() },
            { key: "completion_tokens", label: "Compl Tok", align: "right", render: (r) => (r.completion_tokens ?? 0).toLocaleString() },
            { key: "total_tokens", label: "Total Tok", align: "right", render: (r) => <b>{(r.total_tokens ?? 0).toLocaleString()}</b> },
            { key: "avg_latency_ms", label: "Avg Latency", align: "right", render: (r) => r.avg_latency_ms ? `${Math.round(r.avg_latency_ms)} ms` : "—" },
            {
              key: "est_cost_usd", label: "Est. Cost", align: "right",
              render: (r) => r.est_cost_usd == null
                ? <span className="text-amber-400/70" title="No pricing for this model — add a row to LLM_PRICING_USD_PER_MTOK in config.py">unknown</span>
                : <span className={r.est_cost_usd > 0 ? "text-rose-300" : "text-emerald-400"}>${"" + r.est_cost_usd.toFixed(4)}</span>,
            },
            { key: "last_used", label: "Last Used", render: (r) => fmtIST(r.last_used) },
          ]}
        />
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Panel title="7-Day Tokens & Calls" className="lg:col-span-2">
          <div className="h-60 text-[10px] font-mono">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={daily.data ?? []} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <defs>
                  <linearGradient id="llmTok" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                <XAxis dataKey="date" stroke="#475569" />
                <YAxis yAxisId="tok" stroke="#6366f1" />
                <YAxis yAxisId="calls" orientation="right" stroke="#10b981" />
                <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                <Area yAxisId="tok" type="monotone" dataKey="tokens" name="Tokens" stroke="#6366f1" fill="url(#llmTok)" />
                <Line yAxisId="calls" type="monotone" dataKey="calls" name="Calls" stroke="#10b981" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel title="Today's Token Share by Feature">
          <div className="h-60 text-[10px] font-mono">
            {(callers.data ?? []).length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-500 text-xs">No calls today yet</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={callers.data ?? []} layout="vertical" margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                  <XAxis type="number" stroke="#475569" />
                  <YAxis dataKey="caller" type="category" stroke="#475569" width={110} />
                  <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                  <Bar dataKey="pct" name="Token Share %" fill="#6366f1" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>
      </div>

      <Panel title="Recent LLM Calls" subtitle="Latest 100, newest first"
        actions={<RefreshBtn onClick={calls.reload} loading={calls.loading} />}>
        <DataTable
          rows={calls.data ?? []}
          searchKeys={["caller", "model", "status", "provider"]}
          maxHeight="340px"
          empty={<EmptyState>No calls logged yet.</EmptyState>}
          cols={[
            { key: "ts", label: "Time", render: (r) => fmtIST(r.ts) },
            { key: "caller", label: "Feature", render: (r) => <span className="font-semibold text-slate-100">{r.caller || "—"}</span> },
            { key: "model", label: "Provider / Model", render: (r) => <span><span className="capitalize">{r.provider}</span><span className="text-slate-600"> / </span><span className="text-indigo-300">{r.model}</span></span> },
            { key: "total_tokens", label: "Tokens (P+C)", align: "right", render: (r) => r.total_tokens != null ? `${r.total_tokens.toLocaleString()} (${r.prompt_tokens ?? 0}+${r.completion_tokens ?? 0})` : "—" },
            { key: "latency_ms", label: "Latency", align: "right", render: (r) => r.latency_ms ? `${r.latency_ms} ms` : "—" },
            { key: "status", label: "Status", render: (r) => <Badge text={r.status} /> },
            { key: "error_msg", label: "Error", render: (r) => <span className="text-rose-400/80 text-[10px] max-w-[200px] truncate inline-block" title={r.error_msg ?? ""}>{r.error_msg ?? ""}</span> },
          ]}
        />
      </Panel>
      <div className="text-[10px] text-slate-600">{fmtNum(0, 0) /* keep import used */ && null}</div>
    </div>
  );
}
