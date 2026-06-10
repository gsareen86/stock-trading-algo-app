import { useState } from "react";
import { Zap, ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { fmtIST, fmtNum, getJSON, postJSON } from "../api";
import { Panel, StatCard, useApi, Badge, EmptyState, Help, toast, Btn, RefreshBtn, SearchBox } from "../components/ui";

function sentClass(v: number | null | undefined) {
  if (v === null || v === undefined) return "text-slate-500";
  return v > 0.1 ? "text-emerald-400" : v < -0.1 ? "text-rose-400" : "text-slate-400";
}

/* Leaderboard row — expands to the actual tagged articles with source links */
function LeaderRow({ r }: { r: any }) {
  const [open, setOpen] = useState(false);
  const [articles, setArticles] = useState<any[] | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && articles === null) {
      setLoading(true);
      try { setArticles(await getJSON(`/api/news/ticker/${r.ticker}?hours=48&limit=12`)); }
      catch { setArticles([]); }
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-900/50 border border-slate-800/70 rounded-xl">
      <button onClick={toggle} className="w-full grid grid-cols-12 items-center gap-2 px-3 py-2 text-left text-xs font-mono">
        <span className="col-span-2 font-bold text-slate-100 flex items-center gap-1.5">
          {r.ticker}
          {r.is_open_position && <Badge text="HELD" tone="OK" />}
        </span>
        <span className="col-span-2 text-[10px] text-slate-500 truncate">{r.sector}</span>
        <span className="col-span-1 text-right text-slate-300">{r.articles}</span>
        <span className="col-span-1 text-right text-[10px] text-slate-500" title="positive / neutral / negative">{r.breakdown}</span>
        <span className={`col-span-1 text-right font-bold ${sentClass(r.weighted_sentiment)}`}>{fmtNum(r.weighted_sentiment, 2)}</span>
        <span className="col-span-4 text-[10px] text-slate-500 truncate">{r.latest_headline}</span>
        <span className="col-span-1 flex justify-end text-slate-500">
          {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-1.5 border-t border-slate-800/60 pt-2">
          {loading && <span className="text-[10px] text-slate-500">loading articles…</span>}
          {articles !== null && articles.length === 0 && (
            <span className="text-[10px] text-slate-500">No tagged articles in the last 48h (the row's stats may come from a slightly wider window).</span>
          )}
          {(articles ?? []).map((a, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px]">
              <span className={`font-mono font-bold w-12 text-right flex-shrink-0 ${sentClass(a.sentiment)}`}>
                {a.sentiment != null ? fmtNum(a.sentiment, 2) : "—"}
              </span>
              <div className="min-w-0">
                <a href={a.url} target="_blank" rel="noreferrer"
                  className="text-slate-200 hover:text-indigo-300 inline-flex items-start gap-1">
                  <span className="whitespace-normal">{a.title}</span>
                  <ExternalLink size={10} className="flex-shrink-0 mt-0.5 text-slate-500" />
                </a>
                <div className="text-[9px] text-slate-600">{a.source} · {a.ts}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function NewsAlerts() {
  const [sev, setSev] = useState("");
  const [scope, setScope] = useState("BOTH");
  const alerts = useApi<any[]>(`/api/alerts/feed?scope=${scope}${sev ? `&severity=${sev}` : ""}&hours=168&limit=100`, [sev, scope]);
  const stats = useApi<any>("/api/news/stats");
  const [lbSort, setLbSort] = useState("n_desc");
  const leaderboard = useApi<any[]>(`/api/news/leaderboard?hours=48&scope=universe_with_news&sort_by=${lbSort}`, [lbSort]);
  const [lbQuery, setLbQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (label: string, path: string, after?: () => void) => {
    setBusy(path);
    try { const r = await postJSON(path, {}); toast(`${label}: ${r.message ?? "started"}`); setTimeout(() => after?.(), 2500); }
    catch (e: any) { toast(`${label} failed: ${e.message}`); }
    setBusy(null);
  };

  const lbRows = (leaderboard.data ?? []).filter(
    (r) => !lbQuery || r.ticker.toLowerCase().includes(lbQuery.toLowerCase())
      || (r.sector ?? "").toLowerCase().includes(lbQuery.toLowerCase()));

  return (
    <div className="space-y-6">
      <Help text="News flows in from 7 RSS feeds every 30 minutes and is matched to tickers by company name (common-word tickers like OIL or PERSISTENT only match their full company names — no more crude-oil noise). The LLM then assesses impact on your holdings and watchlist: critical alerts on holdings can recommend a position review and go to Telegram." />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Articles Stored" value={stats.data?.total ?? 0} sub={`${stats.data?.last_24h ?? 0} in last 24h`} />
        <StatCard label="Ticker-Tagged" value={stats.data?.tagged ?? 0} sub="Matched to at least one stock" />
        <StatCard label="Latest Article" value={<span className="text-sm">{fmtIST(stats.data?.latest)}</span>} />
        <div className="glass-panel rounded-2xl p-4 flex flex-col gap-2 justify-center">
          <Btn kind="primary" busy={busy === "/api/news/scrape"} onClick={() => run("Scrape", "/api/news/scrape", () => { stats.reload(); leaderboard.reload(); })}><Zap size={11} /> Scrape News Now</Btn>
          <Btn busy={busy === "/api/alerts/run"} onClick={() => run("Impact pass", "/api/alerts/run", alerts.reload)}>Run LLM Impact Pass</Btn>
          <Btn busy={busy === "/api/news/retag"} onClick={() => run("Retag", "/api/news/retag", () => { stats.reload(); leaderboard.reload(); })} title="Re-run ticker matching on stored articles — use after the matcher rules change">Retag Old Articles</Btn>
        </div>
      </div>

      <Panel title="Impact Alerts"
        subtitle="LLM-triaged news clusters — generated ONLY for stocks you hold or have on the long-term watchlist, and only when there is genuinely new news for that stock (duplicates are suppressed for 24h). An empty or short list usually means: small watchlist, or no fresh relevant news — not a bug. Severity: critical = thesis-relevant now, watch = monitor, info = context."
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
        <div className="text-[10px] text-slate-600 mb-2">{(alerts.data ?? []).length} alerts in the last 7 days for the selected filters</div>
        <div className="space-y-2 max-h-[440px] overflow-auto pr-1">
          {(alerts.data ?? []).length === 0
            ? <EmptyState>No alerts match. To widen coverage: hold more names, pin stocks on the Fundamentals page (pins join the watchlist), then Scrape News and run the LLM Impact Pass.</EmptyState>
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
                {(a.citations ?? []).length > 0 && (
                  <div className="mt-1.5 space-y-0.5">
                    {(a.citations ?? []).slice(0, 3).map((c: any, i: number) => (
                      <a key={i} href={c.url} target="_blank" rel="noreferrer"
                        className="block text-[10px] text-indigo-400/80 hover:text-indigo-300 truncate">
                        ↗ {c.title ?? c.url}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
        </div>
      </Panel>

      <Panel title="Sentiment Leaderboard (48h)"
        subtitle="Recency-weighted news sentiment per stock — click any row to see the tagged articles and open the original sources. Breakdown = positive / neutral / negative article counts."
        actions={
          <div className="flex items-center gap-2">
            <select value={lbSort} onChange={(e) => setLbSort(e.target.value)}
              className="bg-slate-900/70 border border-slate-700/60 rounded-lg px-2 py-1.5 text-xs text-slate-300 outline-none">
              <option value="n_desc">Most covered</option>
              <option value="avg_desc">Most bullish</option>
              <option value="avg_asc">Most bearish</option>
              <option value="ts_desc">Most recent</option>
            </select>
            <SearchBox value={lbQuery} onChange={setLbQuery} placeholder="Filter ticker/sector…" />
            <RefreshBtn onClick={leaderboard.reload} loading={leaderboard.loading} />
          </div>
        }>
        {lbRows.length === 0 ? (
          <EmptyState>No tagged news in the window yet — press "Scrape News Now" above, then refresh.</EmptyState>
        ) : (
          <div className="space-y-1.5 max-h-[480px] overflow-auto pr-1">
            <div className="grid grid-cols-12 gap-2 px-3 text-[9px] text-slate-600 uppercase tracking-wider font-semibold">
              <span className="col-span-2">Ticker</span>
              <span className="col-span-2">Sector</span>
              <span className="col-span-1 text-right">Articles</span>
              <span className="col-span-1 text-right">+ / · / −</span>
              <span className="col-span-1 text-right">Sentiment</span>
              <span className="col-span-4">Latest Headline</span>
              <span className="col-span-1" />
            </div>
            {lbRows.map((r: any) => <LeaderRow key={r.ticker} r={r} />)}
          </div>
        )}
      </Panel>
    </div>
  );
}
