import React, { useState, useEffect, useRef } from "react";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Play,
  Pause,
  Sliders,
  DollarSign,
  AlertTriangle,
  FileText,
  PieChart,
  BookOpen,
  RefreshCw,
  Search,
  CheckCircle,
  XCircle,
  Newspaper,
  Shield,
  Layers,
  Sparkles,
  Download,
  AlertCircle,
  Upload,
  Cpu
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  ComposedChart,
  Line,
  Legend,
} from "recharts";

const API_BASE = "http://127.0.0.1:8000";

// --- HELPERS ---
const to_ist_str = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  try {
    if (typeof iso === "string" && iso.includes("IST")) return iso;
    return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) + " IST";
  } catch (e) {
    return String(iso);
  }
};

// --- TYPES ---
interface BotParams {
  max_open_positions: number;
  risk_per_trade_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  min_composite_score: number;
}

interface LastCycleSummary {
  id?: number;
  started_at_ist?: string;
  finished_at_ist?: string;
  status?: string;
  triggered_by?: string;
  summary?: any;
}

interface BotStatus {
  status: string;
  mode: string;
  market_open: boolean;
  market_time_ist: string;
  is_weekday: boolean;
  last_cycle: LastCycleSummary | null;
  params: BotParams;
}

interface PortfolioSummary {
  cash: number;
  equity: number;
  total_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  live_unrealized_pnl?: number;
  live_total_value?: number;
}

interface PortfolioCapacity {
  active_slots: number;
  max_slots: number;
  remaining_slots: number;
  ratio: number;
}

interface EquityPoint {
  ts: string;
  ts_ist: string;
  portfolio_value: number;
  cash: number;
  equity: number;
  unrealized_pnl: number;
  realized_pnl: number;
}

interface BenchmarkPoint {
  ts: string;
  ts_ist: string;
  benchmark_value: number;
  raw_close: number;
}

interface EquityCurveResponse {
  portfolio: EquityPoint[];
  benchmark: BenchmarkPoint[];
  initial_capital: number;
}

interface DrawdownPoint {
  ts: string;
  ts_ist: string;
  value: number;
  drawdown_pct: number;
}

interface OpenPosition {
  id: number;
  ticker: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  price_as_of: string;
  stop_loss: number | null;
  take_profit: number | null;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  strategy: string;
  composite_score: number;
  entered_at: string;
  high_water_mark: number | null;
  atr_at_entry: number | null;
  t1_target: number | null;
  t1_taken: number;
}

interface ClosedPosition {
  position_id: number;
  ticker: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  opened_at: string;
  closed_at: string;
  pnl: number;
  pnl_pct: number;
  strategy: string;
}

interface RawTrade {
  id: number;
  ts: string;
  ticker: string;
  side: string;
  quantity: number;
  price: number;
  value: number;
  costs: number;
  net_value: number;
  strategy: string;
  reason: string;
  composite_score: number;
  mode: string;
  position_id: number | null;
}

interface ApprovalSignal {
  id: number;
  created_at: string;
  expires_at: string;
  remaining_seconds: number;
  ticker: string;
  side: string;
  action: string;
  quantity: number;
  price: number;
  stop_loss: number | null;
  take_profit: number | null;
  strategy: string;
  composite_score: number;
  reason: string;
  status: string;
}

interface SignalHistory {
  id: number;
  ts: string;
  ticker: string;
  action: string;
  strategy: string;
  technical_score: number;
  fundamental_score: number;
  sentiment_score: number;
  composite_score: number;
  price: number | null;
  reason: string;
  taken: boolean;
}

interface NewsLeader {
  ticker: string;
  is_open_position: boolean;
  sector: string;
  articles: number;
  breakdown: string;
  avg_sentiment: number;
  weighted_sentiment: number;
  latest_sentiment: number;
  latest_headline: string;
  latest_url: string;
  last_update: string;
}

interface TickerNews {
  ts: string;
  source: string;
  title: string;
  summary: string;
  url: string;
  sentiment: number | null;
}

interface FundamentalStock {
  ticker: string;
  screener_url: string;
  is_bank: boolean;
  sources?: string[];
  fetched_at: string;
  pe_ratio: number | null;
  peg_ratio: number | null;
  eps: number | null;
  revenue_growth: number | null;
  earnings_growth: number | null;
  debt_to_equity: number | null;
  roe: number | null;
  profit_margin: number | null;
  market_cap: number | null;
  dividend_yield: number | null;
  sector: string;
  industry: string;
  fundamental_score: number | null;
}

interface SeriesPoint { period: string; value: number | null; }
interface ShareholdingRow {
  period: string;
  promoter_pct: number | null;
  fii_pct: number | null;
  dii_pct: number | null;
  govt_pct: number | null;
  public_pct: number | null;
  pledged_pct: number | null;
  shareholders: number | null;
}
interface ConcallRow {
  date: string | null;
  transcript_url: string | null;
  ppt_url: string | null;
  notes_url: string | null;
  rec_url: string | null;
}
interface AnnualReportRow { label: string; url: string; }

interface FundamentalsDetail {
  ticker: string;
  screener_url: string;
  view: string;
  fetched_at: string;
  warnings: string[];
  top_ratios: {
    market_cap_cr: number | null;
    pe: number | null;
    industry_pe: number | null;
    roe_pct: number | null;
    roce_pct: number | null;
    debt_equity: number | null;
    dividend_yield_pct: number | null;
    book_value: number | null;
    face_value: number | null;
  };
  profit_loss: {
    revenue: SeriesPoint[];
    operating_profit: SeriesPoint[];
    net_profit: SeriesPoint[];
    eps: SeriesPoint[];
    interest?: SeriesPoint[];
    depreciation?: SeriesPoint[];
  };
  balance_sheet: {
    equity_capital: SeriesPoint[]; reserves: SeriesPoint[];
    borrowings: SeriesPoint[]; other_liabilities: SeriesPoint[];
    total_liabilities: SeriesPoint[]; fixed_assets: SeriesPoint[];
    cwip: SeriesPoint[]; investments: SeriesPoint[];
    other_assets: SeriesPoint[]; total_assets: SeriesPoint[];
  };
  cash_flow: {
    cfo: SeriesPoint[]; cfi: SeriesPoint[]; cff: SeriesPoint[]; net_cash: SeriesPoint[];
  };
  ratios: {
    roe: SeriesPoint[]; roce: SeriesPoint[]; opm: SeriesPoint[]; debtor_days: SeriesPoint[];
  };
  quarterly_results: {
    revenue: SeriesPoint[]; operating_profit: SeriesPoint[];
    net_profit: SeriesPoint[]; eps: SeriesPoint[]; opm: SeriesPoint[];
  };
  shareholding: ShareholdingRow[];
  pros: string[];
  cons: string[];
  concalls: ConcallRow[];
  annual_reports: AnnualReportRow[];
  announcements: string[];
}

interface PriceHistoryPoint { ts: string; close: number; volume?: number; }
interface FundamentalsPriceHistory {
  ticker: string;
  period?: string;
  years?: number;
  series: PriceHistoryPoint[];
}

type Timeframe = "1M" | "6M" | "1Y" | "3Y" | "5Y" | "10Y" | "Max";

interface FundamentalsPin { ticker: string; added_at: string; notes: string; }

interface AnalyticsSummary {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_winner: number;
  avg_loser: number;
  total_pnl: number;
  profit_factor: number;
}

interface StrategyPerformance {
  strategy: string;
  trades: number;
  total_pnl: number;
  avg_pnl: number;
  wins: number;
  win_rate_pct: number;
}

interface ResearchCandidate {
  ticker: string;
  scored_at: string;
  profitability_score: number;
  cash_quality_score: number;
  solvency_score: number;
  growth_score: number;
  governance_score: number;
  total_score: number;
  sector: string;
  market_cap: number | null;
}

interface ResearchFailure {
  ticker: string;
  sector: string;
  reason: string;
}

interface ObservabilityTotals {
  prompt_tokens_today: number;
  completion_tokens_today: number;
  cost_today_usd: number;
  max_daily_budget_usd: number;
  calls_today: number;
  success_rate_pct: number;
}

interface ObservabilityCaller {
  caller: string;
  calls: number;
  tokens: number;
  pct: number;
}

interface ObservabilityDaily {
  date: string;
  calls: number;
  cost: number;
}

interface ObservabilityCall {
  id: number;
  ts: string;
  caller: string;
  model: string;
  status: string;
  tokens: number;
  note: string;
}

interface PositionalStatus {
  initial_capital: number;
  cash_balance: number;
  allocated_value: number;
  net_realized_pnl: number;
  total_valuation: number;
  max_positions: number;
  active_positions_count: number;
  available_slots: number;
  llm_research_enabled?: boolean;
  swap_enabled?: boolean;
}

interface PositionalRegime {
  computed_at: string;
  nifty_roc_18m: number;
  smallcap_roc_20m: number;
  nifty_gold_ratio: number;
  flag: string;
  size_multiplier: number;
  notes: string;
}

interface PositionalScanResult {
  id: number;
  scanned_at: string;
  ticker: string;
  price: number | null;
  trend_template: boolean;
  vcp_detected: boolean;
  vcp_strength: number | null;
  proximity_52w_pct: number | null;
  ema21: number | null;
  ema50: number | null;
  ema200: number | null;
  atr_pct: number | null;
  score: number;
  alert_type: string;
  reason: string;
  composite_score: number | null;
  confluence: number;
  strategies_fired: string;
  horizon: string;
  conviction: string;
  timing_score: number | null;
  durability_score: number | null;
  quality_pillar: number | null;
  valuation_pillar: number | null;
  momentum_pillar: number | null;
  sentiment_pillar: number | null;
  management_pillar: number | null;
  est_hold_days: number;
}

interface PositionalResearch {
  ticker: string;
  researched_at: string;
  concall_date: string;
  management_score: number | null;
  verdict: string;
  outlook: string;
  thesis: string;
  key_positives: string[];
  key_risks: string[];
  guidance: string;
  recommendation: string;
  recommendation_rationale: string;
  concall_summary: string;
  fundamentals_summary: string;
  sources: string[];
  confidence: number | null;
}

interface PositionalPosition {
  id: number;
  ticker: string;
  entry_date: string;
  entry_price: number;
  current_price: number;
  quantity: number;
  hard_stop: number;
  ema_trail_stop: number | null;
  target_price: number | null;
  peak_price: number | null;
  below_ema_consecutive: number;
  days_held: number;
  regime_at_entry: string;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  notes: string;
  strategy?: string;
}

const renderStrategyBadge = (strategy: string) => {
  const norm = (strategy || "").toUpperCase();
  switch (norm) {
    case "FUN_TECH_MOMENTUM":
      return (
        <span className="px-2 py-0.5 rounded text-[9px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          FTM
        </span>
      );
    case "BRAHMA_VISHNU_MAHESH":
      return (
        <span className="px-2 py-0.5 rounded text-[9px] font-bold bg-purple-500/10 text-purple-400 border border-purple-500/20">
          BVM
        </span>
      );
    case "YOUNG_MOMENTUM":
      return (
        <span className="px-2 py-0.5 rounded text-[9px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
          YM (1-2-3-4)
        </span>
      );
    case "MINERVINI_VCP":
    default:
      return (
        <span className="px-2 py-0.5 rounded text-[9px] font-bold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
          VCP + Vix
        </span>
      );
  }
};

const renderHorizonBadge = (horizon: string) => {
  const h = (horizon || "").toUpperCase();
  const map: Record<string, { label: string; cls: string }> = {
    BOTH: { label: "POSITIONAL + LT", cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" },
    POSITIONAL: { label: "POSITIONAL", cls: "bg-sky-500/10 text-sky-400 border-sky-500/30" },
    LONG_TERM: { label: "LONG-TERM WATCH", cls: "bg-amber-500/10 text-amber-400 border-amber-500/30" },
    AVOID: { label: "AVOID", cls: "bg-slate-700/20 text-slate-500 border-slate-700/30" },
  };
  const m = map[h];
  if (!m) return <span className="text-slate-600">—</span>;
  return <span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${m.cls}`}>{m.label}</span>;
};

const renderOutlookBadge = (outlook: string) => {
  const o = (outlook || "").toUpperCase();
  const map: Record<string, string> = {
    POSITIVE: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    NEUTRAL: "bg-slate-700/20 text-slate-400 border-slate-700/30",
    MIXED: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    NEGATIVE: "bg-rose-500/10 text-rose-400 border-rose-500/30",
  };
  if (!map[o]) return null;
  return <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${map[o]}`}>{o}</span>;
};

const renderRecommendationBadge = (rec: string) => {
  const r = (rec || "").toUpperCase();
  const map: Record<string, { label: string; cls: string }> = {
    SWING_POSITIONAL: { label: "SWING POSITIONAL", cls: "bg-sky-500/10 text-sky-400 border-sky-500/30" },
    LONG_TERM: { label: "LONG-TERM", cls: "bg-amber-500/10 text-amber-400 border-amber-500/30" },
    BOTH: { label: "SWING + LONG-TERM", cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" },
    AVOID: { label: "AVOID", cls: "bg-rose-500/10 text-rose-400 border-rose-500/30" },
  };
  const m = map[r];
  if (!m) return <span className="text-slate-600">—</span>;
  return <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${m.cls}`}>{m.label}</span>;
};

const renderFiredStrategies = (strategiesFired: string, reason: string) => {
  const fired = (strategiesFired || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (fired.length === 0) {
    // No entry trigger fired (e.g. a long-term watch candidate)
    return reason ? <span className="text-slate-600">—</span> : renderStrategyBadge("MINERVINI_VCP");
  }
  return (
    <div className="flex flex-wrap gap-1 justify-center">
      {fired.map((s, i) => (
        <span key={i}>{renderStrategyBadge(s.toUpperCase())}</span>
      ))}
    </div>
  );
};


const ResearchDetail: React.FC<{ scan: PositionalScanResult; research?: PositionalResearch }> = ({ scan, research }) => (
  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs">
    <div className="space-y-2">
      {research ? (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-slate-500 uppercase tracking-wider text-[9px]">Recommendation</span>
            {renderRecommendationBadge(research.recommendation)}
            {research.recommendation_rationale ? (
              <span className="text-slate-400 text-[11px]">{research.recommendation_rationale}</span>
            ) : null}
          </div>
          <div className="text-slate-500 uppercase tracking-wider text-[9px] pt-1">Analyst Thesis</div>
          <div className="text-slate-200 leading-relaxed">{research.thesis || "—"}</div>
          {research.guidance ? (
            <div className="text-slate-400"><span className="text-slate-500">Mgmt Guidance:</span> {research.guidance}</div>
          ) : null}
          {research.concall_summary ? (
            <div className="pt-1">
              <div className="text-violet-400 uppercase tracking-wider text-[9px] mb-0.5">Concall Summary</div>
              <div className="text-slate-300 leading-relaxed whitespace-pre-line">{research.concall_summary}</div>
            </div>
          ) : (
            <div className="text-slate-600 text-[10px] pt-1">No concall transcript processed (install pypdf / transcript unavailable).</div>
          )}
          {research.fundamentals_summary ? (
            <div className="pt-1">
              <div className="text-cyan-400 uppercase tracking-wider text-[9px] mb-0.5">Fundamentals &amp; Ownership</div>
              <div className="text-slate-300 leading-relaxed">{research.fundamentals_summary}</div>
            </div>
          ) : null}
          <div className="text-slate-500 text-[10px] pt-1">
            {research.concall_date ? `Concall: ${research.concall_date}` : "Concall: n/a"}
            {research.confidence != null ? ` · Confidence: ${(research.confidence * 100).toFixed(0)}%` : ""}
            {research.researched_at ? ` · ${research.researched_at}` : ""}
          </div>
        </>
      ) : (
        <>
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">Technical Reason</div>
          <div className="text-slate-300 leading-relaxed">{scan.reason || "—"}</div>
          <div className="text-slate-500 italic pt-2">No analyst research yet — runs on the next scan or research refresh.</div>
        </>
      )}
    </div>
    {research ? (
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <div className="text-emerald-400 uppercase tracking-wider text-[9px] mb-1">Key Positives</div>
          {research.key_positives?.length ? (
            <ul className="list-disc list-inside text-slate-300 space-y-1">
              {research.key_positives.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          ) : <div className="text-slate-600">—</div>}
        </div>
        <div>
          <div className="text-rose-400 uppercase tracking-wider text-[9px] mb-1">Key Risks</div>
          {research.key_risks?.length ? (
            <ul className="list-disc list-inside text-slate-300 space-y-1">
              {research.key_risks.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          ) : <div className="text-slate-600">—</div>}
        </div>
        <div className="sm:col-span-2 text-[10px] text-slate-500">
          Technical: {scan.reason || "—"}
        </div>
        {research.sources?.length ? (
          <div className="sm:col-span-2">
            <div className="text-slate-500 uppercase tracking-wider text-[9px] mb-1">Sources</div>
            <div className="flex flex-wrap gap-3">
              {research.sources.map((s, i) => (
                <a key={i} href={s} target="_blank" rel="noopener noreferrer" className="text-sky-400 hover:underline truncate max-w-[280px]">{s}</a>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    ) : null}
  </div>
);

interface PositionalScanTableProps {
  rows: PositionalScanResult[];
  research: Record<string, PositionalResearch>;
  variant: "swing" | "longterm";
}

const PositionalScanTable: React.FC<PositionalScanTableProps> = ({ rows, research, variant }) => {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const isLong = variant === "longterm";
  const inr = (v: number | null) => (v != null ? `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "—");
  const num = (v: number | null) => (v != null ? v.toFixed(0) : "—");
  const lookup = (t: string) => research[t.replace(/\.(NS|BO)$/, "")];
  const toggle = (id: number) =>
    setExpanded((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  const title = isLong
    ? "Long-Term Accumulation Candidates (durable businesses + concall thesis)"
    : "Latest Swing Scan Results (VCP & Multi-Strategy Checklists)";
  const unit = isLong ? "long-term candidates" : "setups detected";
  const headers = isLong
    ? ["", "Ticker", "Horizon", "Composite", "Durability", "Quality", "Valuation", "Momentum", "Mgmt / Outlook"]
    : ["", "Ticker", "Horizon", "Confluence", "Strategy", "Price", "Trend", "VCP", "52W %", "ATR %", "Composite", "Timing / Durab", "Mgmt / Outlook"];
  const colCount = headers.length;

  const mgmtCell = (scan: PositionalScanResult) => {
    const r = lookup(scan.ticker);
    return (
      <td className="py-3 px-4 text-center whitespace-nowrap">
        <span className="text-teal-400 font-bold mr-1">{num(scan.management_pillar)}</span>
        {r ? renderOutlookBadge(r.outlook) : null}
      </td>
    );
  };

  return (
    <div className="glass-panel p-6 rounded-2xl">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">{title}</h3>
        <span className="text-xs text-slate-500 font-mono">({rows.length} {unit})</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
              {headers.map((h, i) => (
                <th key={i} className={`py-3 px-4 ${i >= 3 && !isLong ? "text-center" : ""} ${isLong && i >= 3 ? "text-center" : ""}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-850">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="py-8 text-center text-slate-500">
                  No {isLong ? "long-term" : "swing"} candidates yet. Run a scan{isLong ? " + research refresh" : ""}.
                </td>
              </tr>
            ) : (
              rows.map((scan) => {
                const open = expanded.has(scan.id);
                return (
                  <React.Fragment key={scan.id}>
                    <tr className="hover:bg-slate-900/20 cursor-pointer" onClick={() => toggle(scan.id)}>
                      <td className="py-3 px-4 text-slate-500 text-center w-6">{open ? "▾" : "▸"}</td>
                      <td className="py-3 px-4 text-slate-200 font-bold">{scan.ticker}</td>
                      <td className="py-3 px-4 text-center">{renderHorizonBadge(scan.horizon)}</td>
                      {isLong ? (
                        <>
                          <td className="py-3 px-4 text-center text-indigo-400 font-bold">{scan.composite_score != null ? scan.composite_score : scan.score}</td>
                          <td className="py-3 px-4 text-center text-amber-400 font-bold">{num(scan.durability_score)}</td>
                          <td className="py-3 px-4 text-center text-slate-300">{num(scan.quality_pillar)}</td>
                          <td className="py-3 px-4 text-center text-slate-300">{num(scan.valuation_pillar)}</td>
                          <td className="py-3 px-4 text-center text-slate-300">{num(scan.momentum_pillar)}</td>
                          {mgmtCell(scan)}
                        </>
                      ) : (
                        <>
                          <td className="py-3 px-4 text-center" title={scan.strategies_fired || ""}>
                            {scan.confluence > 0 ? (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                                {scan.confluence}× {scan.conviction ? scan.conviction.toUpperCase() : ""}
                              </span>
                            ) : (
                              <span className="text-slate-600">—</span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-center">{renderFiredStrategies(scan.strategies_fired, scan.reason)}</td>
                          <td className="py-3 px-4 text-right text-slate-300">{scan.price ? inr(scan.price) : "—"}</td>
                          <td className="py-3 px-4 text-center">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${scan.trend_template ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-rose-500/10 text-rose-400 border border-rose-500/20"}`}>
                              {scan.trend_template ? "PASS" : "FAIL"}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-center">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${scan.vcp_detected ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-slate-850 text-slate-500"}`}>
                              {scan.vcp_detected ? "YES" : "—"}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-right text-slate-300">{scan.proximity_52w_pct ? `${scan.proximity_52w_pct.toFixed(1)}%` : "—"}</td>
                          <td className="py-3 px-4 text-right text-purple-400">{scan.atr_pct ? `${scan.atr_pct.toFixed(1)}%` : "—"}</td>
                          <td className="py-3 px-4 text-center text-indigo-400 font-bold">{scan.composite_score != null ? scan.composite_score : scan.score}</td>
                          <td className="py-3 px-4 text-center text-slate-400 whitespace-nowrap">
                            <span className="text-sky-400">{num(scan.timing_score)}</span>
                            <span className="text-slate-600"> / </span>
                            <span className="text-amber-400">{num(scan.durability_score)}</span>
                          </td>
                          {mgmtCell(scan)}
                        </>
                      )}
                    </tr>
                    {open && (
                      <tr className="bg-slate-900/40">
                        <td colSpan={colCount} className="px-6 py-4">
                          <ResearchDetail scan={scan} research={lookup(scan.ticker)} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// -----------------------------------------------------------------------------
// FUNDAMENTALS DETAIL PANEL
// -----------------------------------------------------------------------------
// Screener.in-style deep view rendered inside the expanded row of the
// Fundamentals tab. The data is fetched by `toggleFundamentalsRow` in App() and
// passed in via props so this component stays stateless and reusable.
const fmtNumber = (val: number | null | undefined, digits = 2) => {
  if (val === null || val === undefined || isNaN(val)) return "—";
  return val.toLocaleString("en-IN", { maximumFractionDigits: digits });
};

const SeriesTable: React.FC<{
  caption: string;
  rows: { label: string; series: SeriesPoint[]; unit?: string }[];
}> = ({ caption, rows }) => {
  // Build canonical period list from the first row that has data — Screener
  // tables share a common header set per section so this is safe.
  const firstWithData = rows.find((r) => r.series && r.series.length > 0);
  const periods = firstWithData ? firstWithData.series.map((p) => p.period) : [];
  if (periods.length === 0) {
    return (
      <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-850">
        <h4 className="text-[10px] font-bold uppercase tracking-wider text-indigo-300 mb-2">{caption}</h4>
        <div className="text-[11px] text-slate-500">No data available for this section.</div>
      </div>
    );
  }
  return (
    <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-850">
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-indigo-300 mb-2">{caption}</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono">
          <thead>
            <tr className="text-slate-500 border-b border-slate-850">
              <th className="text-left py-1.5 px-2 w-[140px]">Metric</th>
              {periods.map((p) => (
                <th key={p} className="text-right py-1.5 px-2 whitespace-nowrap">{p}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const byPeriod: Record<string, number | null> = {};
              for (const pt of row.series || []) byPeriod[pt.period] = pt.value;
              return (
                <tr key={row.label} className="border-b border-slate-850/60">
                  <td className="py-1.5 px-2 text-slate-300">{row.label}</td>
                  {periods.map((p) => {
                    const v = byPeriod[p];
                    const display = v === null || v === undefined
                      ? "—"
                      : `${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}${row.unit || ""}`;
                    return (
                      <td key={p} className="py-1.5 px-2 text-right text-slate-300 whitespace-nowrap">
                        {display}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// Reverse a "most-recent-first" series into chronological order and cap it
// to the most recent N periods (last N entries after the reverse). Used by
// every yearly / quarterly chart in the detail panel.
const seriesAsc = (pts: SeriesPoint[] | undefined, cap?: number): SeriesPoint[] => {
  const arr = [...(pts || [])].reverse();
  if (cap && arr.length > cap) return arr.slice(arr.length - cap);
  return arr;
};

// Year-keys parsed out of a Screener period label like "Mar 2024" or
// "Dec 2023". We match by 4-digit year.
const _YEAR_RE_FE = /\b(19|20)\d{2}\b/;
const yearOf = (period: string | undefined): number | null => {
  if (!period) return null;
  const m = _YEAR_RE_FE.exec(period);
  return m ? parseInt(m[0], 10) : null;
};

// Pick the closing price closest to (but on or before) Dec 31 of `year` from
// the price-history series. Returns null if no such observation exists -
// rapid-IPO companies will have no price in their early reporting years.
const yearEndClose = (series: PriceHistoryPoint[], year: number): number | null => {
  let chosen: number | null = null;
  const cutoff = `${year}-12-31`;
  for (const p of series) {
    if (p.ts <= cutoff) chosen = p.close;
    else break;
  }
  return chosen;
};

const TIMEFRAMES: Timeframe[] = ["1M", "6M", "1Y", "3Y", "5Y", "10Y", "Max"];

// Translate the user-visible timeframe into a "max years of fundamentals
// data to show". For yearly / quarterly panels we just trim the trailing
// rows so the user is comparing the same horizon across all chart families.
const yearsCapFor = (tf: Timeframe): number => {
  switch (tf) {
    case "1M": case "6M": case "1Y": return 2;   // last 2 yrs of fundamentals
    case "3Y":  return 3;
    case "5Y":  return 5;
    case "10Y": return 10;
    case "Max": return 99;
  }
};
const quartersCapFor = (tf: Timeframe): number => {
  switch (tf) {
    case "1M": case "6M": case "1Y": return 4;
    case "3Y":  return 12;
    case "5Y":  return 20;
    case "10Y": return 40;
    case "Max": return 99;
  }
};

interface PriceChartPoint { ts: string; close: number; volume: number; }

const tickAxisStyle = { stroke: "#475569", fontSize: 10 };
const tooltipContentStyle = { backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0", fontSize: 11 };


type ChartType = "price" | "pe" | "salesmargin" | "pbv" | "evebitda" | "mcapsales" | "yearly_pl" | "returns" | "cashflow";

const PRIMARY_CHARTS: { key: ChartType; label: string }[] = [
  { key: "price",       label: "Price" },
  { key: "pe",          label: "PE Ratio" },
  { key: "salesmargin", label: "Sales & Margin" },
  { key: "pbv",         label: "Price to Book" },
];
const MORE_CHARTS: { key: ChartType; label: string }[] = [
  { key: "evebitda",  label: "EV / EBITDA" },
  { key: "mcapsales", label: "Market Cap / Sales" },
  { key: "yearly_pl", label: "Yearly P&L" },
  { key: "returns",   label: "Returns & Margins" },
  { key: "cashflow",  label: "Cash Flow" },
];

// Simple-moving-average overlay computed in the browser from the price
// series. Returns null for the first window-1 points - Recharts skips
// nulls cleanly so the line just starts later in the chart.
const withSma = (series: PriceChartPoint[], windows: number[]): (PriceChartPoint & { [k: string]: number | null })[] => {
  if (!series.length) return [];
  return series.map((p, i) => {
    const enriched: any = { ...p };
    for (const w of windows) {
      if (i + 1 < w) {
        enriched[`sma${w}`] = null;
      } else {
        let sum = 0;
        for (let j = i - w + 1; j <= i; j++) sum += series[j].close;
        enriched[`sma${w}`] = +(sum / w).toFixed(2);
      }
    }
    return enriched;
  });
};

const FundamentalsChartGrid: React.FC<{
  detail: FundamentalsDetail;
  priceSeries: PriceChartPoint[];
  timeframe: Timeframe;
  topRatios: FundamentalsDetail["top_ratios"];
}> = ({ detail, priceSeries, timeframe, topRatios }) => {
  const yearsCap = yearsCapFor(timeframe);
  const quartersCap = quartersCapFor(timeframe);

  const [chartType, setChartType] = useState<ChartType>("price");
  const [moreOpen, setMoreOpen] = useState(false);
  // Price-view-only toggles
  const [showVolume, setShowVolume] = useState(true);
  const [showSma50, setShowSma50]   = useState(false);
  const [showSma200, setShowSma200] = useState(false);
  const moreRef = useRef<HTMLDivElement | null>(null);

  // Close the More dropdown on click outside.
  useEffect(() => {
    if (!moreOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) setMoreOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [moreOpen]);

  // ---------- Yearly P&L (Revenue / OP / Net Profit + EPS) ----------
  const pl = detail.profit_loss;
  const plRows = (() => {
    const rev = seriesAsc(pl.revenue, yearsCap);
    const op  = seriesAsc(pl.operating_profit, yearsCap);
    const np  = seriesAsc(pl.net_profit, yearsCap);
    const eps = seriesAsc(pl.eps, yearsCap);
    const byPeriod = (arr: SeriesPoint[]) => Object.fromEntries(arr.map((r) => [r.period, r.value]));
    const opP = byPeriod(op), npP = byPeriod(np), epsP = byPeriod(eps);
    const periods = rev.length ? rev.map((r) => r.period) : op.map((r) => r.period);
    return rev.map((r) => ({
      period: r.period, revenue: r.value, op: opP[r.period] ?? null,
      net: npP[r.period] ?? null, eps: epsP[r.period] ?? null,
    })).concat(
      periods.filter((p) => !rev.find((rr) => rr.period === p)).map((p) => ({
        period: p, revenue: null, op: opP[p] ?? null, net: npP[p] ?? null, eps: epsP[p] ?? null,
      }))
    );
  })();

  // ---------- Yearly Margins / Returns (ROE/ROCE/OPM) ----------
  const ratiosRows = (() => {
    const roe  = seriesAsc(detail.ratios.roe,  yearsCap);
    const roce = seriesAsc(detail.ratios.roce, yearsCap);
    const opm  = seriesAsc(detail.ratios.opm,  yearsCap);
    const periods = roe.length ? roe.map((r) => r.period)
                   : (roce.length ? roce.map((r) => r.period) : opm.map((r) => r.period));
    const m = (arr: SeriesPoint[]) => Object.fromEntries(arr.map((r) => [r.period, r.value]));
    const roeM = m(roe), roceM = m(roce), opmM = m(opm);
    return periods.map((p) => ({ period: p, roe: roeM[p] ?? null, roce: roceM[p] ?? null, opm: opmM[p] ?? null }));
  })();

  // ---------- Quarterly Sales + OPM% + NPM% ----------
  const quarterlyRows = (() => {
    const rev = seriesAsc(detail.quarterly_results.revenue, quartersCap);
    const np  = seriesAsc(detail.quarterly_results.net_profit, quartersCap);
    const opm = seriesAsc(detail.quarterly_results.opm, quartersCap);
    const m = (arr: SeriesPoint[]) => Object.fromEntries(arr.map((r) => [r.period, r.value]));
    const npM = m(np), opmM = m(opm);
    return rev.map((r) => {
      const npv = npM[r.period];
      const npm = (r.value && npv != null && r.value !== 0) ? (npv / r.value) * 100 : null;
      return { period: r.period, revenue: r.value, opm: opmM[r.period] ?? null, npm: npm != null ? +npm.toFixed(2) : null };
    });
  })();

  // ---------- Cash Flow (Yearly) ----------
  const cashFlowRows = (() => {
    const cfo = seriesAsc(detail.cash_flow.cfo, yearsCap);
    const cfi = seriesAsc(detail.cash_flow.cfi, yearsCap);
    const cff = seriesAsc(detail.cash_flow.cff, yearsCap);
    const m = (arr: SeriesPoint[]) => Object.fromEntries(arr.map((r) => [r.period, r.value]));
    const periods = cfo.length ? cfo.map((r) => r.period)
                   : (cfi.length ? cfi.map((r) => r.period) : cff.map((r) => r.period));
    const cfoM = m(cfo), cfiM = m(cfi), cffM = m(cff);
    return periods.map((p) => ({ period: p, cfo: cfoM[p] ?? null, cfi: cfiM[p] ?? null, cff: cffM[p] ?? null }));
  })();

  // ---------- Yearly Valuation proxies ----------
  // Same approximations as before — see the panel hints for caveats.
  const valuationRows = (() => {
    const epsArr   = seriesAsc(pl.eps, yearsCap);
    const revArr   = seriesAsc(pl.revenue, yearsCap);
    const opArr    = seriesAsc(pl.operating_profit, yearsCap);
    const depArr   = seriesAsc(pl.depreciation || [], yearsCap);
    const borrowArr= seriesAsc(detail.balance_sheet.borrowings, yearsCap);
    const bookValue = topRatios.book_value || null;
    const mcapNowCr = topRatios.market_cap_cr || null;
    const nowPrice = priceSeries.length ? priceSeries[priceSeries.length - 1].close : null;

    const m = (arr: SeriesPoint[]) => Object.fromEntries(arr.map((r) => [yearOf(r.period), r.value]));
    const epsByY = m(epsArr), revByY = m(revArr), opByY = m(opArr), depByY = m(depArr), borrowByY = m(borrowArr);

    const periods = revArr.length ? revArr : epsArr;
    return periods.map((r) => {
      const y = yearOf(r.period);
      if (!y) return null;
      const closeY = yearEndClose(priceSeries, y);
      const eps = epsByY[y];
      const op  = opByY[y]; const dep = depByY[y];
      const ebitda = (op != null && dep != null) ? op + dep : (op ?? null);
      const borrow = borrowByY[y];
      const sales = revByY[y];
      const mcapY = (closeY && nowPrice && mcapNowCr) ? mcapNowCr * (closeY / nowPrice) : null;
      const pe = (closeY != null && eps != null && eps !== 0) ? +(closeY / eps).toFixed(2) : null;
      const pbv = (closeY != null && bookValue != null && bookValue !== 0) ? +(closeY / bookValue).toFixed(2) : null;
      const evEbitda = (mcapY != null && ebitda != null && ebitda !== 0)
        ? +(((mcapY + (borrow || 0)) / ebitda)).toFixed(2) : null;
      const mcapSales = (mcapY != null && sales != null && sales !== 0)
        ? +((mcapY / sales)).toFixed(2) : null;
      return { period: r.period, pe, pbv, evEbitda, mcapSales, eps, ebitda, sales, bookValue };
    }).filter((x) => x !== null) as Array<{
      period: string; pe: number | null; pbv: number | null;
      evEbitda: number | null; mcapSales: number | null;
      eps: number | null; ebitda: number | null; sales: number | null; bookValue: number | null;
    }>;
  })();

  const priceSeriesEnriched = (chartType === "price" && (showSma50 || showSma200))
    ? withSma(priceSeries, [50, 200])
    : priceSeries;

  const currentLabel = (() => {
    const all = [...PRIMARY_CHARTS, ...MORE_CHARTS];
    return all.find((c) => c.key === chartType)?.label || "Chart";
  })();

  // ---------- Chart pane render switch ----------
  // Returns the chart element when data is available, or a string empty
  // message when not. ResponsiveContainer can't wrap a plain div so we
  // handle the empty case at the parent level.
  const renderChart = (): React.ReactElement | string => {
    switch (chartType) {
      case "price": {
        if (!priceSeries.length) return "No price data available.";
        return (
          <ComposedChart data={priceSeriesEnriched} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <defs>
              <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#818cf8" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#818cf8" stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="ts" tick={tickAxisStyle} minTickGap={40} />
            <YAxis yAxisId="price" tick={tickAxisStyle} domain={["auto", "auto"]} orientation="left" />
            {showVolume && (
              <YAxis yAxisId="vol" tick={tickAxisStyle} orientation="right" tickFormatter={(v) => v >= 1e6 ? `${(v/1e6).toFixed(1)}M` : v >= 1e3 ? `${(v/1e3).toFixed(0)}K` : `${v}`} />
            )}
            <Tooltip contentStyle={tooltipContentStyle}
              formatter={(value: any, name: any) => name === "Volume" ? [Number(value).toLocaleString(), "Volume"] : [`₹${value}`, name]} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            {showVolume && <Bar yAxisId="vol" dataKey="volume" fill="#334155" opacity={0.55} name="Volume" />}
            <Area yAxisId="price" type="monotone" dataKey="close" stroke="#818cf8" fill="url(#priceGrad)" strokeWidth={1.5} name="Close" />
            {showSma50  && <Line yAxisId="price" type="monotone" dataKey="sma50"  stroke="#f59e0b" strokeWidth={1.5} dot={false} name="50 DMA" />}
            {showSma200 && <Line yAxisId="price" type="monotone" dataKey="sma200" stroke="#10b981" strokeWidth={1.5} dot={false} name="200 DMA" />}
          </ComposedChart>
        );
      }
      case "pe": {
        if (!valuationRows.length) return "Not enough EPS / price data to derive P/E.";
        return (
          <ComposedChart data={valuationRows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="period" tick={tickAxisStyle} />
            <YAxis yAxisId="L" tick={tickAxisStyle} />
            <YAxis yAxisId="R" tick={tickAxisStyle} orientation="right" />
            <Tooltip contentStyle={tooltipContentStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line yAxisId="L" type="monotone" dataKey="pe"  stroke="#6366f1" strokeWidth={2} dot={{ r: 2 }} name="P/E" />
            <Line yAxisId="R" type="monotone" dataKey="eps" stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 2" dot={{ r: 2 }} name="EPS (₹)" />
          </ComposedChart>
        );
      }
      case "salesmargin": {
        if (!quarterlyRows.length) return "No quarterly results available.";
        return (
          <ComposedChart data={quarterlyRows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="period" tick={tickAxisStyle} />
            <YAxis yAxisId="L" tick={tickAxisStyle} />
            <YAxis yAxisId="R" tick={tickAxisStyle} unit="%" orientation="right" />
            <Tooltip contentStyle={tooltipContentStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Bar  yAxisId="L" dataKey="revenue" fill="#6366f1" name="Quarter Sales (₹ Cr)" />
            <Line yAxisId="R" type="monotone" dataKey="opm" stroke="#f59e0b" strokeWidth={2} dot={{ r: 2 }} name="OPM %" />
            <Line yAxisId="R" type="monotone" dataKey="npm" stroke="#10b981" strokeWidth={2} dot={{ r: 2 }} name="NPM %" />
          </ComposedChart>
        );
      }
      case "pbv": {
        if (!valuationRows.length) return "Book value / price history missing.";
        return (
          <ComposedChart data={valuationRows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="period" tick={tickAxisStyle} />
            <YAxis yAxisId="L" tick={tickAxisStyle} />
            <YAxis yAxisId="R" tick={tickAxisStyle} orientation="right" />
            <Tooltip contentStyle={tooltipContentStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line yAxisId="L" type="monotone" dataKey="pbv"       stroke="#10b981" strokeWidth={2} dot={{ r: 2 }} name="P/BV" />
            <Line yAxisId="R" type="monotone" dataKey="bookValue" stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 2" dot={{ r: 2 }} name="Book Value (₹)" />
          </ComposedChart>
        );
      }
      case "evebitda": {
        if (!valuationRows.length) return "Insufficient data to compute EV/EBITDA.";
        return (
          <ComposedChart data={valuationRows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="period" tick={tickAxisStyle} />
            <YAxis yAxisId="L" tick={tickAxisStyle} />
            <YAxis yAxisId="R" tick={tickAxisStyle} orientation="right" />
            <Tooltip contentStyle={tooltipContentStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line yAxisId="L" type="monotone" dataKey="evEbitda" stroke="#a78bfa" strokeWidth={2} dot={{ r: 2 }} name="EV/EBITDA" />
            <Line yAxisId="R" type="monotone" dataKey="ebitda"   stroke="#0ea5e9" strokeWidth={1.5} strokeDasharray="4 2" dot={{ r: 2 }} name="EBITDA (₹ Cr)" />
          </ComposedChart>
        );
      }
      case "mcapsales": {
        if (!valuationRows.length) return "Sales / market cap history missing.";
        return (
          <ComposedChart data={valuationRows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="period" tick={tickAxisStyle} />
            <YAxis yAxisId="L" tick={tickAxisStyle} />
            <YAxis yAxisId="R" tick={tickAxisStyle} orientation="right" />
            <Tooltip contentStyle={tooltipContentStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line yAxisId="L" type="monotone" dataKey="mcapSales" stroke="#0ea5e9" strokeWidth={2} dot={{ r: 2 }} name="MCap / Sales" />
            <Line yAxisId="R" type="monotone" dataKey="sales"     stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 2" dot={{ r: 2 }} name="Sales (₹ Cr)" />
          </ComposedChart>
        );
      }
      case "yearly_pl": {
        if (!plRows.length) return "No yearly P&L data.";
        return (
          <ComposedChart data={plRows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="period" tick={tickAxisStyle} />
            <YAxis yAxisId="L" tick={tickAxisStyle} />
            <YAxis yAxisId="R" tick={tickAxisStyle} orientation="right" />
            <Tooltip contentStyle={tooltipContentStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Bar  yAxisId="L" dataKey="revenue" fill="#6366f1" name="Revenue (₹ Cr)" />
            <Bar  yAxisId="L" dataKey="op"      fill="#10b981" name="Operating Profit" />
            <Bar  yAxisId="L" dataKey="net"     fill="#0ea5e9" name="Net Profit" />
            <Line yAxisId="R" type="monotone" dataKey="eps" stroke="#f59e0b" strokeWidth={2} dot={{ r: 2 }} name="EPS (₹)" />
          </ComposedChart>
        );
      }
      case "returns": {
        if (!ratiosRows.length) return "No ROE / ROCE / OPM history available.";
        return (
          <ComposedChart data={ratiosRows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="period" tick={tickAxisStyle} />
            <YAxis tick={tickAxisStyle} unit="%" />
            <Tooltip contentStyle={tooltipContentStyle} formatter={(v: any) => v != null ? `${v}%` : "—"} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line type="monotone" dataKey="roe"  stroke="#10b981" strokeWidth={2} dot={{ r: 2 }} name="ROE %" />
            <Line type="monotone" dataKey="roce" stroke="#6366f1" strokeWidth={2} dot={{ r: 2 }} name="ROCE %" />
            <Line type="monotone" dataKey="opm"  stroke="#f59e0b" strokeWidth={2} dot={{ r: 2 }} name="OPM %" />
          </ComposedChart>
        );
      }
      case "cashflow": {
        if (!cashFlowRows.length) return "No cash flow rows available.";
        return (
          <BarChart data={cashFlowRows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
            <XAxis dataKey="period" tick={tickAxisStyle} />
            <YAxis tick={tickAxisStyle} />
            <Tooltip contentStyle={tooltipContentStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Bar dataKey="cfo" fill="#10b981" name="CFO" />
            <Bar dataKey="cfi" fill="#0ea5e9" name="CFI" />
            <Bar dataKey="cff" fill="#a78bfa" name="CFF" />
          </BarChart>
        );
      }
    }
  };

  const chartHints: Record<ChartType, string> = {
    price:       "Daily Close from yfinance with optional 50/200 DMA overlays and Volume bars on the secondary axis.",
    pe:          "Year-end Price / Yearly EPS. Daily P/E would need TTM-EPS at every date; this is a yearly proxy.",
    salesmargin: "Quarterly Sales (₹ Cr) with OPM% from Screener and NPM% computed as Net Profit / Revenue. GPM% not derivable from current scrape.",
    pbv:         "Year-end Price / latest Book Value per share. Historical per-share BV isn't published by Screener so older years use the latest BV as divisor.",
    evebitda:    "EV ≈ Market Cap (scaled by year-end price ratio) + Borrowings (cash unavailable in our scrape). EBITDA ≈ Operating Profit + Depreciation.",
    mcapsales:   "Year-end Market Cap (scaled from today's MCap by year-end price ratio) / Yearly Revenue.",
    yearly_pl:   "Revenue / Operating Profit / Net Profit in ₹ Cr with EPS on the right axis.",
    returns:     "ROE / ROCE / OPM as reported by Screener.in. All percentages.",
    cashflow:    "Operating / Investing / Financing cash flows in ₹ Cr.",
  };

  return (
    <div className="rounded-lg bg-slate-950/40 border border-slate-850">
      {/* HEADER: chart-type selector */}
      <div className="flex items-center justify-between flex-wrap gap-3 px-4 py-2 border-b border-slate-850">
        <div className="flex items-center gap-1.5 font-mono text-[11px] flex-wrap">
          {PRIMARY_CHARTS.map((c) => (
            <button
              key={c.key}
              onClick={() => { setChartType(c.key); setMoreOpen(false); }}
              className={`px-2.5 py-1 rounded cursor-pointer transition-colors ${
                chartType === c.key
                  ? "bg-indigo-500/20 text-indigo-200 font-bold"
                  : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
              }`}
            >
              {c.label}
            </button>
          ))}
          <div className="relative" ref={moreRef}>
            <button
              onClick={() => setMoreOpen((v) => !v)}
              className={`px-2.5 py-1 rounded cursor-pointer flex items-center gap-1 transition-colors ${
                MORE_CHARTS.find((m) => m.key === chartType)
                  ? "bg-indigo-500/20 text-indigo-200 font-bold"
                  : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
              }`}
            >
              More <span className="text-[8px]">▾</span>
            </button>
            {moreOpen && (
              <div className="absolute right-0 mt-1 z-20 bg-slate-900 border border-slate-700 rounded-lg shadow-lg py-1 min-w-[160px]">
                {MORE_CHARTS.map((c) => (
                  <button
                    key={c.key}
                    onClick={() => { setChartType(c.key); setMoreOpen(false); }}
                    className={`w-full text-left px-3 py-1.5 text-[11px] cursor-pointer ${
                      chartType === c.key
                        ? "text-indigo-200 bg-indigo-500/10"
                        : "text-slate-300 hover:bg-slate-800"
                    }`}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="text-[10px] text-slate-500 font-mono">
          {currentLabel} · {timeframe}
        </div>
      </div>

      {/* CHART HINT */}
      <div className="px-4 pt-2 text-[10px] text-slate-500 font-mono">
        {chartHints[chartType]}
      </div>

      {/* THE CHART */}
      <div className="px-2 pt-1 pb-2">
        <div className="h-72 font-mono text-[10px]">
          {(() => {
            const result = renderChart();
            if (typeof result === "string") {
              return (
                <div className="h-full w-full flex items-center justify-center text-[11px] text-slate-500 font-mono">
                  {result}
                </div>
              );
            }
            return (
              <ResponsiveContainer width="100%" height="100%">
                {result}
              </ResponsiveContainer>
            );
          })()}
        </div>
      </div>

      {/* SERIES TOGGLES (Price view only) */}
      {chartType === "price" && (
        <div className="flex items-center justify-center gap-4 pb-3 text-[10px] font-mono text-slate-400">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={showVolume} onChange={(e) => setShowVolume(e.target.checked)} className="accent-indigo-500" />
            Volume
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={showSma50} onChange={(e) => setShowSma50(e.target.checked)} className="accent-amber-500" />
            50 DMA
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={showSma200} onChange={(e) => setShowSma200(e.target.checked)} className="accent-emerald-500" />
            200 DMA
          </label>
        </div>
      )}
    </div>
  );
};


const FundamentalsDetailPanel: React.FC<{
  stock: FundamentalStock;
  detail?: FundamentalsDetail;
  priceHistory?: FundamentalsPriceHistory;
  loading: boolean;
  timeframe: Timeframe;
  onChangeTimeframe: (tf: Timeframe) => void;
  onRefresh: () => void;
}> = ({ stock, detail, priceHistory, loading, timeframe, onChangeTimeframe, onRefresh }) => {
  if (loading && !detail) {
    return (
      <div className="py-10 text-center text-slate-500 text-xs">
        Fetching Screener.in fundamentals for {stock.ticker}… (first call may take a few seconds)
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="py-10 text-center text-slate-500 text-xs">
        Could not load Screener.in data for {stock.ticker}.
        <button
          onClick={onRefresh}
          className="ml-3 px-2 py-1 rounded border border-slate-700 text-indigo-300 hover:bg-slate-800 cursor-pointer"
        >
          Retry
        </button>
      </div>
    );
  }

  const tr = detail.top_ratios;
  const topRatioCards: { label: string; value: string; hint?: string }[] = [
    { label: "Market Cap",     value: tr.market_cap_cr !== null ? `₹${tr.market_cap_cr.toLocaleString("en-IN")} Cr` : "—" },
    { label: "Stock P/E",      value: fmtNumber(tr.pe) },
    { label: "Industry P/E",   value: fmtNumber(tr.industry_pe) },
    { label: "ROE",            value: tr.roe_pct !== null ? `${tr.roe_pct}%` : "—" },
    { label: "ROCE",           value: tr.roce_pct !== null ? `${tr.roce_pct}%` : "—" },
    { label: "Debt to Equity", value: fmtNumber(tr.debt_equity) },
    { label: "Dividend Yield", value: tr.dividend_yield_pct !== null ? `${tr.dividend_yield_pct}%` : "—" },
    { label: "Book Value",     value: tr.book_value !== null ? `₹${tr.book_value}` : "—", hint: "Per-share book value as reported by Screener.in" },
    { label: "Face Value",     value: tr.face_value !== null ? `₹${tr.face_value}` : "—" },
  ];

  const priceSeries = (priceHistory?.series || []).map((p) => ({
    ts: p.ts.slice(0, 10),
    close: p.close,
    volume: p.volume ?? 0,
  }));

  return (
    <div className="space-y-5">
      {/* HEADER */}
      <div className="flex items-center justify-between flex-wrap gap-3 pb-3 border-b border-slate-850">
        <div>
          <h3 className="text-sm font-bold text-slate-100">
            {stock.ticker}
            <span className="text-[10px] text-slate-500 font-mono ml-2 uppercase">
              {detail.view} view · {detail.fetched_at}
            </span>
          </h3>
          <a
            href={detail.screener_url}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-indigo-300 hover:underline font-mono"
            onClick={(e) => e.stopPropagation()}
          >
            View on Screener.in →
          </a>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* TIMEFRAME SELECTOR — applies to price chart and trims yearly / quarterly panels */}
          <div className="inline-flex items-center bg-slate-900 border border-slate-800 rounded-lg p-0.5 font-mono">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={(e) => { e.stopPropagation(); onChangeTimeframe(tf); }}
                className={`px-2 py-1 text-[10px] rounded cursor-pointer transition-colors ${
                  timeframe === tf
                    ? "bg-indigo-500/20 text-indigo-200 font-bold"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); onRefresh(); }}
            className="px-3 py-1.5 border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-[10px] font-semibold cursor-pointer flex items-center gap-1.5"
            disabled={loading}
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
            {loading ? "Refreshing…" : "Refresh from Screener.in"}
          </button>
        </div>
      </div>

      {detail.warnings && detail.warnings.length > 0 && (
        <div className="p-2 rounded bg-amber-500/10 border border-amber-500/30 text-[10px] text-amber-300 font-mono">
          ⚠ {detail.warnings.join("; ")}
        </div>
      )}

      {/* TOP RATIOS GRID */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        {topRatioCards.map((card) => (
          <div key={card.label} className="p-2.5 rounded-lg bg-slate-950/50 border border-slate-850" title={card.hint || ""}>
            <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">{card.label}</div>
            <div className="text-sm font-mono text-slate-200 mt-0.5">{card.value}</div>
          </div>
        ))}
      </div>

      {/* CHART FAMILIES — Screener.in-style multi-dimensional view */}
      <FundamentalsChartGrid
        detail={detail}
        priceSeries={priceSeries}
        timeframe={timeframe}
        topRatios={tr}
      />

      {/* PROS & CONS */}
      {((detail.pros && detail.pros.length > 0) || (detail.cons && detail.cons.length > 0)) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
            <h4 className="text-[10px] font-bold uppercase tracking-wider text-emerald-300 mb-2">Pros</h4>
            {detail.pros && detail.pros.length > 0 ? (
              <ul className="text-[11px] text-slate-300 space-y-1.5 list-disc pl-4">
                {detail.pros.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            ) : (
              <div className="text-[10px] text-slate-500">None listed.</div>
            )}
          </div>
          <div className="p-3 rounded-lg bg-rose-500/5 border border-rose-500/20">
            <h4 className="text-[10px] font-bold uppercase tracking-wider text-rose-300 mb-2">Cons</h4>
            {detail.cons && detail.cons.length > 0 ? (
              <ul className="text-[11px] text-slate-300 space-y-1.5 list-disc pl-4">
                {detail.cons.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            ) : (
              <div className="text-[10px] text-slate-500">None listed.</div>
            )}
          </div>
        </div>
      )}

      {/* QUARTERLY RESULTS */}
      <SeriesTable
        caption="Quarterly Results (₹ Cr unless stated)"
        rows={[
          { label: "Revenue",          series: detail.quarterly_results.revenue },
          { label: "Operating Profit", series: detail.quarterly_results.operating_profit },
          { label: "Net Profit",       series: detail.quarterly_results.net_profit },
          { label: "EPS",              series: detail.quarterly_results.eps,  unit: "" },
          { label: "OPM",              series: detail.quarterly_results.opm,  unit: "%" },
        ]}
      />

      {/* PROFIT & LOSS */}
      <SeriesTable
        caption="Profit & Loss — Yearly (₹ Cr)"
        rows={[
          { label: "Revenue",          series: detail.profit_loss.revenue },
          { label: "Operating Profit", series: detail.profit_loss.operating_profit },
          { label: "Net Profit",       series: detail.profit_loss.net_profit },
          { label: "EPS (₹)",          series: detail.profit_loss.eps },
        ]}
      />

      {/* BALANCE SHEET */}
      <SeriesTable
        caption="Balance Sheet — Yearly (₹ Cr)"
        rows={[
          { label: "Equity Capital",    series: detail.balance_sheet.equity_capital },
          { label: "Reserves",          series: detail.balance_sheet.reserves },
          { label: "Borrowings",        series: detail.balance_sheet.borrowings },
          { label: "Other Liabilities", series: detail.balance_sheet.other_liabilities },
          { label: "Total Liabilities", series: detail.balance_sheet.total_liabilities },
          { label: "Fixed Assets",      series: detail.balance_sheet.fixed_assets },
          { label: "CWIP",              series: detail.balance_sheet.cwip },
          { label: "Investments",       series: detail.balance_sheet.investments },
          { label: "Other Assets",      series: detail.balance_sheet.other_assets },
          { label: "Total Assets",      series: detail.balance_sheet.total_assets },
        ]}
      />

      {/* CASH FLOW */}
      <SeriesTable
        caption="Cash Flow — Yearly (₹ Cr)"
        rows={[
          { label: "Operating CF",   series: detail.cash_flow.cfo },
          { label: "Investing CF",   series: detail.cash_flow.cfi },
          { label: "Financing CF",   series: detail.cash_flow.cff },
          { label: "Net Cash Flow",  series: detail.cash_flow.net_cash },
        ]}
      />

      {/* RATIOS HISTORY */}
      <SeriesTable
        caption="Ratios — Yearly"
        rows={[
          { label: "ROE",         series: detail.ratios.roe,         unit: "%" },
          { label: "ROCE",        series: detail.ratios.roce,        unit: "%" },
          { label: "OPM",         series: detail.ratios.opm,         unit: "%" },
          { label: "Debtor Days", series: detail.ratios.debtor_days, unit: "" },
        ]}
      />

      {/* SHAREHOLDING PATTERN */}
      {detail.shareholding && detail.shareholding.length > 0 && (
        <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-850">
          <h4 className="text-[10px] font-bold uppercase tracking-wider text-indigo-300 mb-2">Shareholding Pattern (Quarterly)</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] font-mono">
              <thead>
                <tr className="text-slate-500 border-b border-slate-850">
                  <th className="text-left py-1.5 px-2">Holder</th>
                  {detail.shareholding.map((q) => (
                    <th key={q.period} className="text-right py-1.5 px-2 whitespace-nowrap">{q.period}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  ["Promoters %", "promoter_pct"],
                  ["FII %",       "fii_pct"],
                  ["DII %",       "dii_pct"],
                  ["Govt %",      "govt_pct"],
                  ["Public %",    "public_pct"],
                  ["Pledged %",   "pledged_pct"],
                  ["Shareholders","shareholders"],
                ].map(([label, key]) => (
                  <tr key={key} className="border-b border-slate-850/60">
                    <td className="py-1.5 px-2 text-slate-300">{label}</td>
                    {detail.shareholding.map((q) => {
                      const v = (q as any)[key as string];
                      const isShareholderCount = key === "shareholders";
                      return (
                        <td key={`${q.period}-${key}`} className="py-1.5 px-2 text-right text-slate-300 whitespace-nowrap">
                          {v === null || v === undefined
                            ? "—"
                            : isShareholderCount
                            ? v.toLocaleString("en-IN")
                            : `${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}%`}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* CONCALLS / ANNUAL REPORTS / ANNOUNCEMENTS */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="p-3 rounded-lg bg-slate-950/40 border border-slate-850">
          <h4 className="text-[10px] font-bold uppercase tracking-wider text-indigo-300 mb-2">Recent Concalls</h4>
          {detail.concalls && detail.concalls.length > 0 ? (
            <ul className="text-[11px] space-y-1.5">
              {detail.concalls.slice(0, 6).map((c, i) => (
                <li key={i} className="text-slate-300">
                  <span className="text-slate-500 font-mono">{c.date || "—"}</span>{" "}
                  <span className="space-x-2">
                    {c.transcript_url && <a href={c.transcript_url} target="_blank" rel="noreferrer" className="text-indigo-300 hover:underline">Transcript</a>}
                    {c.ppt_url        && <a href={c.ppt_url}        target="_blank" rel="noreferrer" className="text-indigo-300 hover:underline">PPT</a>}
                    {c.notes_url      && <a href={c.notes_url}      target="_blank" rel="noreferrer" className="text-indigo-300 hover:underline">Notes</a>}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-[10px] text-slate-500">No concall links found.</div>
          )}
        </div>
        <div className="p-3 rounded-lg bg-slate-950/40 border border-slate-850">
          <h4 className="text-[10px] font-bold uppercase tracking-wider text-indigo-300 mb-2">Annual Reports</h4>
          {detail.annual_reports && detail.annual_reports.length > 0 ? (
            <ul className="text-[11px] space-y-1.5">
              {detail.annual_reports.slice(0, 8).map((a, i) => (
                <li key={i}>
                  <a href={a.url} target="_blank" rel="noreferrer" className="text-indigo-300 hover:underline">{a.label}</a>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-[10px] text-slate-500">No annual reports listed.</div>
          )}
        </div>
        <div className="p-3 rounded-lg bg-slate-950/40 border border-slate-850">
          <h4 className="text-[10px] font-bold uppercase tracking-wider text-indigo-300 mb-2">Announcements</h4>
          {detail.announcements && detail.announcements.length > 0 ? (
            <ul className="text-[11px] space-y-1 text-slate-300">
              {detail.announcements.slice(0, 8).map((a, i) => (
                <li key={i} className="text-[10px]">• {a}</li>
              ))}
            </ul>
          ) : (
            <div className="text-[10px] text-slate-500">No recent announcements.</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default function App() {
  const [activeTab, setActiveTab] = useState<string>("dashboard");
  const [showLogs, setShowLogs] = useState<boolean>(true);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Bot states
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null);
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary | null>(null);
  const [portfolioCapacity, setPortfolioCapacity] = useState<PortfolioCapacity | null>(null);
  const [openPositions, setOpenPositions] = useState<OpenPosition[]>([]);
  const [closedPositions, setClosedPositions] = useState<ClosedPosition[]>([]);
  const [rawTrades, setRawTrades] = useState<RawTrade[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalSignal[]>([]);
  const [signals, setSignals] = useState<SignalHistory[]>([]);
  
  // Charts
  const [equityCurveData, setEquityCurveData] = useState<EquityCurveResponse | null>(null);
  const [drawdownData, setDrawdownData] = useState<DrawdownPoint[]>([]);

  // News states
  const [newsLeaderboard, setNewsLeaderboard] = useState<NewsLeader[]>([]);
  const [newsHours, setNewsHours] = useState<number>(24);
  const [newsScope, setNewsScope] = useState<string>("universe_with_news");
  const [newsSort, setNewsSort] = useState<string>("n_desc");
  const [tickerSearch, setTickerSearch] = useState<string>("");
  const [tickerNewsFeed, setTickerNewsFeed] = useState<TickerNews[]>([]);
  const [tickerStats, setTickerStats] = useState<any>(null);
  // Per-ticker expansion in the news leaderboard.
  const [newsExpanded, setNewsExpanded] = useState<Set<string>>(new Set());
  const [newsArticlesByTicker, setNewsArticlesByTicker] = useState<Record<string, TickerNews[]>>({});
  const [newsArticlesLoading, setNewsArticlesLoading] = useState<Set<string>>(new Set());
  const [showNewsHelp, setShowNewsHelp] = useState<boolean>(true);

  // Fundamentals states
  const [fundamentals, setFundamentals] = useState<FundamentalStock[]>([]);
  const [fundamentalsSearch, setFundamentalsSearch] = useState<string>("");
  const [fundamentalsExpanded, setFundamentalsExpanded] = useState<Set<string>>(new Set());
  const [fundamentalsDetailByTicker, setFundamentalsDetailByTicker] = useState<Record<string, FundamentalsDetail>>({});
  const [fundamentalsPriceByTicker, setFundamentalsPriceByTicker] = useState<Record<string, FundamentalsPriceHistory>>({});
  const [fundamentalsDetailLoading, setFundamentalsDetailLoading] = useState<Set<string>>(new Set());
  const [fundamentalsPinInput, setFundamentalsPinInput] = useState<string>("");
  const [fundamentalsPins, setFundamentalsPins] = useState<FundamentalsPin[]>([]);
  // Per-ticker active timeframe for the price + ratio charts.
  const [fundamentalsTimeframe, setFundamentalsTimeframe] = useState<Record<string, Timeframe>>({});

  // Analytics states
  const [analyticsSummary, setAnalyticsSummary] = useState<AnalyticsSummary | null>(null);
  const [strategyPerformance, setStrategyPerformance] = useState<StrategyPerformance[]>([]);

  // Research states
  const [researchCandidates, setResearchCandidates] = useState<ResearchCandidate[]>([]);
  const [researchFailures, setResearchFailures] = useState<ResearchFailure[]>([]);
  const [researchSearch, setResearchSearch] = useState<string>("");

  // Observability states
  const [observabilityTotals, setObservabilityTotals] = useState<ObservabilityTotals | null>(null);
  const [observabilityCallers, setObservabilityCallers] = useState<ObservabilityCaller[]>([]);
  const [observabilityDaily, setObservabilityDaily] = useState<ObservabilityDaily[]>([]);
  const [observabilityCalls, setObservabilityCalls] = useState<ObservabilityCall[]>([]);

  // Positional states
  const [positionalStatus, setPositionalStatus] = useState<PositionalStatus | null>(null);
  const [positionalRegime, setPositionalRegime] = useState<PositionalRegime | null>(null);
  const [positionalScanResults, setPositionalScanResults] = useState<PositionalScanResult[]>([]);
  const [positionalResearch, setPositionalResearch] = useState<Record<string, PositionalResearch>>({});
  const [positionalPositions, setPositionalPositions] = useState<PositionalPosition[]>([]);
  const [uploadProgress, setUploadProgress] = useState<string>("");

  // System states
  const [systemLogs, setSystemLogs] = useState<string[]>([]);
  const [logLevelFilter, setLogLevelFilter] = useState<string>("");
  const [botCycles, setBotCycles] = useState<any[]>([]);

  // Parameter form states
  const [paramMaxOpen, setParamMaxOpen] = useState<number>(5);
  const [paramRiskPct, setParamRiskPct] = useState<number>(0.04);
  const [paramStopLoss, setParamStopLoss] = useState<number>(0.05);
  const [paramTakeProfit, setParamTakeProfit] = useState<number>(0.10);
  const [paramMinScore, setParamMinScore] = useState<number>(60.0);

  // CSV file references
  const queryAFileInput = useRef<HTMLInputElement>(null);
  const queryBFileInput = useRef<HTMLInputElement>(null);

  // Notification timer
  useEffect(() => {
    if (successMsg || errorMsg) {
      const timer = setTimeout(() => {
        setSuccessMsg(null);
        setErrorMsg(null);
      }, 6000);
      return () => clearTimeout(timer);
    }
  }, [successMsg, errorMsg]);

  // --- API FETCHERS ---
  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/bot/status`);
      const data: BotStatus = await res.json();
      setBotStatus(data);
      if (data.params) {
        setParamMaxOpen(data.params.max_open_positions);
        setParamRiskPct(data.params.risk_per_trade_pct);
        setParamStopLoss(data.params.stop_loss_pct);
        setParamTakeProfit(data.params.take_profit_pct);
        setParamMinScore(data.params.min_composite_score);
      }
    } catch (e) {
      console.error("Failed to fetch status:", e);
    }
  };

  const fetchPortfolio = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/portfolio/summary`);
      const data: PortfolioSummary = await res.json();
      setPortfolioSummary(data);

      const capRes = await fetch(`${API_BASE}/api/portfolio/capacity`);
      const capData: PortfolioCapacity = await capRes.json();
      setPortfolioCapacity(capData);
    } catch (e) {
      console.error("Failed to fetch portfolio:", e);
    }
  };

  const fetchApprovals = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/approvals`);
      const data: ApprovalSignal[] = await res.json();
      setPendingApprovals(data);
    } catch (e) {
      console.error("Failed to fetch approvals:", e);
    }
  };

  const fetchPositions = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/positions/open`);
      const data: OpenPosition[] = await res.json();
      setOpenPositions(data);
    } catch (e) {
      console.error("Failed to fetch open positions:", e);
    }
  };

  // Triggered on activeTab changes
  useEffect(() => {
    fetchStatus();
    fetchPortfolio();
    fetchApprovals();
    fetchPositions();
  }, [activeTab]);

  // Poll high-priority data periodically
  useEffect(() => {
    const timer = setInterval(() => {
      fetchStatus();
      fetchPortfolio();
      fetchApprovals();
      if (activeTab === "positions" || activeTab === "dashboard") {
        fetchPositions();
      }
    }, 6000);
    return () => clearInterval(timer);
  }, [activeTab]);

  // Dynamic tab content loaders
  useEffect(() => {
    if (activeTab === "dashboard") {
      const fetchCharts = async () => {
        try {
          const resCurve = await fetch(`${API_BASE}/api/portfolio/equity-curve`);
          const curveData: EquityCurveResponse = await resCurve.json();
          setEquityCurveData(curveData);

          const resDD = await fetch(`${API_BASE}/api/portfolio/drawdown`);
          const ddData: DrawdownPoint[] = await resDD.json();
          setDrawdownData(ddData);
        } catch (e) {
          console.error("Failed to fetch charts data:", e);
        }
      };
      fetchCharts();
    }

    if (activeTab === "control") {
      const fetchControlAssets = async () => {
        try {
          const resSig = await fetch(`${API_BASE}/api/signals?limit=30`);
          const sigData = await resSig.json();
          setSignals(sigData);

          const resCyc = await fetch(`${API_BASE}/api/bot/cycles?limit=30`);
          const cycData = await resCyc.json();
          setBotCycles(cycData);
        } catch (e) {
          console.error("Failed to fetch control logs:", e);
        }
      };
      fetchControlAssets();
    }

    if (activeTab === "positions") {
      const fetchClosed = async () => {
        try {
          const resC = await fetch(`${API_BASE}/api/positions/closed`);
          const cData = await resC.json();
          setClosedPositions(cData);

          const resT = await fetch(`${API_BASE}/api/trades/raw`);
          const tData = await resT.json();
          setRawTrades(tData);
        } catch (e) {
          console.error("Failed to fetch position history:", e);
        }
      };
      fetchClosed();
    }

    if (activeTab === "positional" || activeTab === "longterm") {
      const fetchPositionalData = async () => {
        try {
          const resStat = await fetch(`${API_BASE}/api/positional/status`);
          const statData = await resStat.json();
          setPositionalStatus(statData);

          const resReg = await fetch(`${API_BASE}/api/positional/regime`);
          const regData = await resReg.json();
          setPositionalRegime(regData);

          const resScan = await fetch(`${API_BASE}/api/positional/scan-results`);
          const scanData = await resScan.json();
          setPositionalScanResults(scanData);

          try {
            const resRes = await fetch(`${API_BASE}/api/positional/research`);
            const researchData: PositionalResearch[] = await resRes.json();
            const byTicker: Record<string, PositionalResearch> = {};
            (researchData || []).forEach((r) => { byTicker[r.ticker] = r; });
            setPositionalResearch(byTicker);
          } catch { /* research is optional */ }

          const resPos = await fetch(`${API_BASE}/api/positional/positions`);
          const posData = await resPos.json();
          setPositionalPositions(posData);
        } catch (e) {
          console.error("Failed to fetch swing positional:", e);
        }
      };
      fetchPositionalData();
    }

    if (activeTab === "news") {
      const fetchNewsFeed = async () => {
        try {
          const resStats = await fetch(`${API_BASE}/api/news/stats`);
          const statData = await resStats.json();
          setTickerStats(statData);
        } catch (e) {
          console.error("Failed to fetch news stats:", e);
        }
      };
      fetchNewsFeed();
      loadNewsLeaderboard();
    }

    if (activeTab === "fundamentals") {
      loadFundamentalsTable();
      loadFundamentalsPins();
    }

    if (activeTab === "analytics") {
      const fetchAnalytics = async () => {
        try {
          const resS = await fetch(`${API_BASE}/api/analytics/summary`);
          const sData = await resS.json();
          setAnalyticsSummary(sData);

          const resP = await fetch(`${API_BASE}/api/analytics/strategies`);
          const pData = await resP.json();
          setStrategyPerformance(pData);
        } catch (e) {
          console.error("Failed to fetch analytics:", e);
        }
      };
      fetchAnalytics();
    }

    if (activeTab === "research") {
      const fetchResearch = async () => {
        try {
          const resC = await fetch(`${API_BASE}/api/research/candidates`);
          const cData = await resC.json();
          setResearchCandidates(cData);

          const resF = await fetch(`${API_BASE}/api/research/failures`);
          const fData = await resF.json();
          setResearchFailures(fData);
        } catch (e) {
          console.error("Failed to fetch research:", e);
        }
      };
      fetchResearch();
    }

    if (activeTab === "observability") {
      const fetchObs = async () => {
        try {
          const resT = await fetch(`${API_BASE}/api/llm/observability/totals`);
          const tData = await resT.json();
          setObservabilityTotals(tData);

          const resC = await fetch(`${API_BASE}/api/llm/observability/callers`);
          const cData = await resC.json();
          setObservabilityCallers(cData);

          const resD = await fetch(`${API_BASE}/api/llm/observability/daily`);
          const dData = await resD.json();
          setObservabilityDaily(dData);

          const resCalls = await fetch(`${API_BASE}/api/llm/observability/calls`);
          const callsData = await resCalls.json();
          setObservabilityCalls(callsData);
        } catch (e) {
          console.error("Failed to fetch observability:", e);
        }
      };
      fetchObs();
    }

    if (activeTab === "logs") {
      fetchLogs();
    }
  }, [activeTab]);

  // Log updater timer when the logs tab or visibility is on
  useEffect(() => {
    let timer: any = null;
    if (activeTab === "logs") {
      timer = setInterval(() => {
        fetchLogs();
      }, 3000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [activeTab, logLevelFilter]);

  const loadNewsLeaderboard = async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/news/leaderboard?hours=${newsHours}&scope=${newsScope}&sort_by=${newsSort}`
      );
      const data = await res.json();
      setNewsLeaderboard(data);
    } catch (e) {
      console.error("Failed to fetch news leaderboard:", e);
    }
  };

  const lookupTickerNews = async (tickerVal: string) => {
    if (!tickerVal) return;
    try {
      const res = await fetch(`${API_BASE}/api/news/ticker/${tickerVal.toUpperCase()}`);
      const data = await res.json();
      setTickerNewsFeed(data);
    } catch (e) {
      console.error("Failed ticker news search:", e);
    }
  };

  const toggleNewsRow = async (ticker: string) => {
    const upper = ticker.toUpperCase();
    setNewsExpanded((prev) => {
      const next = new Set(prev);
      next.has(upper) ? next.delete(upper) : next.add(upper);
      return next;
    });
    // Lazy-fetch the full article list on first expansion.
    if (!newsArticlesByTicker[upper] && !newsArticlesLoading.has(upper)) {
      setNewsArticlesLoading((prev) => new Set(prev).add(upper));
      try {
        const res = await fetch(`${API_BASE}/api/news/ticker/${upper}`);
        const data: TickerNews[] = await res.json();
        setNewsArticlesByTicker((prev) => ({ ...prev, [upper]: data }));
      } catch (e) {
        console.error(`Failed to load articles for ${upper}:`, e);
      } finally {
        setNewsArticlesLoading((prev) => {
          const next = new Set(prev);
          next.delete(upper);
          return next;
        });
      }
    }
  };

  const loadFundamentalsTable = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/fundamentals?scope=universe`);
      const data = await res.json();
      setFundamentals(data);
    } catch (e) {
      console.error("Failed to fetch fundamentals:", e);
    }
  };

  const loadFundamentalsPins = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/fundamentals/pins`);
      const data = await res.json();
      setFundamentalsPins(data);
    } catch (e) {
      console.error("Failed to load pins:", e);
    }
  };

  const toggleFundamentalsRow = async (ticker: string, opts?: { refresh?: boolean }) => {
    const upper = ticker.toUpperCase();
    const wasOpen = fundamentalsExpanded.has(upper);
    setFundamentalsExpanded((prev) => {
      const next = new Set(prev);
      if (opts?.refresh) {
        next.add(upper);
      } else {
        next.has(upper) ? next.delete(upper) : next.add(upper);
      }
      return next;
    });
    // Only fetch when opening (or explicit refresh) and not already cached.
    const needsFetch = opts?.refresh ||
      (!wasOpen && !fundamentalsDetailByTicker[upper] && !fundamentalsDetailLoading.has(upper));
    if (!needsFetch) return;
    setFundamentalsDetailLoading((prev) => new Set(prev).add(upper));
    try {
      const url = `${API_BASE}/api/fundamentals/detail/${upper}${opts?.refresh ? "?refresh=true" : ""}`;
      const detailRes = await fetch(url);
      if (!detailRes.ok) throw new Error(`Detail HTTP ${detailRes.status}`);
      const detail: FundamentalsDetail = await detailRes.json();
      setFundamentalsDetailByTicker((prev) => ({ ...prev, [upper]: detail }));
      // Pull price history alongside the detail. Don't block the panel
      // render if it fails - the chart panel renders a "no data" message.
      const period = fundamentalsTimeframe[upper] || "5Y";
      try {
        const phRes = await fetch(`${API_BASE}/api/fundamentals/price-history/${upper}?period=${period}`);
        if (phRes.ok) {
          const ph: FundamentalsPriceHistory = await phRes.json();
          setFundamentalsPriceByTicker((prev) => ({ ...prev, [upper]: ph }));
        }
      } catch (e) {
        console.warn(`Price history fetch failed for ${upper}:`, e);
      }
    } catch (e) {
      console.error(`Failed to load fundamentals detail for ${upper}:`, e);
    } finally {
      setFundamentalsDetailLoading((prev) => {
        const next = new Set(prev);
        next.delete(upper);
        return next;
      });
    }
  };

  const pinFundamentalsTicker = async () => {
    const tk = fundamentalsPinInput.trim().toUpperCase().replace(/\.(NS|BO)$/, "");
    if (!tk) return;
    try {
      await fetch(`${API_BASE}/api/fundamentals/pin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: tk }),
      });
      setFundamentalsPinInput("");
      await Promise.all([loadFundamentalsTable(), loadFundamentalsPins()]);
    } catch (e) {
      console.error("Failed to pin ticker:", e);
    }
  };

  const unpinFundamentalsTicker = async (ticker: string) => {
    try {
      await fetch(`${API_BASE}/api/fundamentals/pin/${ticker.toUpperCase()}`, { method: "DELETE" });
      await Promise.all([loadFundamentalsTable(), loadFundamentalsPins()]);
    } catch (e) {
      console.error(`Failed to unpin ${ticker}:`, e);
    }
  };

  const setFundamentalsTimeframeForTicker = async (ticker: string, tf: Timeframe) => {
    const upper = ticker.toUpperCase();
    setFundamentalsTimeframe((prev) => ({ ...prev, [upper]: tf }));
    // Re-fetch the price series at the new window. Yearly / quarterly
    // panels just re-slice in the renderer from cached detail data.
    try {
      const phRes = await fetch(`${API_BASE}/api/fundamentals/price-history/${upper}?period=${tf}`);
      if (phRes.ok) {
        const ph: FundamentalsPriceHistory = await phRes.json();
        setFundamentalsPriceByTicker((prev) => ({ ...prev, [upper]: ph }));
      }
    } catch (e) {
      console.warn(`Timeframe switch fetch failed for ${upper}:`, e);
    }
  };

  const fetchLogs = async () => {
    try {
      const url = logLevelFilter
        ? `${API_BASE}/api/system/logs?limit=400&level=${logLevelFilter}`
        : `${API_BASE}/api/system/logs?limit=400`;
      const res = await fetch(url);
      const data = await res.json();
      setSystemLogs(data.lines || []);
    } catch (e) {
      console.error("Failed to fetch system logs:", e);
    }
  };

  // --- FORM HANDLERS ---
  const handleControlBot = async (targetStatus: string, targetMode?: string) => {
    const actKey = `control_${targetStatus}`;
    setLoading((prev) => ({ ...prev, [actKey]: true }));
    try {
      const res = await fetch(`${API_BASE}/api/bot/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: targetStatus, mode: targetMode || botStatus?.mode }),
      });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg(`Bot successfully set to state: ${targetStatus.toUpperCase()}`);
        fetchStatus();
      } else {
        setErrorMsg("Failed to update bot scheduling state.");
      }
    } catch (e) {
      setErrorMsg("Network error trying to control bot.");
    } finally {
      setLoading((prev) => ({ ...prev, [actKey]: false }));
    }
  };

  const handleUpdateParameters = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading((prev) => ({ ...prev, params: true }));
    try {
      const res = await fetch(`${API_BASE}/api/bot/parameters`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          max_open_positions: paramMaxOpen,
          risk_per_trade_pct: paramRiskPct,
          stop_loss_pct: paramStopLoss,
          take_profit_pct: paramTakeProfit,
          min_composite_score: paramMinScore,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("System portfolio limits updated successfully.");
        fetchStatus();
      } else {
        setErrorMsg("Error saving parameters to SQLite.");
      }
    } catch (e) {
      setErrorMsg("Failed to post configuration updates.");
    } finally {
      setLoading((prev) => ({ ...prev, params: false }));
    }
  };

  const handleTriggerCycle = async () => {
    setLoading((prev) => ({ ...prev, cycle: true }));
    try {
      const res = await fetch(`${API_BASE}/api/bot/cycle/run?force=true`, {
        method: "POST",
      });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("Intraday scanning scan cycle kicked off in backend.");
      } else {
        setErrorMsg("Scan initiation failed.");
      }
    } catch (e) {
      setErrorMsg("Error triggering scanning loop.");
    } finally {
      setLoading((prev) => ({ ...prev, cycle: false }));
    }
  };

  const handleDecideApproval = async (id: number, action: string) => {
    const actKey = `approve_${id}_${action}`;
    setLoading((prev) => ({ ...prev, [actKey]: true }));
    try {
      const res = await fetch(`${API_BASE}/api/approvals/${id}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, note: `Executed via React Dashboard Panel` }),
      });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg(`Approved and submitted ticker successfully.`);
        fetchApprovals();
        fetchPositions();
      } else {
        setErrorMsg(data.message || "Failed to submit approval choice.");
      }
    } catch (e) {
      setErrorMsg("Network error executing choice.");
    } finally {
      setLoading((prev) => ({ ...prev, [actKey]: false }));
    }
  };

  // Re-run the analyst over holdings + watchlist + recent shortlist. force=true
  // bypasses the by-concall cache so it re-summarises with the CURRENT prompts/logic.
  const handleResearchRefresh = async () => {
    setLoading((prev) => ({ ...prev, research_refresh: true }));
    try {
      const res = await fetch(`${API_BASE}/api/positional/research/refresh?force=true`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("Re-running research (cache bypassed) on holdings + watchlist + recent shortlist.");
      } else {
        setErrorMsg(data.detail || "Failed to start research refresh.");
      }
    } catch (e) {
      setErrorMsg("Network error starting research refresh.");
    } finally {
      setLoading((prev) => ({ ...prev, research_refresh: false }));
    }
  };

  // Complete refresh: re-scan the whole universe (regenerate the candidate list) AND
  // force fresh research on every candidate — the full pipeline end to end.
  const handleFullRescan = async () => {
    setLoading((prev) => ({ ...prev, full_rescan: true }));
    try {
      const res = await fetch(`${API_BASE}/api/positional/scan?force=true`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("Full re-scan + research started in the background. Candidates and summaries will update when it finishes (can take several minutes).");
      } else {
        setErrorMsg(data.detail || "Failed to start full re-scan.");
      }
    } catch (e) {
      setErrorMsg("Network error starting full re-scan.");
    } finally {
      setLoading((prev) => ({ ...prev, full_rescan: false }));
    }
  };

  const handleTriggerNewsScrape = async () => {
    setLoading((prev) => ({ ...prev, news_scrape: true }));
    try {
      const res = await fetch(`${API_BASE}/api/news/scrape`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("News scraping & FinBERT analyzer scheduled.");
      } else {
        setErrorMsg("Failed to start scraper.");
      }
    } catch (e) {
      setErrorMsg("Network error scraping RSS feeds.");
    } finally {
      setLoading((prev) => ({ ...prev, news_scrape: false }));
    }
  };

  const handleTriggerNewsRetag = async () => {
    setLoading((prev) => ({ ...prev, news_retag: true }));
    try {
      const res = await fetch(`${API_BASE}/api/news/retag`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("Existing news title parsing scheduled.");
      } else {
        setErrorMsg("Failed to start tag parser.");
      }
    } catch (e) {
      setErrorMsg("Network error retagging.");
    } finally {
      setLoading((prev) => ({ ...prev, news_retag: false }));
    }
  };

  const handleTriggerPositionalExits = async () => {
    setLoading((prev) => ({ ...prev, pos_exits: true }));
    try {
      const res = await fetch(`${API_BASE}/api/positional/exit-check`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("EOD positional exit checks and scan triggered in background.");
      } else {
        setErrorMsg("Failed EOD exit trigger.");
      }
    } catch (e) {
      setErrorMsg("Network error exit checks.");
    } finally {
      setLoading((prev) => ({ ...prev, pos_exits: false }));
    }
  };

  const handleRunRegimeCheck = async () => {
    setLoading((prev) => ({ ...prev, regime: true }));
    try {
      const res = await fetch(`${API_BASE}/api/positional/regime/run`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("Market regime recomputation started in the background. The panel will refresh once it finishes.");
      } else {
        setErrorMsg(data.detail || "Failed to start regime recomputation.");
      }
    } catch (e) {
      setErrorMsg("Network error starting regime recomputation.");
    } finally {
      setLoading((prev) => ({ ...prev, regime: false }));
    }
  };

  const handleTogglePositionalConfig = async (field: "llm" | "swap") => {
    if (!positionalStatus) return;
    const newLlm = field === "llm" ? !positionalStatus.llm_research_enabled : !!positionalStatus.llm_research_enabled;
    const newSwap = field === "swap" ? !positionalStatus.swap_enabled : !!positionalStatus.swap_enabled;
    try {
      const response = await fetch(`${API_BASE}/api/positional/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm_research_enabled: newLlm,
          swap_enabled: newSwap,
        }),
      });
      if (response.ok) {
        setPositionalStatus({
          ...positionalStatus,
          llm_research_enabled: newLlm,
          swap_enabled: newSwap,
        });
        setSuccessMsg(`Positional configuration updated successfully.`);
      } else {
        setErrorMsg("Failed to update positional strategy configuration.");
      }
    } catch (error) {
      console.error("Error updating positional strategy config:", error);
      setErrorMsg("Network error updating configuration.");
    }
  };

  const handleTestTelegram = async () => {
    setLoading((prev) => ({ ...prev, telegram: true }));
    try {
      const res = await fetch(`${API_BASE}/api/positional/alerts/test`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("Test notification successfully fired to Telegram channel!");
      } else {
        setErrorMsg("Telegram alert configuration error.");
      }
    } catch (e) {
      setErrorMsg("Failed to dispatch test notification.");
    } finally {
      setLoading((prev) => ({ ...prev, telegram: false }));
    }
  };

  const handleUploadUniverse = async (e: React.FormEvent) => {
    e.preventDefault();
    const fileA = queryAFileInput.current?.files?.[0];
    const fileB = queryBFileInput.current?.files?.[0];

    if (!fileA || !fileB) {
      setErrorMsg("Both Query A (Non-financials) and Query B (Banks/NBFCs) files must be selected!");
      return;
    }

    setUploadProgress("Deduplicating and processing files on the backend...");
    setLoading((prev) => ({ ...prev, upload: true }));

    const formData = new FormData();
    formData.append("query_a", fileA);
    formData.append("query_b", fileB);

    try {
      const res = await fetch(`${API_BASE}/api/positional/universe/upload`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg(
          `Merged & Whitelisted: Combined ${data.result.total_rows} tickers. Passed: ${data.result.passed}, Failed: ${data.result.failed}.`
        );
        const resScan = await fetch(`${API_BASE}/api/positional/scan-results`);
        const scanData = await resScan.json();
        setPositionalScanResults(scanData);
      } else {
        setErrorMsg(data.detail || "Merge failed on the backend.");
      }
    } catch (err) {
      setErrorMsg("Network error attempting multi-part CSV uploads.");
    } finally {
      setUploadProgress("");
      setLoading((prev) => ({ ...prev, upload: false }));
      if (queryAFileInput.current) queryAFileInput.current.value = "";
      if (queryBFileInput.current) queryBFileInput.current.value = "";
    }
  };

  const isBotActive = botStatus?.status === "RUNNING";
  const marketOpenState = botStatus?.market_open;
  
  const formatINR = (val: number | undefined) => {
    if (val === undefined || isNaN(val)) return "₹0.00";
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 2
    }).format(val);
  };

  const getPnlColor = (pnl: number) => {
    if (pnl > 0) return "text-emerald-400 font-semibold";
    if (pnl < 0) return "text-rose-500 font-semibold";
    return "text-slate-400";
  };

  const getBadgeColor = (flag: string | undefined) => {
    if (!flag) return "bg-slate-800 text-slate-300 border border-slate-700";
    const f = flag.toUpperCase();
    if (f === "BULLISH" || f === "RUNNING" || f === "SUCCESS" || f === "APPROVED" || f === "TAKEN") {
      return "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
    }
    if (f === "BEARISH" || f === "STOPPED" || f === "FAILED" || f === "REJECTED" || f === "DANGER") {
      return "bg-rose-500/10 text-rose-400 border border-rose-500/20";
    }
    if (f === "NEUTRAL" || f === "PAUSED" || f === "PENDING" || f === "CACHED") {
      return "bg-amber-500/10 text-amber-400 border border-amber-500/20";
    }
    return "bg-slate-800/50 text-slate-300 border border-slate-700/50";
  };

  return (
    <div className="flex h-screen bg-[#040814] overflow-hidden text-slate-300">
      {/* --- SIDEBAR --- */}
      <aside className="w-64 flex-shrink-0 glass-panel border-r border-slate-800 flex flex-col justify-between">
        <div>
          {/* LOGO */}
          <div className="p-6 border-b border-slate-800/80 flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg grad-primary flex items-center justify-center active-pulse">
              <Activity size={18} className="text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-200 to-purple-400 m-0 leading-none">
                Antigravity NSE
              </h1>
              <span className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">
                Virtual Brokerage Engine
              </span>
            </div>
          </div>

          {/* ACTIVE STATUS INDICATOR PANEL */}
          <div className="p-4 mx-3 my-4 rounded-xl bg-slate-900/50 border border-slate-800/50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-slate-500">Scheduler Bot:</span>
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isBotActive ? "bg-emerald-400 active-pulse" : "bg-rose-500 danger-pulse"
                  }`}
                />
                <span className={`text-xs font-semibold ${isBotActive ? "text-emerald-400" : "text-rose-400"}`}>
                  {botStatus?.status || "LOADING..."}
                </span>
              </div>
            </div>

            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-slate-500">Market Clock:</span>
              <span className="text-xs text-slate-300 font-mono">{botStatus?.market_time_ist || "—"}</span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">Exchange State:</span>
              <span
                className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                  marketOpenState
                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                    : "bg-slate-800 text-slate-400 border border-slate-700"
                }`}
              >
                {marketOpenState ? "OPEN" : "CLOSED"}
              </span>
            </div>
          </div>

          {/* SIDEBAR NAVIGATION ITEMS */}
          <nav className="px-3 space-y-1">
            <button
              onClick={() => setActiveTab("dashboard")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "dashboard"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <PieChart size={16} />
              Overview Dashboard
            </button>

            <button
              onClick={() => setActiveTab("control")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 relative ${
                activeTab === "control"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <Sliders size={16} />
              Control Center
              {pendingApprovals.length > 0 && (
                <span className="absolute right-3 bg-rose-500 text-white text-[10px] px-1.5 py-0.5 rounded-full font-bold active-pulse">
                  {pendingApprovals.length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab("positions")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "positions"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <DollarSign size={16} />
              Active Positions
            </button>

            <button
              onClick={() => setActiveTab("positional")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "positional"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <Layers size={16} />
              Swing Positional
            </button>

            <button
              onClick={() => setActiveTab("longterm")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "longterm"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <TrendingUp size={16} />
              Long-Term
            </button>

            <button
              onClick={() => setActiveTab("news")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "news"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <Newspaper size={16} />
              NLP News Sentiment
            </button>

            <button
              onClick={() => setActiveTab("fundamentals")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "fundamentals"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <Shield size={16} />
              Fundamentals
            </button>

            <button
              onClick={() => setActiveTab("analytics")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "analytics"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <TrendingUp size={16} />
              Performance Stats
            </button>

            <button
              onClick={() => setActiveTab("observability")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "observability"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <Cpu size={16} />
              LLM Observability
            </button>

            <button
              onClick={() => setActiveTab("research")}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                activeTab === "research"
                  ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                  : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
              }`}
            >
              <BookOpen size={16} />
              Research Pipeline
            </button>

            {showLogs && (
              <button
                onClick={() => setActiveTab("logs")}
                className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                  activeTab === "logs"
                    ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                    : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
                }`}
              >
                <FileText size={16} />
                Telemetry Logs
              </button>
            )}
          </nav>
        </div>

        {/* LOG VISIBILITY TOGGLE SWITCH */}
        <div className="p-4 border-t border-slate-800/80">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500 font-medium">Show Logs Tab</span>
            <button
              onClick={() => {
                setShowLogs(!showLogs);
                if (showLogs && activeTab === "logs") {
                  setActiveTab("dashboard");
                }
              }}
              className={`w-11 h-6 rounded-full transition-colors relative focus:outline-none ${
                showLogs ? "bg-indigo-600" : "bg-slate-800"
              }`}
            >
              <span
                className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${
                  showLogs ? "left-6" : "left-1"
                }`}
              />
            </button>
          </div>
        </div>
      </aside>

      {/* --- MAIN MAIN FRAME --- */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* --- DYNAMIC HEADER --- */}
        <header className="h-16 border-b border-slate-800/80 bg-slate-950/40 backdrop-blur-md flex items-center justify-between px-8 flex-shrink-0 z-10">
          <div>
            <h2 className="text-lg font-bold text-slate-200 capitalize m-0">
              {activeTab === "news" ? "NLP News Sentiment Hub" : activeTab === "positional" ? "Minervini VCP Positional Model" : activeTab + " view"}
            </h2>
          </div>

          {/* Quick Stats Banner */}
          <div className="flex items-center gap-6">
            {portfolioSummary && (
              <>
                <div className="text-right hidden sm:block">
                  <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">
                    Total Account Value
                  </div>
                  <div className="text-sm font-bold text-indigo-300 font-mono">
                    {formatINR(portfolioSummary.live_total_value || portfolioSummary.total_value)}
                  </div>
                </div>

                <div className="text-right hidden md:block border-l border-slate-800 pl-6">
                  <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">
                    Active Cash Pool
                  </div>
                  <div className="text-sm font-bold text-slate-300 font-mono">
                    {formatINR(portfolioSummary.cash)}
                  </div>
                </div>

                <div className="text-right border-l border-slate-800 pl-6">
                  <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">
                    Today's UnPnL
                  </div>
                  <div className={`text-sm font-bold font-mono ${getPnlColor(portfolioSummary.live_unrealized_pnl || 0)}`}>
                    {portfolioSummary.live_unrealized_pnl && portfolioSummary.live_unrealized_pnl >= 0 ? "+" : ""}
                    {formatINR(portfolioSummary.live_unrealized_pnl || 0)}
                  </div>
                </div>
              </>
            )}

            <button
              onClick={() => setActiveTab(activeTab)}
              className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 rounded-lg transition-colors border border-slate-850"
            >
              <RefreshCw size={14} className={loading[activeTab] ? "animate-spin" : ""} />
            </button>
          </div>
        </header>

        {/* --- GLOBAL APP TOAST MESSAGE BANNER --- */}
        {(successMsg || errorMsg) && (
          <div className="absolute bottom-6 right-6 z-50">
            <div
              className={`p-4 rounded-xl shadow-2xl flex items-center gap-3 border ${
                successMsg
                  ? "bg-emerald-950/95 text-emerald-200 border-emerald-500/30 shadow-emerald-500/10 animate-slideIn"
                  : "bg-rose-950/95 text-rose-200 border-rose-500/30 shadow-rose-500/10 animate-slideIn"
              }`}
            >
              {successMsg ? <CheckCircle size={18} className="text-emerald-400" /> : <AlertTriangle size={18} className="text-rose-400" />}
              <span className="text-xs font-semibold">{successMsg || errorMsg}</span>
            </div>
          </div>
        )}

        {/* --- MAIN PAGE COMPONENT ROUTER --- */}
        <div className="flex-1 overflow-y-auto p-8">
          {/* ==================== 1. OVERVIEW DASHBOARD ==================== */}
          {activeTab === "dashboard" && (
            <div className="space-y-8 animate-fadeIn">
              {/* TOP KPI GRID */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <div className="glass-panel p-6 rounded-2xl glass-panel-hover flex flex-col justify-between h-32 relative overflow-hidden">
                  <div className="flex items-center justify-between text-slate-500">
                    <span className="text-xs font-semibold uppercase tracking-wider">Net Realized Margin</span>
                    <TrendingUp size={16} className="text-indigo-400" />
                  </div>
                  <div className="mt-2">
                    <span className={`text-2xl font-bold font-mono ${getPnlColor(portfolioSummary?.realized_pnl || 0)}`}>
                      {formatINR(portfolioSummary?.realized_pnl || 0)}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500 mt-1">Settled round-trip metrics</div>
                </div>

                <div className="glass-panel p-6 rounded-2xl glass-panel-hover flex flex-col justify-between h-32 relative overflow-hidden">
                  <div className="flex items-center justify-between text-slate-500">
                    <span className="text-xs font-semibold uppercase tracking-wider">Unrealized Live Margin</span>
                    <TrendingDown size={16} className="text-purple-400" />
                  </div>
                  <div className="mt-2">
                    <span className={`text-2xl font-bold font-mono ${getPnlColor(portfolioSummary?.live_unrealized_pnl || 0)}`}>
                      {formatINR(portfolioSummary?.live_unrealized_pnl || 0)}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500 mt-1">Live ticker margins status</div>
                </div>

                <div className="glass-panel p-6 rounded-2xl glass-panel-hover flex flex-col justify-between h-32 relative overflow-hidden">
                  <div className="flex items-center justify-between text-slate-500">
                    <span className="text-xs font-semibold uppercase tracking-wider">Positions Capacity Slots</span>
                    <Sliders size={16} className="text-amber-400" />
                  </div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-2xl font-bold text-slate-100 font-mono">
                      {portfolioCapacity?.active_slots || 0}
                    </span>
                    <span className="text-sm text-slate-500">/ {portfolioCapacity?.max_slots || 5}</span>
                  </div>
                  {portfolioCapacity && (
                    <div className="w-full bg-slate-800 rounded-full h-1.5 mt-2">
                      <div
                        className="grad-primary h-1.5 rounded-full"
                        style={{ width: `${portfolioCapacity.ratio * 100}%` }}
                      />
                    </div>
                  )}
                </div>

                <div className="glass-panel p-6 rounded-2xl glass-panel-hover flex flex-col justify-between h-32 relative overflow-hidden">
                  <div className="flex items-center justify-between text-slate-500">
                    <span className="text-xs font-semibold uppercase tracking-wider">Intraday Active Holdings</span>
                    <Activity size={16} className="text-emerald-400 animate-pulse" />
                  </div>
                  <div className="mt-2">
                    <span className="text-2xl font-bold text-slate-100 font-mono">{openPositions.length}</span>
                  </div>
                  <div className="text-[10px] text-slate-500 mt-1">Active automated positions open</div>
                </div>
              </div>

              {/* CHARTS CONTAINER */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* 1. EQUITY CURVE (2 cols) */}
                <div className="glass-panel p-6 rounded-2xl lg:col-span-2 space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                        Synchronized Account Growth
                      </h3>
                      <span className="text-xs text-slate-500">Comparative performance vs Nifty 50 benchmark</span>
                    </div>
                  </div>

                  <div className="h-80 w-full font-mono text-[10px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={equityCurveData?.portfolio || []}
                        margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                      >
                        <defs>
                          <linearGradient id="colorPort" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#6366f1" stopOpacity={0.2} />
                            <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                        <XAxis dataKey="ts_ist" stroke="#475569" />
                        <YAxis stroke="#475569" domain={["auto", "auto"]} />
                        <Tooltip
                          contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }}
                        />
                        <Area
                          type="monotone"
                          dataKey="portfolio_value"
                          name="Bot Portfolio Value"
                          stroke="#6366f1"
                          strokeWidth={2}
                          fillOpacity={1}
                          fill="url(#colorPort)"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* 2. RISK DRAWDOWN LEVEL CHART (1 col) */}
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                      Portfolio High Drawdowns
                    </h3>
                    <span className="text-xs text-slate-500">Continuous peak-to-trough risk tracking</span>
                  </div>

                  <div className="h-80 w-full font-mono text-[10px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={drawdownData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                          <linearGradient id="colorDD" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                        <XAxis dataKey="ts_ist" stroke="#475569" />
                        <YAxis stroke="#475569" domain={["auto", 0]} />
                        <Tooltip
                          contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }}
                        />
                        <Area
                          type="monotone"
                          dataKey="drawdown_pct"
                          name="Drawdown %"
                          stroke="#ef4444"
                          strokeWidth={1.5}
                          fillOpacity={1}
                          fill="url(#colorDD)"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>

              {/* CURRENT LIVE HOLDINGS MINI GRID */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Live Holdings Fastboard
                  </h3>
                  <span className="text-xs text-slate-500">{openPositions.length} trades currently scanning</span>
                </div>

                {openPositions.length === 0 ? (
                  <div className="p-8 text-center border border-dashed border-slate-800 rounded-xl text-slate-500 text-xs">
                    No active intraday positions currently running. Use the Control Center to audit signals.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {openPositions.map((pos) => (
                      <div key={pos.id} className="p-5 rounded-xl bg-slate-950/60 border border-slate-800/80">
                        <div className="flex items-center justify-between">
                          <div className="flex items-baseline gap-2">
                            <span className="text-sm font-bold text-slate-200">{pos.ticker}</span>
                            <span
                              className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                                pos.side.toUpperCase() === "LONG" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                              }`}
                            >
                              {pos.side}
                            </span>
                          </div>
                          <span className={`text-xs font-mono font-bold ${getPnlColor(pos.unrealized_pnl)}`}>
                            {pos.unrealized_pnl >= 0 ? "+" : ""}
                            {pos.unrealized_pnl_pct.toFixed(2)}%
                          </span>
                        </div>

                        <div className="grid grid-cols-2 gap-y-2 mt-4 text-xs font-mono border-t border-slate-850 pt-3">
                          <div className="text-slate-500">Entry Price:</div>
                          <div className="text-right text-slate-300">{formatINR(pos.entry_price)}</div>
                          <div className="text-slate-500">Current Ltp:</div>
                          <div className="text-right text-slate-300 font-bold">{formatINR(pos.current_price)}</div>
                          <div className="text-slate-500">Unrealized:</div>
                          <div className={`text-right ${getPnlColor(pos.unrealized_pnl)}`}>
                            {pos.unrealized_pnl >= 0 ? "+" : ""}
                            {formatINR(pos.unrealized_pnl)}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ==================== 2. CONTROL CENTER ==================== */}
          {activeTab === "control" && (
            <div className="space-y-8 animate-fadeIn">
              {/* TRIGGER TRIGGERS / STATUS CONTROL */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* STATUS TOGGLE */}
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Engine Master Switches
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    Trigger master halts, execute manual square-offs, or restart the automated scheduling runner loop.
                  </p>

                  <div className="flex flex-col gap-3 pt-2">
                    {botStatus?.status === "STOPPED" ? (
                      <button
                        onClick={() => handleControlBot("running")}
                        disabled={loading["control_running"]}
                        className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-bold bg-emerald-600 hover:bg-emerald-500 text-white transition-all shadow-lg shadow-emerald-600/10 cursor-pointer text-xs"
                      >
                        <Play size={14} />
                        {loading["control_running"] ? "INITIALIZING..." : "START RUNNER LOOP"}
                      </button>
                    ) : (
                      <button
                        onClick={() => handleControlBot("stopped")}
                        disabled={loading["control_stopped"]}
                        className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-bold bg-rose-600 hover:bg-rose-500 text-white transition-all shadow-lg shadow-rose-600/10 cursor-pointer text-xs"
                      >
                        <Pause size={14} />
                        {loading["control_stopped"] ? "HALTING..." : "HALT RUNNER LOOP"}
                      </button>
                    )}

                    <div className="grid grid-cols-2 gap-3">
                      <button
                        onClick={() => handleControlBot(botStatus?.status || "RUNNING", "auto")}
                        className={`py-2 px-3 rounded-lg text-[10px] font-semibold border ${
                          botStatus?.mode === "auto"
                            ? "bg-indigo-500/10 border-indigo-500 text-indigo-400 font-bold"
                            : "bg-slate-900 border-slate-800 text-slate-400 hover:bg-slate-800"
                        }`}
                      >
                        Fully Auto Mode
                      </button>

                      <button
                        onClick={() => handleControlBot(botStatus?.status || "RUNNING", "semi-auto")}
                        className={`py-2 px-3 rounded-lg text-[10px] font-semibold border ${
                          botStatus?.mode === "semi-auto"
                            ? "bg-indigo-500/10 border-indigo-500 text-indigo-400 font-bold"
                            : "bg-slate-900 border-slate-800 text-slate-400 hover:bg-slate-800"
                        }`}
                      >
                        Semi-Auto VETO
                      </button>
                    </div>
                  </div>
                </div>

                {/* FORCE RUN INTRADAY CYCLE */}
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Background Scanning Engine
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    Instantly command the scanner to trigger a full sweep over whitelists, scraping live quotes to identify setups.
                  </p>
                  <div className="pt-2">
                    <button
                      onClick={handleTriggerCycle}
                      disabled={loading["cycle"]}
                      className="w-full py-3 px-4 rounded-xl font-bold grad-primary hover:opacity-90 text-white transition-all shadow-lg shadow-indigo-600/20 cursor-pointer flex items-center justify-center gap-2 text-xs"
                    >
                      <RefreshCw size={14} className={loading["cycle"] ? "animate-spin" : ""} />
                      {loading["cycle"] ? "RUNNING CYCLE..." : "FORCE INTRADAY CYCLE"}
                    </button>
                  </div>
                  {botStatus?.last_cycle && (
                    <div className="mt-2 p-3 rounded-lg bg-slate-900/60 border border-slate-800/80 text-[11px] font-mono space-y-1">
                      <div className="text-slate-500 uppercase tracking-wider text-[9px] mb-1 font-bold">
                        Last Cycle Summary
                      </div>
                      <div className="flex justify-between">
                        <span>Triggered:</span>
                        <span className="text-slate-300 font-bold">{botStatus.last_cycle.triggered_by}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Ended:</span>
                        <span className="text-slate-300 font-bold">{botStatus.last_cycle.finished_at_ist}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Result:</span>
                        <span
                          className={`font-bold ${
                            botStatus.last_cycle.status === "SUCCESS" ? "text-emerald-400" : "text-rose-400"
                          }`}
                        >
                          {botStatus.last_cycle.status}
                        </span>
                      </div>
                    </div>
                  )}
                </div>

                {/* BOT SYSTEM PARAMETERS FORM */}
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Portfolio Limits Config
                  </h3>
                  <form onSubmit={handleUpdateParameters} className="space-y-3 pt-1">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                          Max Holdings
                        </label>
                        <input
                          type="number"
                          value={paramMaxOpen}
                          onChange={(e) => setParamMaxOpen(parseInt(e.target.value))}
                          className="w-full mt-1 bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                          required
                        />
                      </div>
                      <div>
                        <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                          Risk / Trade (%)
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={paramRiskPct}
                          onChange={(e) => setParamRiskPct(parseFloat(e.target.value))}
                          className="w-full mt-1 bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                          required
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                          Stop Loss (%)
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={paramStopLoss}
                          onChange={(e) => setParamStopLoss(parseFloat(e.target.value))}
                          className="w-full mt-1 bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                          required
                        />
                      </div>
                      <div>
                        <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                          Take Profit (%)
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={paramTakeProfit}
                          onChange={(e) => setParamTakeProfit(parseFloat(e.target.value))}
                          className="w-full mt-1 bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                          required
                        />
                      </div>
                    </div>

                    <div>
                      <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                        Min Composite VETO Score
                      </label>
                      <input
                        type="number"
                        step="0.1"
                        value={paramMinScore}
                        onChange={(e) => setParamMinScore(parseFloat(e.target.value))}
                        className="w-full mt-1 bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                        required
                      />
                    </div>

                    <button
                      type="submit"
                      disabled={loading["params"]}
                      className="w-full mt-2 py-2 px-4 rounded-lg font-bold border border-slate-800 hover:bg-slate-900 text-slate-300 text-xs transition-colors cursor-pointer"
                    >
                      {loading["params"] ? "SAVING..." : "SAVE METRICS CONSTRAINTS"}
                    </button>
                  </form>
                </div>
              </div>

              {/* APPROVALS QUEUE CARDS DECK */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <div className="flex items-baseline gap-2">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                      VETO Approvals Decision Deck
                    </h3>
                    <span className="text-xs text-slate-500 font-medium">({pendingApprovals.length} pending)</span>
                  </div>
                  <span className="text-[10px] text-amber-500/80 font-bold bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-full">
                    Awaiting Manual Decision
                  </span>
                </div>

                {pendingApprovals.length === 0 ? (
                  <div className="p-8 text-center border border-dashed border-slate-800 rounded-xl text-slate-500 text-xs font-mono">
                    Approval Queue is empty. Automated engine is currently scanning or trading in Auto mode.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {pendingApprovals.map((appr) => (
                      <div
                        key={appr.id}
                        className="p-5 rounded-xl bg-slate-950/60 border border-slate-800 flex flex-col justify-between"
                      >
                        <div className="space-y-4">
                          <div className="flex items-center justify-between">
                            <div className="flex items-baseline gap-2">
                              <span className="text-lg font-bold text-slate-200">{appr.ticker}</span>
                              <span
                                className={`text-[10px] font-mono px-2 py-0.5 rounded ${
                                  appr.side.toUpperCase() === "LONG" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                                }`}
                              >
                                {appr.side}
                              </span>
                            </div>
                            <span className="text-xs text-slate-500 font-mono">
                              Expires in: <strong className="text-rose-400 font-bold">{appr.remaining_seconds}s</strong>
                            </span>
                          </div>

                          <div className="grid grid-cols-3 gap-4 border-y border-slate-900 py-3 text-xs font-mono">
                            <div>
                              <div className="text-slate-500 text-[10px] uppercase">Est Quantity:</div>
                              <div className="text-slate-300 font-bold mt-1">{appr.quantity}</div>
                            </div>
                            <div>
                              <div className="text-slate-500 text-[10px] uppercase">Target Entry:</div>
                              <div className="text-slate-300 font-bold mt-1">{formatINR(appr.price)}</div>
                            </div>
                            <div>
                              <div className="text-slate-500 text-[10px] uppercase">Veto Score:</div>
                              <div className="text-indigo-400 font-bold mt-1">{appr.composite_score}</div>
                            </div>
                          </div>

                          <div className="text-xs space-y-1">
                            <span className="text-slate-500 uppercase tracking-wider text-[9px] font-bold block">
                              Scanning Analysis Reason:
                            </span>
                            <p className="text-slate-300 leading-relaxed font-mono text-[11px]">{appr.reason}</p>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3 mt-5">
                          <button
                            onClick={() => handleDecideApproval(appr.id, "reject")}
                            disabled={loading[`approve_${appr.id}_reject`]}
                            className="py-2.5 px-4 rounded-lg bg-rose-950/40 border border-rose-500/30 text-rose-400 font-semibold text-xs transition-colors hover:bg-rose-900/40 cursor-pointer flex items-center justify-center gap-1.5"
                          >
                            <XCircle size={14} />
                            REJECT ENTRY
                          </button>

                          <button
                            onClick={() => handleDecideApproval(appr.id, "approve")}
                            disabled={loading[`approve_${appr.id}_approve`]}
                            className="py-2.5 px-4 rounded-lg bg-emerald-950/40 border border-emerald-500/30 text-emerald-400 font-semibold text-xs transition-colors hover:bg-emerald-900/40 cursor-pointer flex items-center justify-center gap-1.5"
                          >
                            <CheckCircle size={14} />
                            APPROVE TICKER
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* RAW SIGNALS HISTORY AUDIT GRID */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="glass-panel p-6 rounded-2xl lg:col-span-2">
                  <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                      Veto Signals History Feed
                    </h3>
                    <span className="text-xs text-slate-500">Live scanning alerts</span>
                  </div>

                  <div className="overflow-x-auto max-h-[350px] overflow-y-auto pr-1">
                    <table className="w-full text-xs font-mono text-left border-collapse">
                      <thead>
                        <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                          <th className="py-2 px-3">Timestamp</th>
                          <th className="py-2 px-3">Ticker</th>
                          <th className="py-2 px-3">Technical Score</th>
                          <th className="py-2 px-3">Fund Score</th>
                          <th className="py-2 px-3 text-center">Composite</th>
                          <th className="py-2 px-3">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-850">
                        {signals.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="py-8 text-center text-slate-500">
                              No signals found.
                            </td>
                          </tr>
                        ) : (
                          signals.map((sig) => (
                            <tr key={sig.id} className="hover:bg-slate-900/20">
                              <td className="py-2 px-3 text-slate-400">{sig.ts}</td>
                              <td className="py-2 px-3 text-slate-200 font-bold">{sig.ticker}</td>
                              <td className="py-2 px-3 text-slate-300">{sig.technical_score}</td>
                              <td className="py-2 px-3 text-emerald-400">{sig.fundamental_score}</td>
                              <td className="py-2 px-3 text-center text-indigo-400 font-bold">{sig.composite_score}</td>
                              <td className="py-2 px-3">
                                <span className={`px-2 py-0.5 rounded-full text-[9px] ${getBadgeColor(sig.taken ? "TAKEN" : "PENDING")}`}>
                                  {sig.taken ? "TAKEN" : "DEFERRED"}
                                </span>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* BOT CYCLES AUDIT TRAILS */}
                <div className="glass-panel p-6 rounded-2xl">
                  <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                      Schedulers Cycle Audit Trails
                    </h3>
                    <span className="text-xs text-slate-500">Loop audits</span>
                  </div>

                  <div className="space-y-4 max-h-[350px] overflow-y-auto pr-1">
                    {botCycles.length === 0 ? (
                      <div className="p-4 text-center text-slate-500 font-mono text-xs">No cycle logs yet.</div>
                    ) : (
                      botCycles.map((cyc) => (
                        <div key={cyc.id} className="p-3 rounded-lg bg-slate-950/60 border border-slate-850 font-mono text-[10px] space-y-1.5">
                          <div className="flex justify-between border-b border-slate-900 pb-1">
                            <span className="font-bold text-slate-300">Cycle #{cyc.id}</span>
                            <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${getBadgeColor(cyc.status)}`}>
                              {cyc.status}
                            </span>
                          </div>
                          <div className="text-slate-400">Triggered: <span className="text-slate-200">{cyc.triggered_by}</span></div>
                          <div className="text-slate-400">Finished: <span className="text-slate-200">{to_ist_str(cyc.finished_at)}</span></div>
                          {cyc.summary && cyc.summary.actions_taken !== undefined && (
                            <div className="text-indigo-400 font-semibold mt-1">
                              Actions: {cyc.summary.actions_taken} orders processed
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ==================== 3. ACTIVE POSITIONS ==================== */}
          {activeTab === "positions" && (
            <div className="space-y-8 animate-fadeIn">
              {/* CURRENT OPEN POSITIONS TABLE */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Live Account Holdings Table
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">({openPositions.length} active positions)</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4 text-center">Side</th>
                        <th className="py-3 px-4 text-right">Quantity</th>
                        <th className="py-3 px-4 text-right">Entry Price</th>
                        <th className="py-3 px-4 text-right">Last Price</th>
                        <th className="py-3 px-4 text-right">Stop Loss</th>
                        <th className="py-3 px-4 text-right">Take Profit</th>
                        <th className="py-3 px-4 text-right">Live Unrealized PNL</th>
                        <th className="py-3 px-4 text-right">Live UnPnL %</th>
                        <th className="py-3 px-4">Strategy</th>
                        <th className="py-3 px-4 text-center">Score</th>
                        <th className="py-3 px-4">Entered At</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {openPositions.length === 0 ? (
                        <tr>
                          <td colSpan={12} className="py-8 text-center text-slate-500">
                            No holdings are currently running.
                          </td>
                        </tr>
                      ) : (
                        openPositions.map((pos) => (
                          <tr key={pos.id} className="hover:bg-slate-900/20">
                            <td className="py-3 px-4 text-slate-200 font-bold">{pos.ticker}</td>
                            <td className="py-3 px-4 text-center">
                              <span
                                className={`px-1.5 py-0.5 rounded text-[9px] ${
                                  pos.side.toUpperCase() === "LONG" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                                }`}
                              >
                                {pos.side}
                              </span>
                            </td>
                            <td className="py-3 px-4 text-right text-slate-300">{pos.quantity}</td>
                            <td className="py-3 px-4 text-right text-slate-300">{formatINR(pos.entry_price)}</td>
                            <td className="py-3 px-4 text-right text-slate-100 font-bold">{formatINR(pos.current_price)}</td>
                            <td className="py-3 px-4 text-right text-rose-400">
                              {pos.stop_loss ? formatINR(pos.stop_loss) : "—"}
                            </td>
                            <td className="py-3 px-4 text-right text-emerald-400">
                              {pos.take_profit ? formatINR(pos.take_profit) : "—"}
                            </td>
                            <td className={`py-3 px-4 text-right ${getPnlColor(pos.unrealized_pnl)}`}>
                              {pos.unrealized_pnl >= 0 ? "+" : ""}
                              {formatINR(pos.unrealized_pnl)}
                            </td>
                            <td className={`py-3 px-4 text-right ${getPnlColor(pos.unrealized_pnl)}`}>
                              {pos.unrealized_pnl >= 0 ? "+" : ""}
                              {pos.unrealized_pnl_pct.toFixed(2)}%
                            </td>
                            <td className="py-3 px-4 text-slate-400">{pos.strategy}</td>
                            <td className="py-3 px-4 text-center text-indigo-400">{pos.composite_score}</td>
                            <td className="py-3 px-4 text-slate-500">{pos.entered_at}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* CLOSED TRADES ARCHIVE */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Realized Closed Trades Ledger
                  </h3>
                  <span className="text-xs text-slate-500">History of round-trip executions</span>
                </div>

                <div className="overflow-x-auto max-h-[300px]">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px] sticky top-0 bg-[#080d21]">
                        <th className="py-2 px-3">Ticker</th>
                        <th className="py-2 px-3 text-center">Direction</th>
                        <th className="py-2 px-3 text-right">Qty</th>
                        <th className="py-2 px-3 text-right">Avg Entry</th>
                        <th className="py-2 px-3 text-right">Avg Exit</th>
                        <th className="py-2 px-3 text-right">PNL</th>
                        <th className="py-2 px-3 text-right">Return %</th>
                        <th className="py-2 px-3">Opened At</th>
                        <th className="py-2 px-3">Closed At</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {closedPositions.length === 0 ? (
                        <tr>
                          <td colSpan={9} className="py-8 text-center text-slate-500">
                            No closed trades on ledger.
                          </td>
                        </tr>
                      ) : (
                        closedPositions.map((pos, idx) => (
                          <tr key={idx} className="hover:bg-slate-900/20">
                            <td className="py-2 px-3 text-slate-200 font-bold">{pos.ticker}</td>
                            <td className="py-2 px-3 text-center">
                              <span
                                className={`px-1.5 py-0.5 rounded text-[9px] ${
                                  pos.side.toUpperCase() === "LONG" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                                }`}
                              >
                                {pos.side}
                              </span>
                            </td>
                            <td className="py-2 px-3 text-right text-slate-400">{pos.quantity}</td>
                            <td className="py-2 px-3 text-right text-slate-400">{formatINR(pos.entry_price)}</td>
                            <td className="py-2 px-3 text-right text-slate-300">
                              {pos.exit_price ? formatINR(pos.exit_price) : "—"}
                            </td>
                            <td className={`py-2 px-3 text-right ${getPnlColor(pos.pnl)}`}>
                              {pos.pnl >= 0 ? "+" : ""}
                              {formatINR(pos.pnl)}
                            </td>
                            <td className={`py-2 px-3 text-right ${getPnlColor(pos.pnl)}`}>
                              {pos.pnl >= 0 ? "+" : ""}
                              {pos.pnl_pct.toFixed(2)}%
                            </td>
                            <td className="py-2 px-3 text-slate-500">{pos.opened_at}</td>
                            <td className="py-2 px-3 text-slate-500">{pos.closed_at}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* RAW TRANSACTIONS FILLS LEDGER */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Fills Transactions Audit Ledger
                  </h3>
                  <span className="text-xs text-slate-500">Database fill logs</span>
                </div>

                <div className="overflow-x-auto max-h-[300px]">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px] sticky top-0 bg-[#080d21]">
                        <th className="py-2 px-3">Fill ID</th>
                        <th className="py-2 px-3">Timestamp</th>
                        <th className="py-2 px-3">Ticker</th>
                        <th className="py-2 px-3">Side</th>
                        <th className="py-2 px-3 text-right">Fill Qty</th>
                        <th className="py-2 px-3 text-right">Fill Price</th>
                        <th className="py-2 px-3 text-right">Gross value</th>
                        <th className="py-2 px-3">Reason</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {rawTrades.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="py-8 text-center text-slate-500">
                            No fills found on SQLite database ledger.
                          </td>
                        </tr>
                      ) : (
                        rawTrades.map((tr) => (
                          <tr key={tr.id} className="hover:bg-slate-900/20">
                            <td className="py-2 px-3 text-slate-500">#{tr.id}</td>
                            <td className="py-2 px-3 text-slate-400">{tr.ts}</td>
                            <td className="py-2 px-3 text-slate-200 font-bold">{tr.ticker}</td>
                            <td className="py-2 px-3">
                              <span
                                className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                                  tr.side.toUpperCase() === "BUY" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                                }`}
                              >
                                {tr.side}
                              </span>
                            </td>
                            <td className="py-2 px-3 text-right text-slate-300">{tr.quantity}</td>
                            <td className="py-2 px-3 text-right text-slate-300">{formatINR(tr.price)}</td>
                            <td className="py-2 px-3 text-right text-slate-100">{formatINR(tr.value)}</td>
                            <td className="py-2 px-3 text-slate-400 max-w-[180px] truncate">{tr.reason}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ==================== 4. SWING POSITIONAL ==================== */}
          {activeTab === "positional" && (
            <div className="space-y-8 animate-fadeIn">
              {/* SWING CAPITAL POOL & MARKET REGIME SUMMARY */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Positional Capital Pool Allocation
                  </h3>

                  {positionalStatus && (
                    <div className="space-y-3 font-mono text-xs">
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Isolated Fund Pool:</span>
                        <span className="text-indigo-400 font-bold">{formatINR(positionalStatus.initial_capital)}</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Allocated Exposure:</span>
                        <span className="text-slate-300 font-bold">{formatINR(positionalStatus.allocated_value)}</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Unallocated Cash:</span>
                        <span className="text-emerald-400 font-bold">{formatINR(positionalStatus.cash_balance)}</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Accumulated Return:</span>
                        <span className={`font-bold ${getPnlColor(positionalStatus.net_realized_pnl)}`}>
                          {positionalStatus.net_realized_pnl >= 0 ? "+" : ""}
                          {formatINR(positionalStatus.net_realized_pnl)}
                        </span>
                      </div>
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Exposure Capacity:</span>
                        <span className="text-slate-300 font-bold">
                          {positionalStatus.active_positions_count} / {positionalStatus.max_positions} slots
                        </span>
                      </div>
                      <div className="flex items-center justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">LLM VCP Research:</span>
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              positionalStatus.llm_research_enabled
                                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                : "bg-slate-800 text-slate-400 border border-slate-700"
                            }`}
                          >
                            {positionalStatus.llm_research_enabled ? "ON (Ollama)" : "OFF (Tech Only)"}
                          </span>
                          <button
                            onClick={() => handleTogglePositionalConfig("llm")}
                            className={`w-8 h-4.5 rounded-full transition-colors relative focus:outline-none ${
                              positionalStatus.llm_research_enabled ? "bg-indigo-600" : "bg-slate-800"
                            }`}
                          >
                            <span
                              className={`w-3 h-3 rounded-full bg-white absolute top-[3px] transition-all duration-150 ${
                                positionalStatus.llm_research_enabled ? "left-[17px]" : "left-[3px]"
                              }`}
                            />
                          </button>
                        </div>
                      </div>
                      <div className="flex items-center justify-between pt-1">
                        <span className="text-slate-500">Opportunity Swaps:</span>
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              positionalStatus.swap_enabled
                                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                : "bg-slate-800 text-slate-400 border border-slate-700"
                            }`}
                          >
                            {positionalStatus.swap_enabled ? "ACTIVE" : "DISABLED"}
                          </span>
                          <button
                            onClick={() => handleTogglePositionalConfig("swap")}
                            className={`w-8 h-4.5 rounded-full transition-colors relative focus:outline-none ${
                              positionalStatus.swap_enabled ? "bg-indigo-600" : "bg-slate-800"
                            }`}
                          >
                            <span
                              className={`w-3 h-3 rounded-full bg-white absolute top-[3px] transition-all duration-150 ${
                                positionalStatus.swap_enabled ? "left-[17px]" : "left-[3px]"
                              }`}
                            />
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    EOD Macro Regime Index
                  </h3>
                  {positionalRegime && (
                    <div className="space-y-3 font-mono text-xs">
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Market State regime:</span>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${getBadgeColor(positionalRegime.flag)}`}>
                          {positionalRegime.flag}
                        </span>
                      </div>
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Size Multiplier:</span>
                        <span className="text-indigo-400 font-bold">{Math.round(positionalRegime.size_multiplier * 100)}%</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Nifty ROC 18M:</span>
                        <span className="text-slate-300 font-bold">{(positionalRegime.nifty_roc_18m * 100).toFixed(1)}%</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Smallcap ROC 20M:</span>
                        <span className="text-slate-300 font-bold">{(positionalRegime.smallcap_roc_20m * 100).toFixed(1)}%</span>
                      </div>
                      <div className="flex justify-between pt-1">
                        <span className="text-slate-500">Regime Computed At:</span>
                        <span className="text-slate-400 text-[10px]">{positionalRegime.computed_at}</span>
                      </div>
                    </div>
                  )}
                  <button
                    onClick={handleRunRegimeCheck}
                    disabled={loading["regime"]}
                    title="Recompute the monthly macro market regime now (Nifty/Smallcap ROC, size multiplier). Runs in the background; normally auto-runs on the first trading days of the month."
                    className="w-full py-2.5 px-4 rounded-xl border border-slate-800 hover:bg-slate-900 text-slate-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <Activity size={14} className={loading["regime"] ? "animate-spin" : ""} />
                    {loading["regime"] ? "RECOMPUTING REGIME..." : "RECOMPUTE MARKET REGIME"}
                  </button>
                </div>

                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Model Ops & Alerts Test
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    Instantly command the backend to run EOD sweep scans or test Telegram setups.
                  </p>

                  <div className="space-y-3 pt-2">
                    <button
                      onClick={handleTriggerPositionalExits}
                      disabled={loading["pos_exits"]}
                      className="w-full py-2.5 px-4 rounded-xl border border-slate-800 hover:bg-slate-900 text-slate-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <RefreshCw size={14} className={loading["pos_exits"] ? "animate-spin" : ""} />
                      {loading["pos_exits"] ? "RUNNING EOD EXIT CHECKS..." : "RUN EOD EXIT CHECKS"}
                    </button>

                    <button
                      onClick={handleTestTelegram}
                      disabled={loading["telegram"]}
                      className="w-full py-2.5 px-4 rounded-xl border border-slate-800 hover:bg-slate-900 text-slate-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <Sparkles size={14} />
                      {loading["telegram"] ? "DISPATCHING..." : "TEST TELEGRAM NOTIFICATION"}
                    </button>
                  </div>
                </div>
              </div>

              {/* DUAL CSV MERGER & UPLOADER */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center gap-3 mb-4 border-b border-slate-800/80 pb-3">
                  <Upload size={18} className="text-indigo-400 animate-pulse" />
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                      Screener.in Dual CSV Whitelist Uploader
                    </h3>
                    <span className="text-xs text-slate-500">
                      Upload both exported tables together; the server processes, deduplicates, and whitelists them automatically.
                    </span>
                  </div>
                </div>

                <form onSubmit={handleUploadUniverse} className="space-y-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* QUERY A (NON-FINANCIALS) */}
                    <div className="p-5 rounded-xl bg-slate-950/60 border border-slate-850 hover:border-slate-800 transition-colors flex flex-col items-center justify-center text-center cursor-pointer relative">
                      <div className="w-10 h-10 rounded-full bg-indigo-500/10 flex items-center justify-center mb-3">
                        <FileText size={18} className="text-indigo-400" />
                      </div>
                      <span className="text-xs font-semibold text-slate-300">
                        Query A: Standard Non-Financial Stocks
                      </span>
                      <p className="text-[10px] text-slate-500 mt-1 max-w-[200px]">
                        Exported screener CSV representing classic VCP setups (excludes banks & NBFCs).
                      </p>
                      <input
                        type="file"
                        accept=".csv"
                        ref={queryAFileInput}
                        className="mt-4 text-xs font-mono file:bg-slate-900 file:border-none file:text-slate-300 file:px-3 file:py-1 file:rounded-md file:text-[10px] file:font-semibold text-slate-400 cursor-pointer"
                        required
                      />
                    </div>

                    {/* QUERY B (BANKS & NBFCS) */}
                    <div className="p-5 rounded-xl bg-slate-950/60 border border-slate-850 hover:border-slate-800 transition-colors flex flex-col items-center justify-center text-center cursor-pointer relative">
                      <div className="w-10 h-10 rounded-full bg-purple-500/10 flex items-center justify-center mb-3">
                        <Shield size={18} className="text-purple-400" />
                      </div>
                      <span className="text-xs font-semibold text-slate-300 text-center">
                        Query B: Banks & Financial Institutions
                      </span>
                      <p className="text-[10px] text-slate-500 mt-1 max-w-[200px]">
                        Exported screener CSV containing columns tailored for bank debt metrics.
                      </p>
                      <input
                        type="file"
                        accept=".csv"
                        ref={queryBFileInput}
                        className="mt-4 text-xs font-mono file:bg-slate-900 file:border-none file:text-slate-300 file:px-3 file:py-1 file:rounded-md file:text-[10px] file:font-semibold text-slate-400 cursor-pointer"
                        required
                      />
                    </div>
                  </div>

                  {uploadProgress && (
                    <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 text-[10px] font-mono text-center text-indigo-400 animate-pulse">
                      {uploadProgress}
                    </div>
                  )}

                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={loading["upload"]}
                      className="py-3 px-6 rounded-xl font-bold grad-primary hover:opacity-90 text-white text-xs transition-all shadow-lg shadow-indigo-600/20 flex items-center gap-1.5 cursor-pointer"
                    >
                      <Upload size={14} />
                      {loading["upload"] ? "PROCESSING MERGES..." : "MERGE & UPDATE SWING WHITELISTS"}
                    </button>
                  </div>
                </form>
              </div>

              {/* ACTIVE SWING POSITIONS TABLE (EMA 21 TRACKER) */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Active Multi-Strategy Positional Positions (EMA Trail Tracker)
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">({positionalPositions.length} active holdings)</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4 text-center">Strategy</th>
                        <th className="py-3 px-4">Entry Date</th>
                        <th className="py-3 px-4 text-right">Holdings Qty</th>
                        <th className="py-3 px-4 text-right">Avg Entry</th>
                        <th className="py-3 px-4 text-right">Ltp</th>
                        <th className="py-3 px-4 text-right">Hard Stop</th>
                        <th className="py-3 px-4 text-right">21 EMA Trail</th>
                        <th className="py-3 px-4 text-right">Peak High</th>
                        <th className="py-3 px-4 text-center">Below EMA Days</th>
                        <th className="py-3 px-4 text-right">Hold Days</th>
                        <th className="py-3 px-4 text-right">UnPnL</th>
                        <th className="py-3 px-4 text-right">UnPnL %</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {positionalPositions.length === 0 ? (
                        <tr>
                          <td colSpan={13} className="py-8 text-center text-slate-500">
                            No swing holdings are currently active.
                          </td>
                        </tr>
                      ) : (
                        positionalPositions.map((pos) => (
                          <tr key={pos.id} className="hover:bg-slate-900/20">
                            <td className="py-3 px-4 text-slate-200 font-bold">{pos.ticker}</td>
                            <td className="py-3 px-4 text-center">
                              {renderStrategyBadge(pos.strategy || "MINERVINI_VCP")}
                            </td>
                            <td className="py-3 px-4 text-slate-400">{pos.entry_date}</td>
                            <td className="py-3 px-4 text-right text-slate-300">{pos.quantity}</td>
                            <td className="py-3 px-4 text-right text-slate-300">{formatINR(pos.entry_price)}</td>
                            <td className="py-3 px-4 text-right text-slate-100 font-bold">{formatINR(pos.current_price)}</td>
                            <td className="py-3 px-4 text-right text-rose-400">{formatINR(pos.hard_stop)}</td>
                            <td className="py-3 px-4 text-right text-purple-400">
                              {pos.ema_trail_stop ? formatINR(pos.ema_trail_stop) : "—"}
                            </td>
                            <td className="py-3 px-4 text-right text-emerald-400">
                              {pos.peak_price ? formatINR(pos.peak_price) : "—"}
                            </td>
                            <td className="py-3 px-4 text-center">
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                  pos.below_ema_consecutive > 0
                                    ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                                    : "bg-slate-850 text-slate-400"
                                }`}
                              >
                                {pos.below_ema_consecutive} days
                              </span>
                            </td>
                            <td className="py-3 px-4 text-right text-slate-400">{pos.days_held} days</td>
                            <td className={`py-3 px-4 text-right ${getPnlColor(pos.unrealized_pnl)}`}>
                              {pos.unrealized_pnl >= 0 ? "+" : ""}
                              {formatINR(pos.unrealized_pnl)}
                            </td>
                            <td className={`py-3 px-4 text-right ${getPnlColor(pos.unrealized_pnl)}`}>
                              {pos.unrealized_pnl >= 0 ? "+" : ""}
                              {pos.unrealized_pnl_pct.toFixed(2)}%
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* SCAN CANDIDATES GRID — swing horizons only (POSITIONAL / BOTH); LONG_TERM lives in its own tab */}
              <div className="flex items-center justify-end gap-2 mb-3">
                <button
                  onClick={handleResearchRefresh}
                  disabled={loading["research_refresh"] || loading["full_rescan"]}
                  title="Re-summarise holdings + watchlist + recent shortlist with the current prompts (bypasses the concall cache). No universe re-scan."
                  className="py-2 px-3 rounded-lg border border-slate-800 hover:bg-slate-900 text-slate-300 font-semibold text-[11px] cursor-pointer flex items-center gap-1.5 transition-colors"
                >
                  <RefreshCw size={13} className={loading["research_refresh"] ? "animate-spin" : ""} />
                  {loading["research_refresh"] ? "RE-RUNNING..." : "RE-RUN RESEARCH"}
                </button>
                <button
                  onClick={handleFullRescan}
                  disabled={loading["full_rescan"] || loading["research_refresh"]}
                  title="Re-scan the entire universe to regenerate the candidate list AND force fresh research on every candidate. Full pipeline; can take several minutes."
                  className="py-2 px-3 rounded-lg border border-indigo-700/60 bg-indigo-600/10 hover:bg-indigo-600/20 text-indigo-300 font-semibold text-[11px] cursor-pointer flex items-center gap-1.5 transition-colors"
                >
                  <RefreshCw size={13} className={loading["full_rescan"] ? "animate-spin" : ""} />
                  {loading["full_rescan"] ? "RE-SCANNING..." : "FULL RE-SCAN + RESEARCH"}
                </button>
              </div>
              <PositionalScanTable
                rows={positionalScanResults.filter((s) => s.horizon === "POSITIONAL" || s.horizon === "BOTH" || !s.horizon)}
                research={positionalResearch}
                variant="swing"
              />
              <p className="text-[11px] text-slate-500 mt-3">
                Click any row to expand the analyst thesis (positives, risks, guidance, sources). Long-term-only candidates
                appear under the <span className="text-amber-400 font-semibold">Long-Term</span> tab.
                <span className="text-slate-400"> Made prompt/logic changes? Use <b>Full Re-Scan + Research</b> to rebuild the candidate list and re-run every summary.</span>
              </p>
            </div>
          )}

          {/* ==================== LONG-TERM (durability-led candidates) ==================== */}
          {activeTab === "longterm" && (
            <div className="space-y-8 animate-fadeIn">
              <div className="glass-panel p-6 rounded-2xl flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0 mb-1">
                    Long-Term Accumulation
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed max-w-3xl">
                    Durable businesses surfaced by the scorecard's Axis-B (quality, valuation, management outlook). These have
                    strong fundamentals but no current swing trigger (or are <span className="text-emerald-400">BOTH</span> — also a swing setup).
                    They are <span className="text-slate-300">researched but never auto-bought</span> as positional trades. Click a row for the analyst thesis.
                  </p>
                </div>
                <div className="shrink-0 flex flex-col gap-2">
                  <button
                    onClick={handleResearchRefresh}
                    disabled={loading["research_refresh"] || loading["full_rescan"]}
                    title="Re-summarise holdings + watchlist + recent shortlist with the current prompts (bypasses the concall cache). No universe re-scan."
                    className="py-2.5 px-4 rounded-xl border border-slate-800 hover:bg-slate-900 text-slate-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <RefreshCw size={14} className={loading["research_refresh"] ? "animate-spin" : ""} />
                    {loading["research_refresh"] ? "RE-RUNNING..." : "RE-RUN RESEARCH"}
                  </button>
                  <button
                    onClick={handleFullRescan}
                    disabled={loading["full_rescan"] || loading["research_refresh"]}
                    title="Re-scan the entire universe to regenerate the candidate list AND force fresh research on every candidate. Full pipeline; can take several minutes."
                    className="py-2.5 px-4 rounded-xl border border-indigo-700/60 bg-indigo-600/10 hover:bg-indigo-600/20 text-indigo-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <RefreshCw size={14} className={loading["full_rescan"] ? "animate-spin" : ""} />
                    {loading["full_rescan"] ? "RE-SCANNING..." : "FULL RE-SCAN + RESEARCH"}
                  </button>
                </div>
              </div>

              <PositionalScanTable
                rows={positionalScanResults.filter((s) => s.horizon === "LONG_TERM" || s.horizon === "BOTH")}
                research={positionalResearch}
                variant="longterm"
              />
            </div>
          )}

          {/* ==================== 5. NLP NEWS SENTIMENT ==================== */}
          {activeTab === "news" && (
            <div className="space-y-8 animate-fadeIn">
              {/* RSS SCRAPER TRIGGER BUTTONS & LEADERBOARD CONTROLS */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* RE-SCAN NEWS SCRAPER */}
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    RSS Scrapers & NLP Model Refreshes
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    Instruct NLP scrapers to download recent RSS headlines and evaluate sentiment values.
                  </p>

                  <div className="grid grid-cols-2 gap-3 pt-2">
                    <button
                      onClick={handleTriggerNewsScrape}
                      disabled={loading["news_scrape"]}
                      className="py-2.5 px-4 rounded-xl border border-slate-800 hover:bg-slate-900 text-slate-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <RefreshCw size={14} className={loading["news_scrape"] ? "animate-spin" : ""} />
                      {loading["news_scrape"] ? "SCRAPING..." : "RUN SCRAPERS"}
                    </button>

                    <button
                      onClick={handleTriggerNewsRetag}
                      disabled={loading["news_retag"]}
                      className="py-2.5 px-4 rounded-xl border border-slate-800 hover:bg-slate-900 text-slate-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <Sliders size={14} />
                      {loading["news_retag"] ? "RETAGGING..." : "RE-TAG SYMBOLS"}
                    </button>
                  </div>
                </div>

                {/* HISTORICAL SENTIMENT STATS */}
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Headlines Stats Inventory
                  </h3>
                  {tickerStats ? (
                    <div className="space-y-3 font-mono text-xs">
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Total Scraped Stories:</span>
                        <span className="text-slate-300 font-bold">{tickerStats.total_news}</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Scored Sentiments:</span>
                        <span className="text-emerald-400 font-bold">{tickerStats.scored_news}</span>
                      </div>
                      <div className="flex justify-between pt-1">
                        <span className="text-slate-500">Last Scraper Run:</span>
                        <span className="text-slate-400 text-[10px]">
                          {tickerStats.last_ts ? to_ist_str(tickerStats.last_ts) : "—"}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-slate-500 text-xs font-mono py-4 text-center">Loading NLP stats...</div>
                  )}
                </div>

                {/* INDIVIDUAL TICKER SENTIMENT DRILLDOWN */}
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Individual Ticker Drilldown
                  </h3>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="e.g. INFY, RELIANCE"
                      value={tickerSearch}
                      onChange={(e) => setTickerSearch(e.target.value)}
                      className="flex-1 bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono uppercase"
                    />
                    <button
                      onClick={() => lookupTickerNews(tickerSearch)}
                      className="px-3 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-lg text-xs font-semibold cursor-pointer"
                    >
                      LOOKUP
                    </button>
                  </div>
                  <span className="text-[10px] text-slate-500 block">Searches SQLite for ticker sentiment logs.</span>
                </div>
              </div>

              {/* TICKER LOOKUP DRILLDOWN DETAILS (CONDITIONAL) */}
              {tickerNewsFeed.length > 0 && (
                <div className="glass-panel p-6 rounded-2xl animate-fadeIn">
                  <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-indigo-400 m-0">
                      Historical sentiment Feed for {tickerSearch.toUpperCase()}
                    </h3>
                    <button
                      onClick={() => setTickerNewsFeed([])}
                      className="text-xs text-slate-500 hover:text-slate-300 underline font-semibold"
                    >
                      Clear Feed
                    </button>
                  </div>

                  <div className="space-y-4 max-h-[350px] overflow-y-auto pr-2">
                    {tickerNewsFeed.map((news, idx) => (
                      <div key={idx} className="p-4 rounded-xl bg-slate-950/60 border border-slate-850">
                        <div className="flex items-baseline justify-between gap-4">
                          <h4 className="text-xs font-bold text-slate-200">
                            <a href={news.url} target="_blank" rel="noreferrer" className="hover:underline text-indigo-300">
                              {news.title}
                            </a>
                          </h4>
                          <span
                            className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold shrink-0 ${
                              news.sentiment && news.sentiment >= 0.05
                                ? "bg-emerald-500/10 text-emerald-400"
                                : news.sentiment && news.sentiment <= -0.05
                                ? "bg-rose-500/10 text-rose-400"
                                : "bg-slate-800 text-slate-400"
                            }`}
                          >
                            {news.sentiment !== null ? news.sentiment.toFixed(3) : "NEUTRAL"}
                          </span>
                        </div>
                        <p className="text-slate-400 text-[11px] mt-2 font-mono">{news.summary}</p>
                        <div className="flex items-center gap-3 mt-3 text-[10px] text-slate-500 font-mono">
                          <span>{news.source}</span>
                          <span>•</span>
                          <span>{news.ts}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* RECENCY DECAY SENTIMENT LEADERBOARD */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3 flex-wrap gap-4">
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0 flex items-center gap-2">
                      Recency-Decay Sentiment Leaderboard
                      <button
                        type="button"
                        onClick={() => setShowNewsHelp((v) => !v)}
                        className="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-400 hover:text-indigo-300 hover:border-indigo-500/40 cursor-pointer"
                        title="Toggle column definitions"
                      >
                        {showNewsHelp ? "Hide help" : "What do these columns mean?"}
                      </button>
                    </h3>
                    <span className="text-xs text-slate-500">
                      Weighted score decay: recent headlines weigh exponentially more. Click any row to see every article scored for that ticker.
                    </span>
                  </div>

                  {/* FILTER CONTROLS */}
                  <div className="flex items-center gap-3 flex-wrap font-mono text-[10px]">
                    <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-1.5">
                      <span className="text-slate-500 mr-2 uppercase">Hours:</span>
                      <select
                        value={newsHours}
                        onChange={(e) => setNewsHours(parseInt(e.target.value))}
                        className="bg-transparent border-none text-slate-300 focus:outline-none focus:ring-0 cursor-pointer"
                      >
                        <option value={24} className="bg-[#0b1021]">24h</option>
                        <option value={48} className="bg-[#0b1021]">48h</option>
                        <option value={72} className="bg-[#0b1021]">72h</option>
                      </select>
                    </div>

                    <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-1.5">
                      <span className="text-slate-500 mr-2 uppercase">Scope:</span>
                      <select
                        value={newsScope}
                        onChange={(e) => setNewsScope(e.target.value)}
                        className="bg-transparent border-none text-slate-300 focus:outline-none focus:ring-0 cursor-pointer"
                      >
                        <option value="universe_with_news" className="bg-[#0b1021]">Full Universe</option>
                        <option value="open_positions" className="bg-[#0b1021]">Open Holdings</option>
                        <option value="min_three" className="bg-[#0b1021]">Minimum 3 articles</option>
                      </select>
                    </div>

                    <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-1.5">
                      <span className="text-slate-500 mr-2 uppercase">Sort:</span>
                      <select
                        value={newsSort}
                        onChange={(e) => setNewsSort(e.target.value)}
                        className="bg-transparent border-none text-slate-300 focus:outline-none focus:ring-0 cursor-pointer"
                      >
                        <option value="n_desc" className="bg-[#0b1021]">Articles Volume</option>
                        <option value="avg_desc" className="bg-[#0b1021]">Highest Sentiment</option>
                        <option value="avg_asc" className="bg-[#0b1021]">Lowest Sentiment</option>
                        <option value="ts_desc" className="bg-[#0b1021]">Latest update</option>
                      </select>
                    </div>

                    <button
                      onClick={loadNewsLeaderboard}
                      className="p-2 border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg cursor-pointer"
                    >
                      APPLY
                    </button>
                  </div>
                </div>

                {showNewsHelp && (
                  <div className="mb-4 grid grid-cols-1 md:grid-cols-3 gap-3 text-[11px] font-mono">
                    <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-800">
                      <div className="text-indigo-300 font-bold uppercase tracking-wider text-[10px] mb-1">Breakdown</div>
                      <div className="text-slate-400">
                        Article counts in the window split as <span className="text-emerald-400">positive</span> /{" "}
                        <span className="text-slate-300">neutral</span> /{" "}
                        <span className="text-rose-400">negative</span>. A score ≥ +0.05 counts as positive, ≤ −0.05 as negative.
                      </div>
                    </div>
                    <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-800">
                      <div className="text-indigo-300 font-bold uppercase tracking-wider text-[10px] mb-1">Unweighted Avg</div>
                      <div className="text-slate-400">
                        Plain arithmetic mean of every article&rsquo;s sentiment score (−1 to +1). Old and fresh headlines count the same.
                      </div>
                    </div>
                    <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-800">
                      <div className="text-indigo-300 font-bold uppercase tracking-wider text-[10px] mb-1">Decay Weighted Avg</div>
                      <div className="text-slate-400">
                        Same mean, but each article is weighted by an exponential half-life ≈ window/4 (≈6h for a 24h view). Recent news dominates.
                      </div>
                    </div>
                  </div>
                )}

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4 w-6"></th>
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4">Sector Type</th>
                        <th className="py-3 px-4 text-center" title="Total articles tagged to this ticker in the selected time window.">Article Count</th>
                        <th className="py-3 px-4 text-center" title="Positive / Neutral / Negative article counts. Positive = score ≥ +0.05, Negative = ≤ −0.05.">Breakdown</th>
                        <th className="py-3 px-4 text-center" title="Plain arithmetic mean of all article sentiment scores. Range −1 to +1.">Unweighted Avg</th>
                        <th className="py-3 px-4 text-center" title="Recency-weighted mean (exponential half-life ≈ window/4). Old headlines fade out.">Decay Weighted Avg</th>
                        <th className="py-3 px-4">Latest Headline Scored</th>
                        <th className="py-3 px-4">Scored Date</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {newsLeaderboard.length === 0 ? (
                        <tr>
                          <td colSpan={9} className="py-8 text-center text-slate-500">
                            No matching headlines sentiment logs found in this period.
                          </td>
                        </tr>
                      ) : (
                        newsLeaderboard.map((newsItem, idx) => {
                          const open = newsExpanded.has(newsItem.ticker);
                          const articles = newsArticlesByTicker[newsItem.ticker] || [];
                          const isLoadingArticles = newsArticlesLoading.has(newsItem.ticker);
                          return (
                            <React.Fragment key={`${newsItem.ticker}-${idx}`}>
                              <tr
                                className="hover:bg-slate-900/20 cursor-pointer"
                                onClick={() => toggleNewsRow(newsItem.ticker)}
                              >
                                <td className="py-3 px-4 text-slate-500 text-center w-6">{open ? "▾" : "▸"}</td>
                                <td className="py-3 px-4 text-slate-200 font-bold flex items-center gap-1.5">
                                  {newsItem.ticker}
                                  {newsItem.is_open_position && (
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 active-pulse" title="Holding active" />
                                  )}
                                </td>
                                <td className="py-3 px-4 text-slate-400">{newsItem.sector}</td>
                                <td className="py-3 px-4 text-center text-slate-300">{newsItem.articles}</td>
                                <td className="py-3 px-4 text-center text-slate-500">{newsItem.breakdown}</td>
                                <td className="py-3 px-4 text-center text-slate-300">{newsItem.avg_sentiment.toFixed(3)}</td>
                                <td
                                  className={`py-3 px-4 text-center font-bold ${
                                    newsItem.weighted_sentiment >= 0.05
                                      ? "text-emerald-400"
                                      : newsItem.weighted_sentiment <= -0.05
                                      ? "text-rose-500"
                                      : "text-slate-400"
                                  }`}
                                >
                                  {newsItem.weighted_sentiment.toFixed(3)}
                                </td>
                                <td className="py-3 px-4 text-slate-400 max-w-[220px] truncate">
                                  <a
                                    href={newsItem.latest_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="hover:underline"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    {newsItem.latest_headline}
                                  </a>
                                </td>
                                <td className="py-3 px-4 text-slate-500">{newsItem.last_update}</td>
                              </tr>
                              {open && (
                                <tr className="bg-slate-900/40">
                                  <td colSpan={9} className="px-6 py-4">
                                    <div className="flex items-center justify-between mb-3">
                                      <h4 className="text-[11px] font-bold uppercase tracking-wider text-indigo-300">
                                        Articles scored for {newsItem.ticker}
                                      </h4>
                                      <span className="text-[10px] text-slate-500 font-mono">
                                        {isLoadingArticles ? "Loading…" : `${articles.length} article${articles.length === 1 ? "" : "s"} (last 24h)`}
                                      </span>
                                    </div>
                                    {isLoadingArticles && articles.length === 0 ? (
                                      <div className="py-4 text-center text-slate-500 text-xs">Loading articles…</div>
                                    ) : articles.length === 0 ? (
                                      <div className="py-4 text-center text-slate-500 text-xs">No detailed articles available.</div>
                                    ) : (
                                      <div className="space-y-3 max-h-[420px] overflow-y-auto pr-2">
                                        {articles.map((a, aIdx) => (
                                          <div key={aIdx} className="p-3 rounded-lg bg-slate-950/60 border border-slate-850">
                                            <div className="flex items-baseline justify-between gap-3">
                                              <h5 className="text-xs font-bold text-slate-200">
                                                <a
                                                  href={a.url}
                                                  target="_blank"
                                                  rel="noreferrer"
                                                  className="hover:underline text-indigo-300"
                                                  onClick={(e) => e.stopPropagation()}
                                                >
                                                  {a.title}
                                                </a>
                                              </h5>
                                              <span
                                                className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold shrink-0 ${
                                                  a.sentiment !== null && a.sentiment >= 0.05
                                                    ? "bg-emerald-500/10 text-emerald-400"
                                                    : a.sentiment !== null && a.sentiment <= -0.05
                                                    ? "bg-rose-500/10 text-rose-400"
                                                    : "bg-slate-800 text-slate-400"
                                                }`}
                                              >
                                                {a.sentiment !== null ? a.sentiment.toFixed(3) : "NEUTRAL"}
                                              </span>
                                            </div>
                                            {a.summary && (
                                              <p className="text-slate-400 text-[11px] mt-2 font-mono">{a.summary}</p>
                                            )}
                                            <div className="flex items-center gap-3 mt-2 text-[10px] text-slate-500 font-mono">
                                              <span>{a.source}</span>
                                              <span>•</span>
                                              <span>{a.ts}</span>
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ==================== 6. FUNDAMENTALS ==================== */}
          {activeTab === "fundamentals" && (
            <div className="space-y-8 animate-fadeIn">
              {/* SOURCES LEGEND + PIN INPUT */}
              <div className="glass-panel p-5 rounded-2xl space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                      Universe Sources
                    </h3>
                    <span className="text-xs text-slate-500">
                      Tickers shown are auto-selected from the books that need fundamentals attention.
                      Click any row to load the deep Screener.in view.
                    </span>
                  </div>
                  <button
                    onClick={() => { loadFundamentalsTable(); loadFundamentalsPins(); }}
                    className="px-3 py-1.5 border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-[10px] font-semibold cursor-pointer flex items-center gap-1.5"
                  >
                    <RefreshCw size={11} /> Reload
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-5 gap-2 text-[10px] font-mono">
                  {[
                    { key: "intraday_open",   label: "Intraday Open",   color: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30" },
                    { key: "positional_open", label: "Positional Open", color: "bg-sky-500/10 text-sky-300 border-sky-500/30" },
                    { key: "pinned",          label: "Pinned",          color: "bg-amber-500/10 text-amber-300 border-amber-500/30" },
                    { key: "lt_universe",     label: "LT Universe",     color: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30" },
                    { key: "pos_scan_top",    label: "Pos Scan Top",    color: "bg-purple-500/10 text-purple-300 border-purple-500/30" },
                  ].map((src) => {
                    const count = fundamentals.filter((s) => (s.sources || []).includes(src.key)).length;
                    return (
                      <div key={src.key} className={`p-2 rounded-lg border flex items-center justify-between ${src.color}`}>
                        <span className="font-bold uppercase tracking-wider">{src.label}</span>
                        <span className="font-mono">{count}</span>
                      </div>
                    );
                  })}
                </div>

                <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-slate-800/60">
                  <div className="flex gap-2 flex-1 min-w-[260px]">
                    <input
                      type="text"
                      placeholder="Pin a ticker (e.g. INFY)"
                      value={fundamentalsPinInput}
                      onChange={(e) => setFundamentalsPinInput(e.target.value.toUpperCase())}
                      onKeyDown={(e) => { if (e.key === "Enter") pinFundamentalsTicker(); }}
                      className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-amber-500/40 font-mono"
                    />
                    <button
                      onClick={pinFundamentalsTicker}
                      className="px-3 py-1.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded-lg text-[10px] font-semibold cursor-pointer"
                    >
                      PIN
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {fundamentalsPins.length === 0 ? (
                      <span className="text-[10px] text-slate-500 font-mono">No pinned tickers yet.</span>
                    ) : fundamentalsPins.map((p) => (
                      <span
                        key={p.ticker}
                        className="px-2 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-300 border border-amber-500/30 font-mono flex items-center gap-1.5"
                      >
                        {p.ticker}
                        <button
                          onClick={() => unpinFundamentalsTicker(p.ticker)}
                          className="text-amber-200/70 hover:text-rose-300 cursor-pointer"
                          title={`Unpin ${p.ticker}`}
                        >×</button>
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              {/* SEARCH INPUT CARD */}
              <div className="glass-panel p-4 rounded-2xl flex items-center gap-4">
                <Search size={16} className="text-slate-500" />
                <input
                  type="text"
                  placeholder="Filter by ticker or sector…"
                  value={fundamentalsSearch}
                  onChange={(e) => setFundamentalsSearch(e.target.value)}
                  className="flex-1 bg-transparent border-none text-slate-200 text-xs focus:outline-none font-mono"
                />
              </div>

              {/* MAIN METRIC GRID */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Fundamentals — Investable Universe
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">({fundamentals.length} companies)</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4 w-6"></th>
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4">Sources</th>
                        <th className="py-3 px-4">Sector</th>
                        <th className="py-3 px-4 text-center">Score</th>
                        <th className="py-3 px-4 text-right" title="Trailing P/E from yfinance.">P/E</th>
                        <th className="py-3 px-4 text-right" title="Price/Earnings to Growth.">PEG</th>
                        <th className="py-3 px-4 text-right" title="Market capitalization in INR.">Market Cap</th>
                        <th className="py-3 px-4 text-right">Rev Growth</th>
                        <th className="py-3 px-4 text-right">D/E</th>
                        <th className="py-3 px-4 text-right">ROE %</th>
                        <th className="py-3 px-4 text-right">Profit Margin</th>
                        <th className="py-3 px-4">Warnings</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {fundamentals.length === 0 ? (
                        <tr>
                          <td colSpan={13} className="py-8 text-center text-slate-500">
                            No tickers in the fundamentals universe yet. Open or pin a position to populate this view.
                          </td>
                        </tr>
                      ) : fundamentals
                        .filter(
                          (stock) =>
                            stock.ticker.toUpperCase().includes(fundamentalsSearch.toUpperCase()) ||
                            stock.sector.toUpperCase().includes(fundamentalsSearch.toUpperCase())
                        )
                        .map((stock, idx) => {
                          const open = fundamentalsExpanded.has(stock.ticker);
                          const detail = fundamentalsDetailByTicker[stock.ticker];
                          const priceHist = fundamentalsPriceByTicker[stock.ticker];
                          const detailLoading = fundamentalsDetailLoading.has(stock.ticker);
                          return (
                            <React.Fragment key={`${stock.ticker}-${idx}`}>
                              <tr
                                className="hover:bg-slate-900/20 cursor-pointer"
                                onClick={() => toggleFundamentalsRow(stock.ticker)}
                              >
                                <td className="py-3 px-4 text-slate-500 text-center w-6">{open ? "▾" : "▸"}</td>
                                <td className="py-3 px-4 font-bold text-slate-200">{stock.ticker}</td>
                                <td className="py-3 px-4">
                                  <div className="flex flex-wrap gap-1">
                                    {(stock.sources || []).map((s) => {
                                      const styles: Record<string, string> = {
                                        intraday_open:   "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
                                        positional_open: "bg-sky-500/10 text-sky-300 border-sky-500/30",
                                        pinned:          "bg-amber-500/10 text-amber-300 border-amber-500/30",
                                        lt_universe:     "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
                                        pos_scan_top:    "bg-purple-500/10 text-purple-300 border-purple-500/30",
                                      };
                                      const labels: Record<string, string> = {
                                        intraday_open:   "Intraday",
                                        positional_open: "Positional",
                                        pinned:          "Pinned",
                                        lt_universe:     "LT",
                                        pos_scan_top:    "Scan",
                                      };
                                      return (
                                        <span
                                          key={s}
                                          className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${styles[s] || "bg-slate-800 text-slate-400 border-slate-700"}`}
                                        >
                                          {labels[s] || s}
                                        </span>
                                      );
                                    })}
                                  </div>
                                </td>
                                <td className="py-3 px-4 text-slate-400">{stock.sector}</td>
                                <td className="py-3 px-4 text-center text-indigo-400 font-bold">
                                  {stock.fundamental_score !== null ? stock.fundamental_score : "—"}
                                </td>
                                <td className="py-3 px-4 text-right text-slate-300">
                                  {stock.pe_ratio !== null ? stock.pe_ratio.toFixed(2) : "—"}
                                </td>
                                <td className="py-3 px-4 text-right text-slate-300">
                                  {stock.peg_ratio !== null ? stock.peg_ratio.toFixed(2) : "—"}
                                </td>
                                <td className="py-3 px-4 text-right text-slate-300">
                                  {stock.market_cap !== null ? formatINR(stock.market_cap).replace("₹", "") : "—"}
                                </td>
                                <td className="py-3 px-4 text-right text-emerald-400 font-bold">
                                  {stock.revenue_growth !== null ? `${stock.revenue_growth >= 0 ? "+" : ""}${stock.revenue_growth.toFixed(1)}%` : "—"}
                                </td>
                                <td
                                  className={`py-3 px-4 text-right ${
                                    stock.debt_to_equity !== null && stock.debt_to_equity > 2.0
                                      ? "text-rose-500 font-bold"
                                      : "text-slate-300"
                                  }`}
                                >
                                  {stock.debt_to_equity !== null ? stock.debt_to_equity.toFixed(2) : "—"}
                                </td>
                                <td className="py-3 px-4 text-right text-emerald-400">
                                  {stock.roe !== null ? `${stock.roe.toFixed(1)}%` : "—"}
                                </td>
                                <td className="py-3 px-4 text-right text-slate-300">
                                  {stock.profit_margin !== null ? `${stock.profit_margin.toFixed(1)}%` : "—"}
                                </td>
                                <td className="py-3 px-4">
                                  {stock.is_bank ? (
                                    <span
                                      className="px-2 py-0.5 rounded text-[10px] bg-purple-500/10 text-purple-400 border border-purple-500/20 font-bold"
                                      title="Banks/NBFCs follow unique capital ratios"
                                    >
                                      Banking rules
                                    </span>
                                  ) : stock.debt_to_equity !== null && stock.debt_to_equity > 1.5 ? (
                                    <span
                                      className="px-2 py-0.5 rounded text-[10px] bg-rose-500/10 text-rose-400 border border-rose-500/20 font-bold flex items-center gap-1 w-max"
                                      title="Caution: Debt-to-Equity exceeds 1.5!"
                                    >
                                      <AlertCircle size={10} /> Highly Leveraged
                                    </span>
                                  ) : stock.fetched_at === "—" ? (
                                    <span className="text-[10px] text-slate-500 italic">Fundamentals not fetched yet</span>
                                  ) : (
                                    <span className="text-[10px] text-slate-500">Passed standard bounds</span>
                                  )}
                                </td>
                              </tr>
                              {open && (
                                <tr className="bg-slate-900/40">
                                  <td colSpan={13} className="px-6 py-5">
                                    <FundamentalsDetailPanel
                                      stock={stock}
                                      detail={detail}
                                      priceHistory={priceHist}
                                      loading={detailLoading}
                                      timeframe={fundamentalsTimeframe[stock.ticker] || "5Y"}
                                      onChangeTimeframe={(tf) => setFundamentalsTimeframeForTicker(stock.ticker, tf)}
                                      onRefresh={() => toggleFundamentalsRow(stock.ticker, { refresh: true })}
                                    />
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ==================== 7. PERFORMANCE STATS ==================== */}
          {activeTab === "analytics" && (
            <div className="space-y-8 animate-fadeIn">
              {/* SUMMARY STATS GRID */}
              {analyticsSummary && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                  <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-32 relative overflow-hidden">
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">
                      Engine Profit Factor
                    </span>
                    <span className="text-2xl font-extrabold text-indigo-400 font-mono mt-2">
                      {analyticsSummary.profit_factor}
                    </span>
                    <span className="text-[10px] text-slate-500 mt-1">Total wins divided by total losses</span>
                  </div>

                  <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-32 relative overflow-hidden">
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">
                      Win-Loss Ratio (Win Rate)
                    </span>
                    <span className="text-2xl font-extrabold text-emerald-400 font-mono mt-2">
                      {analyticsSummary.win_rate.toFixed(1)}%
                    </span>
                    <div className="w-full bg-slate-800 rounded-full h-1.5 mt-2">
                      <div
                        className="grad-success h-1.5 rounded-full"
                        style={{ width: `${analyticsSummary.win_rate}%` }}
                      />
                    </div>
                  </div>

                  <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-32 relative overflow-hidden">
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">
                      Avg Winner vs Loser size
                    </span>
                    <div className="mt-2 space-y-1 font-mono text-xs">
                      <div className="flex justify-between">
                        <span className="text-emerald-400">Wins:</span>
                        <span>{formatINR(analyticsSummary.avg_winner)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-rose-500">Losses:</span>
                        <span>{formatINR(analyticsSummary.avg_loser)}</span>
                      </div>
                    </div>
                  </div>

                  <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-32 relative overflow-hidden">
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">
                      Account realized P&L
                    </span>
                    <span className={`text-2xl font-extrabold font-mono mt-2 ${getPnlColor(analyticsSummary.total_pnl)}`}>
                      {formatINR(analyticsSummary.total_pnl)}
                    </span>
                    <span className="text-[10px] text-slate-500 mt-1">Historical realized profit</span>
                  </div>
                </div>
              )}

              {/* STRATEGIC SYSTEM BREAKDOWNS */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 animate-fadeIn">
                {/* Visualizer Chart */}
                <div className="glass-panel p-6 rounded-2xl lg:col-span-2 space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Realized PNL Breakdown by System Code
                  </h3>
                  <div className="h-80 w-full font-mono text-[10px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={strategyPerformance} margin={{ top: 20, right: 10, left: -20, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                        <XAxis dataKey="strategy" stroke="#475569" />
                        <YAxis stroke="#475569" />
                        <Tooltip
                          contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }}
                        />
                        <Bar dataKey="total_pnl" name="Total Realized profit (₹)">
                          {strategyPerformance.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.total_pnl >= 0 ? "#10b981" : "#ef4444"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Data Grid */}
                <div className="glass-panel p-6 rounded-2xl space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    System Return Metrics Table
                  </h3>
                  <div className="space-y-4 overflow-y-auto max-h-[300px] pr-2">
                    {strategyPerformance.map((strat, idx) => (
                      <div key={idx} className="p-4 rounded-xl bg-slate-950/60 border border-slate-850">
                        <div className="flex items-center justify-between border-b border-slate-900 pb-2">
                          <span className="text-xs font-bold text-slate-200 uppercase">{strat.strategy}</span>
                          <span className={`text-xs font-mono font-bold ${getPnlColor(strat.total_pnl)}`}>
                            {formatINR(strat.total_pnl)}
                          </span>
                        </div>

                        <div className="grid grid-cols-3 gap-2 text-[10px] font-mono text-slate-500 mt-3">
                          <div>
                            <div>Total Trades:</div>
                            <div className="text-slate-300 font-bold mt-0.5">{strat.trades}</div>
                          </div>
                          <div>
                            <div>Win Rate:</div>
                            <div className="text-emerald-400 font-bold mt-0.5">{strat.win_rate_pct.toFixed(1)}%</div>
                          </div>
                          <div>
                            <div>Avg Return:</div>
                            <div className="text-slate-300 font-bold mt-0.5">{formatINR(strat.avg_pnl)}</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ==================== 8. LLM OBSERVABILITY ==================== */}
          {activeTab === "observability" && (
            <div className="space-y-8 animate-fadeIn">
              {/* STATS OVERVIEW CARDS */}
              {observabilityTotals && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                  <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-32 relative overflow-hidden">
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">
                      Daily API Token Count
                    </span>
                    <span className="text-2xl font-extrabold text-indigo-400 font-mono mt-2">
                      {observabilityTotals.prompt_tokens_today + observabilityTotals.completion_tokens_today}
                    </span>
                    <span className="text-[10px] text-slate-500 mt-1">
                      {observabilityTotals.prompt_tokens_today} prompt / {observabilityTotals.completion_tokens_today} comp
                    </span>
                  </div>

                  <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-32 relative overflow-hidden">
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">
                      Today's API Cost (USD)
                    </span>
                    <span className="text-2xl font-extrabold text-emerald-400 font-mono mt-2">
                      ${observabilityTotals.cost_today_usd.toFixed(3)}
                    </span>
                    <div className="w-full bg-slate-800 rounded-full h-1.5 mt-2">
                      <div
                        className="grad-success h-1.5 rounded-full"
                        style={{
                          width: `${(observabilityTotals.cost_today_usd / observabilityTotals.max_daily_budget_usd) * 100}%`
                        }}
                      />
                    </div>
                  </div>

                  <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-32 relative overflow-hidden">
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">
                      Active Daily Budget
                    </span>
                    <span className="text-2xl font-extrabold text-slate-100 font-mono mt-2">
                      ${observabilityTotals.max_daily_budget_usd.toFixed(2)}
                    </span>
                    <span className="text-[10px] text-slate-500 mt-1">Daily hard boundary set in .env</span>
                  </div>

                  <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between h-32 relative overflow-hidden">
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">
                      Today's query Sessions
                    </span>
                    <span className="text-2xl font-extrabold text-indigo-400 font-mono mt-2">
                      {observabilityTotals.calls_today}
                    </span>
                    <span className="text-[10px] text-slate-500 mt-1">
                      Success rate: {observabilityTotals.success_rate_pct}%
                    </span>
                  </div>
                </div>
              )}

              {/* CHARTS SECTION */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Daily Cost Trend */}
                <div className="glass-panel p-6 rounded-2xl lg:col-span-2">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-4">
                    7-Day LLM Query Calls & Cost Trends
                  </h3>
                  <div className="h-64 w-full font-mono text-[10px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={observabilityDaily} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                          <linearGradient id="colorCost" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.2} />
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                        <XAxis dataKey="date" stroke="#475569" />
                        <YAxis stroke="#475569" />
                        <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                        <Area type="monotone" dataKey="cost" name="Query Cost ($)" stroke="#10b981" fillOpacity={1} fill="url(#colorCost)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* calling share breakdown */}
                <div className="glass-panel p-6 rounded-2xl">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-4">
                    Token Calling Share by Trigger Component
                  </h3>
                  <div className="h-64 w-full font-mono text-[10px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={observabilityCallers} layout="vertical" margin={{ top: 10, right: 10, left: 10, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                        <XAxis type="number" stroke="#475569" />
                        <YAxis dataKey="caller" type="category" stroke="#475569" width={100} />
                        <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                        <Bar dataKey="pct" name="Tokens Share (%)" fill="#6366f1" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>

              {/* DETAILED LLM LOGS TABLE */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Recent LLM Call Sessions Logger
                  </h3>
                  <span className="text-xs text-slate-500">Observability audits</span>
                </div>

                <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px] sticky top-0 bg-[#080d21]">
                        <th className="py-2 px-3">Session Timestamp</th>
                        <th className="py-2 px-3">Trigger Caller</th>
                        <th className="py-2 px-3">Target Model</th>
                        <th className="py-2 px-3 text-center">Tokens consumed</th>
                        <th className="py-2 px-3 text-center">Cost Estim</th>
                        <th className="py-2 px-3">Session Status</th>
                        <th className="py-2 px-3">Notes (Ticker/Scans)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {observabilityCalls.map((call) => (
                        <tr key={call.id} className="hover:bg-slate-900/20">
                          <td className="py-2 px-3 text-slate-400">{call.ts}</td>
                          <td className="py-2 px-3 text-slate-200 font-semibold">{call.caller}</td>
                          <td className="py-2 px-3 text-slate-400">{call.model}</td>
                          <td className="py-2 px-3 text-center text-slate-300">{call.tokens}</td>
                          <td className="py-2 px-3 text-center text-slate-300">${(call.tokens * 0.000002).toFixed(4)}</td>
                          <td className="py-2 px-3">
                            <span className={`px-2 py-0.5 rounded-full text-[9px] ${getBadgeColor(call.status)}`}>
                              {call.status}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-slate-400 max-w-[200px] truncate">{call.note}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ==================== 9. RESEARCH PIPELINE ==================== */}
          {activeTab === "research" && (
            <div className="space-y-8 animate-fadeIn">
              {/* SEARCH INPUT BAR */}
              <div className="glass-panel p-5 rounded-2xl flex items-center gap-4">
                <Search size={16} className="text-slate-500" />
                <input
                  type="text"
                  placeholder="Search Whitelist Quality Candidates (e.g. COALINDIA)..."
                  value={researchSearch}
                  onChange={(e) => setResearchSearch(e.target.value)}
                  className="flex-1 bg-transparent border-none text-slate-200 text-xs focus:outline-none font-mono"
                />
              </div>

              {/* COGNITIVE HIGH-CONVICTION QUALITY CANDIDATES */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    High-Conviction Quality Score whitelists candidates
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">({researchCandidates.length} passed)</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4">Sector Type</th>
                        <th className="py-3 px-4 text-right">Market Cap (Cr)</th>
                        <th className="py-3 px-4 text-center">Profitability</th>
                        <th className="py-3 px-4 text-center">Cash Quality</th>
                        <th className="py-3 px-4 text-center">Solvency</th>
                        <th className="py-3 px-4 text-center">Growth Score</th>
                        <th className="py-3 px-4 text-center">Gov Score</th>
                        <th className="py-3 px-4 text-center">Aggregate Score</th>
                        <th className="py-3 px-4">Evaluated Date</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {researchCandidates
                        .filter(
                          (cand) =>
                            cand.ticker.toUpperCase().includes(researchSearch.toUpperCase()) ||
                            cand.sector.toUpperCase().includes(researchSearch.toUpperCase())
                        )
                        .map((cand, idx) => (
                          <tr key={idx} className="hover:bg-slate-900/20">
                            <td className="py-3 px-4 text-slate-200 font-bold">{cand.ticker}</td>
                            <td className="py-3 px-4 text-slate-400">{cand.sector}</td>
                            <td className="py-3 px-4 text-right text-slate-300">
                              {cand.market_cap !== null ? formatINR(cand.market_cap).replace("₹", "") : "—"}
                            </td>
                            <td className="py-3 px-4 text-center text-slate-300">{cand.profitability_score}/20</td>
                            <td className="py-3 px-4 text-center text-slate-300">{cand.cash_quality_score}/20</td>
                            <td className="py-3 px-4 text-center text-slate-300">{cand.solvency_score}/20</td>
                            <td className="py-3 px-4 text-center text-slate-300">{cand.growth_score}/20</td>
                            <td className="py-3 px-4 text-center text-slate-300">{cand.governance_score}/20</td>
                            <td className="py-3 px-4 text-center text-indigo-400 font-extrabold">{cand.total_score}/100</td>
                            <td className="py-3 px-4 text-slate-500">{cand.scored_at}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* FAILED CANDIDATES GAP ANALYZER */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Failed Whitelists Candidates & Filter Gap Reasons
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">({researchFailures.length} failed)</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4">Sector Category</th>
                        <th className="py-3 px-4">Fundamental Filter Failure Reason</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {researchFailures
                        .filter(
                          (fail) =>
                            fail.ticker.toUpperCase().includes(researchSearch.toUpperCase()) ||
                            fail.sector.toUpperCase().includes(researchSearch.toUpperCase())
                        )
                        .map((fail, idx) => (
                          <tr key={idx} className="hover:bg-slate-900/20">
                            <td className="py-3 px-4 text-rose-400 font-bold">{fail.ticker}</td>
                            <td className="py-3 px-4 text-slate-400">{fail.sector}</td>
                            <td className="py-3 px-4 text-slate-400 leading-relaxed font-mono">
                              <span className="px-2 py-0.5 rounded text-[9px] bg-rose-500/10 text-rose-400 border border-rose-500/20 font-bold mr-3 inline-block">
                                FAILED BOUNDS
                              </span>
                              {fail.reason}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ==================== 10. TELEMETRY LOGS ==================== */}
          {activeTab === "logs" && (
            <div className="space-y-8 animate-fadeIn h-full flex flex-col">
              <div className="glass-panel p-6 rounded-2xl flex-1 flex flex-col justify-between">
                <div className="space-y-4 flex-1 flex flex-col">
                  {/* LOG CONTROLS */}
                  <div className="flex items-center justify-between border-b border-slate-800 pb-3 flex-wrap gap-4">
                    <div className="flex items-center gap-3">
                      <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 active-pulse" />
                      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                        Live scrolling system Logs (Tail: 400 lines)
                      </h3>
                    </div>

                    <div className="flex items-center gap-3 font-mono text-[10px]">
                      <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-1.5">
                        <span className="text-slate-500 mr-2 uppercase">Lvl:</span>
                        <select
                          value={logLevelFilter}
                          onChange={(e) => setLogLevelFilter(e.target.value)}
                          className="bg-transparent border-none text-slate-300 focus:outline-none focus:ring-0 cursor-pointer"
                        >
                          <option value="" className="bg-[#0b1021]">ALL LEVELS</option>
                          <option value="INFO" className="bg-[#0b1021]">INFO ONLY</option>
                          <option value="WARNING" className="bg-[#0b1021]">WARNINGS</option>
                          <option value="ERROR" className="bg-[#0b1021]">ERRORS</option>
                        </select>
                      </div>

                      <a
                        href={`${API_BASE}/api/system/logs/download`}
                        className="py-2 px-3 border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg flex items-center gap-1 cursor-pointer font-sans"
                        download
                      >
                        <Download size={12} />
                        DOWNLOAD FULL REPORT
                      </a>
                    </div>
                  </div>

                  {/* STREAM PANEL */}
                  <div className="flex-1 min-h-[380px] bg-slate-950/80 border border-slate-900 rounded-xl p-5 overflow-y-auto font-mono text-[11px] leading-relaxed space-y-1.5 scroll-smooth select-text">
                    {systemLogs.length === 0 ? (
                      <div className="text-slate-500 text-center py-8">
                        Connecting to logs stream or empty logs file...
                      </div>
                    ) : (
                      systemLogs.map((line, idx) => {
                        let lineStyle = "text-slate-400";
                        if (line.includes("ERROR") || line.includes("CRITICAL")) {
                          lineStyle = "text-rose-400 font-bold bg-rose-500/5 px-1 py-0.5 rounded";
                        } else if (line.includes("WARNING")) {
                          lineStyle = "text-amber-400 font-medium";
                        } else if (line.includes("SUCCESS")) {
                          lineStyle = "text-emerald-400 font-medium";
                        } else if (line.includes("INFO")) {
                          lineStyle = "text-slate-300";
                        }

                        return (
                          <div key={idx} className={`${lineStyle} whitespace-pre-wrap hover:bg-slate-900/10`}>
                            {line}
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
