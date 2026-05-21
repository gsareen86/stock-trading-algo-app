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
  Cell
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
  fundamental_score: number;
}

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
}

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

  // Fundamentals states
  const [fundamentals, setFundamentals] = useState<FundamentalStock[]>([]);
  const [fundamentalsSearch, setFundamentalsSearch] = useState<string>("");

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

    if (activeTab === "positional") {
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
      const fetchFundamentals = async () => {
        try {
          const res = await fetch(`${API_BASE}/api/fundamentals`);
          const data = await res.json();
          setFundamentals(data);
        } catch (e) {
          console.error("Failed to fetch fundamentals:", e);
        }
      };
      fetchFundamentals();
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
        setSuccessMsg("EOD exit scanning triggered in background.");
      } else {
        setErrorMsg("Failed EOD exit trigger.");
      }
    } catch (e) {
      setErrorMsg("Network error exit checks.");
    } finally {
      setLoading((prev) => ({ ...prev, pos_exits: false }));
    }
  };

  const handleTriggerPositionalScan = async () => {
    setLoading((prev) => ({ ...prev, pos_scan: true }));
    try {
      const res = await fetch(`${API_BASE}/api/positional/scan`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setSuccessMsg("EOD positional scan triggered in background.");
      } else {
        setErrorMsg("Failed EOD positional scan trigger.");
      }
    } catch (e) {
      setErrorMsg("Network error positional scan.");
    } finally {
      setLoading((prev) => ({ ...prev, pos_scan: false }));
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
                      onClick={handleTriggerPositionalScan}
                      disabled={loading["pos_scan"]}
                      className="w-full py-2.5 px-4 rounded-xl border border-indigo-800 hover:bg-indigo-950/20 text-indigo-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <RefreshCw size={14} className={loading["pos_scan"] ? "animate-spin" : ""} />
                      {loading["pos_scan"] ? "SCANNING UNIVERSE..." : "RUN EOD SWEEP SCAN NOW"}
                    </button>

                    <button
                      onClick={handleTriggerPositionalExits}
                      disabled={loading["pos_exits"]}
                      className="w-full py-2.5 px-4 rounded-xl border border-slate-800 hover:bg-slate-900 text-slate-300 font-semibold text-xs cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <RefreshCw size={14} className={loading["pos_exits"] ? "animate-spin" : ""} />
                      {loading["pos_exits"] ? "SWEEPING EXITS..." : "RUN EOD EXIT CHECKS"}
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
                    Active Minervini VCP Positions (21 EMA Tracker)
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">({positionalPositions.length} active holdings)</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4">Ticker</th>
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
                          <td colSpan={12} className="py-8 text-center text-slate-500">
                            No swing holdings are currently active.
                          </td>
                        </tr>
                      ) : (
                        positionalPositions.map((pos) => (
                          <tr key={pos.id} className="hover:bg-slate-900/20">
                            <td className="py-3 px-4 text-slate-200 font-bold">{pos.ticker}</td>
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

              {/* SCAN CANDIDATES GRID */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Latest Swing Scan Results (VCP & Momentum Checklists)
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">({positionalScanResults.length} setups detected)</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4">Scanned At</th>
                        <th className="py-3 px-4 text-right">Price</th>
                        <th className="py-3 px-4 text-center">Trend Template</th>
                        <th className="py-3 px-4 text-center">VCP Detected</th>
                        <th className="py-3 px-4 text-right">52W Proximity %</th>
                        <th className="py-3 px-4 text-right">ATR %</th>
                        <th className="py-3 px-4 text-center">Setup Score</th>
                        <th className="py-3 px-4">Reason Details</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {positionalScanResults.length === 0 ? (
                        <tr>
                          <td colSpan={9} className="py-8 text-center text-slate-500">
                            No scan candidates populated yet. Ensure whitelists are uploaded!
                          </td>
                        </tr>
                      ) : (
                        positionalScanResults.map((scan) => (
                          <tr key={scan.id} className="hover:bg-slate-900/20">
                            <td className="py-3 px-4 text-slate-200 font-bold">{scan.ticker}</td>
                            <td className="py-3 px-4 text-slate-500">{scan.scanned_at}</td>
                            <td className="py-3 px-4 text-right text-slate-300">
                              {scan.price ? formatINR(scan.price) : "—"}
                            </td>
                            <td className="py-3 px-4 text-center">
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                  scan.trend_template
                                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                    : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                                }`}
                              >
                                {scan.trend_template ? "PASSED" : "FAILED"}
                              </span>
                            </td>
                            <td className="py-3 px-4 text-center">
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                  scan.vcp_detected
                                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                    : "bg-slate-850 text-slate-500"
                                }`}
                              >
                                {scan.vcp_detected ? "DETEC" : "—"}
                              </span>
                            </td>
                            <td className="py-3 px-4 text-right text-slate-300">
                              {scan.proximity_52w_pct ? `${scan.proximity_52w_pct.toFixed(1)}%` : "—"}
                            </td>
                            <td className="py-3 px-4 text-right text-purple-400">
                              {scan.atr_pct ? `${scan.atr_pct.toFixed(1)}%` : "—"}
                            </td>
                            <td className="py-3 px-4 text-center text-indigo-400 font-bold">{scan.score}</td>
                            <td className="py-3 px-4 text-slate-400 max-w-[200px] truncate">{scan.reason}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
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
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                      Recency-Decay Sentiment Leaderboard
                    </h3>
                    <span className="text-xs text-slate-500">
                      Weighted score decay: recent headlines weigh exponentially more.
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

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4">Sector Type</th>
                        <th className="py-3 px-4 text-center">Article Count</th>
                        <th className="py-3 px-4 text-center">Breakdown</th>
                        <th className="py-3 px-4 text-center">Unweighted Avg</th>
                        <th className="py-3 px-4 text-center">Decay Weighted Avg</th>
                        <th className="py-3 px-4">Latest Headline Scored</th>
                        <th className="py-3 px-4">Scored Date</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {newsLeaderboard.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="py-8 text-center text-slate-500">
                            No matching headlines sentiment logs found in this period.
                          </td>
                        </tr>
                      ) : (
                        newsLeaderboard.map((newsItem, idx) => (
                          <tr key={idx} className="hover:bg-slate-900/20">
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
                              <a href={newsItem.latest_url} target="_blank" rel="noreferrer" className="hover:underline">
                                {newsItem.latest_headline}
                              </a>
                            </td>
                            <td className="py-3 px-4 text-slate-500">{newsItem.last_update}</td>
                          </tr>
                        ))
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
              {/* SEARCH INPUT CARD */}
              <div className="glass-panel p-5 rounded-2xl flex items-center gap-4">
                <Search size={16} className="text-slate-500" />
                <input
                  type="text"
                  placeholder="Search SQLite whitelists (e.g. INFOSYS, PE, DEBT)..."
                  value={fundamentalsSearch}
                  onChange={(e) => setFundamentalsSearch(e.target.value)}
                  className="flex-1 bg-transparent border-none text-slate-200 text-xs focus:outline-none font-mono"
                />
              </div>

              {/* MAIN METRIC GRID */}
              <div className="glass-panel p-6 rounded-2xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 m-0">
                    Scored Whitelist Fundamentals Table
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">({fundamentals.length} companies)</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-850 text-slate-500 uppercase tracking-wider text-[9px]">
                        <th className="py-3 px-4">Ticker</th>
                        <th className="py-3 px-4">Sector Category</th>
                        <th className="py-3 px-4 text-center">Score</th>
                        <th className="py-3 px-4 text-right">P/E Ratio</th>
                        <th className="py-3 px-4 text-right">PEG Ratio</th>
                        <th className="py-3 px-4 text-right">Market Cap (Cr)</th>
                        <th className="py-3 px-4 text-right">Revenue growth</th>
                        <th className="py-3 px-4 text-right">Solvency (D/E)</th>
                        <th className="py-3 px-4 text-right">ROE (%)</th>
                        <th className="py-3 px-4 text-right">Profit Margin (%)</th>
                        <th className="py-3 px-4">Financial Caution Warnings</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {fundamentals
                        .filter(
                          (stock) =>
                            stock.ticker.toUpperCase().includes(fundamentalsSearch.toUpperCase()) ||
                            stock.sector.toUpperCase().includes(fundamentalsSearch.toUpperCase())
                        )
                        .map((stock, idx) => (
                          <tr key={idx} className="hover:bg-slate-900/20">
                            <td className="py-3 px-4 font-bold text-slate-200">
                              <a
                                href={stock.screener_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-indigo-300 hover:underline flex items-center gap-1.5"
                              >
                                {stock.ticker}
                              </a>
                            </td>
                            <td className="py-3 px-4 text-slate-400">{stock.sector}</td>
                            <td className="py-3 px-4 text-center text-indigo-400 font-bold">{stock.fundamental_score}</td>
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
                              {stock.revenue_growth !== null ? `+${stock.revenue_growth.toFixed(1)}%` : "—"}
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
                                  🏦 Banking rules
                                </span>
                              ) : stock.debt_to_equity !== null && stock.debt_to_equity > 1.5 ? (
                                <span
                                  className="px-2 py-0.5 rounded text-[10px] bg-rose-500/10 text-rose-400 border border-rose-500/20 font-bold flex items-center gap-1 w-max"
                                  title="Caution: Debt-to-Equity exceeds 1.5!"
                                >
                                  <AlertCircle size={10} /> Highly Leveraged
                                </span>
                              ) : (
                                <span className="text-[10px] text-slate-500">Passed standard bounds</span>
                              )}
                            </td>
                          </tr>
                        ))}
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
