import { useState } from "react";
import { Zap } from "lucide-react";
import { fmtIST, fmtNum, postJSON } from "../api";
import { Panel, StatCard, useApi, Badge, DataTable, EmptyState, Help, toast, Btn, RefreshBtn } from "../components/ui";

export default function NewsAlerts() {
  const [sev, setSev] = useState("");
  const [scope, setScope] = useState("BOTH");
  const alerts = useApi<any[]>(`/api/alerts/feed?scope=${scope}${sev ? `&severity=${sev}` : ""}&hours=168&limit=100`, [sev, scope]);
  const stats = useApi<any>("/api/news/stats");
  const leaderboard = useApi<any>("/api/news/leaderboard?hours=48&scope=universe_with_news");
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (label: string, path: string, after?: () => void) => {
    setBusy(path);
    try { const r = await postJSON(path, {}); toast(`${label}: ${r.message ?? "started"}`); setTimeout(() => after?.(), 2500); }
    catch (e: any) { toast(`${label} failed: ${e.message}`); }
    setBusy(null);
  };

  const lbRows: any[] = Array.isArray(leaderboard.data) ? leaderboard.data : (leaderboard.data?.rows ?? leaderboard.data?.items ?? []);

  return (
    <div className="space-y-6">
      <Help text="News flows in from 7 RSS feeds every 30 minutes and is matched to tickers by company name (common-word tickers like OIL or PERSISTENT only match their full company names — no more crude-oil noise). The LLM then assesses impact on your holdings and watchlist: critical alerts on holdings can recommend a position review and go to Telegram." />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Articles Stored" value={stats.data?.total ?? 0} sub={`${stats.data?.last_24h ?? 0} in last 24h`} />
        <StatCard label="Ticker-Tagged" value={stats.data?.tagged ?? 0} sub="Matched to at least one stock" />
        <StatCard label="Latest Article" value={<span className="text-sm">{fmtIST(stats.data?.latest)}</span>} />
        <div className="glass-panel rounded-2xl p-4 flex flex-col gap-2 justify-center">
          <Btn kind="primary" busy={busy === "/api/news/scrape"} onClick={() => run("Scrape", "/api/news/scrape", stats.reload)}><Zap size={11} /> Scrape News Now</Btn>
          <Btn busy={busy === "/api/alerts/run"} onClick={() => run("Impact pass", "/api/alerts/run", alerts.reload)}>Run LLM Impact Pass</Btn>
          <Btn busy={busy === "/api/news/retag"} onClick={() => run("Retag", "/api/news/retag", stats.reload)} title="Re-run ticker matching on stored articles — use after the matcher rules change">Retag Old Articles</Btn>
        </div>
      </div>

      <Panel title="Impact Alerts" subtitle="LLM-triaged news clusters per stock. Severity: critical = thesis-relevant now, watch = monitor, info = context. REVIEW_EXIT on a holding means: read it today."
        actions={
          <div className="flex items-center gap-2">
            <select value={sev} onChange={(e) => setSev(e.target.value)}
              className="bg-slate-900/70 border border-slate-700/60 rounded-lg px-2 py-1.5 text-xs text-slate-300 outline-none">
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="watch">Watch</option>
              <option value="info">Info</option>
            </select>
            <select value={scope} onChange={(e) => setScope(e.target.value)}
              className="bg-slate-900/70 border border-slate-700/60 rounded-lg px-2 py-1.5 text-xs text-slate-300 outline-none">
              <option value="BOTH">Holdings + Watchlist</option>
              <option value="HOLDING">Holdings only</option>
              <option value="LT_WATCH">Watchlist only</option>
            </select>
            <RefreshBtn onClick={alerts.reload} loading={alerts.loading} />
          </div>
        }>
        <div className="space-y-2 max-h-[440px] overflow-auto pr-1">
          {(alerts.data ?? []).length === 0
            ? <EmptyState>No alerts in the last 7 days. Scrape news, then run the LLM Impact Pass — alerts appear for stocks you hold or watch when relevant news clusters form.</EmptyState>
            : (alerts.data ?? []).map((a: any) => (
              <div key={a.id} className="bg-slate-900/50 border border-slate-800/70 rounded-xl p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-bold text-slate-100 text-sm">{a.ticker}</span>
                  <Badge text={a.severity} />
                  <Badge text={a.recommended_action} />
                  <Badge text={a.scope} tone="INFO" />
                  <span className="text-[10px] text-slate-500">{a.linkage}{a.linkage_sector ? ` · ${a.linkage_sector}` : ""}</span>
                  <span className="flex-1" />
                  <span className="text-[10px] text-slate-600">{a.created_at_ist ?? fmtIST(a.created_at)}</span>
                </div>
                <p className="text-[11px] text-slate-300 mt-2 mb-0 leading-relaxed">{a.impact_summary}</p>
                {(a.reasons ?? []).length > 0 && (
                  <ul className="text-[10px] text-slate-500 mt-1 mb-0 pl-4">
                    {(a.reasons ?? []).slice(0, 4).map((x: string, i: number) => <li key={i}>{x}</li>)}
                  </ul>
                )}
              </div>
            ))}
        </div>
      </Panel>

      <Panel title="Sentiment Leaderboard (48h)" subtitle="Time-decayed news sentiment per stock — fresh headlines outweigh stale ones"
        actions={<RefreshBtn onClick={leaderboard.reload} loading={leaderboard.loading} />}>
        <DataTable
          rows={lbRows}
          searchKeys={["ticker", "sector"]}
          defaultSort={{ key: "sentiment", dir: "desc" }}
          maxHeight="340px"
          empty={<EmptyState>No tagged news in the window yet — scrape news first.</EmptyState>}
          cols={[
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "sector", label: "Sector" },
            { key: "n", label: "Articles", align: "right", render: (r) => r.n ?? r.count ?? "—" },
            {
              key: "sentiment", label: "Sentiment", align: "right",
              sortValue: (r) => r.sentiment ?? r.avg_sentiment ?? 0,
              render: (r) => {
                const v = r.sentiment ?? r.avg_sentiment;
                return <span className={v > 0.1 ? "text-emerald-400" : v < -0.1 ? "text-rose-400" : "text-slate-400"}>{fmtNum(v, 2)}</span>;
              },
            },
            { key: "latest_title", label: "Latest Headline", render: (r) => <span className="text-[10px] text-slate-500 whitespace-normal">{r.latest_title ?? r.title ?? "—"}</span> },
          ]}
        />
      </Panel>
    </div>
  );
}
