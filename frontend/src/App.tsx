/* App shell — grouped sidebar, contextual header, one page component per view.
   Every page is self-contained in src/pages/ and built from the shared
   primitives in src/components/ui.tsx, so the whole app stays aligned. */
import { useEffect, useState } from "react";
import {
  Activity, PieChart, DollarSign, Sliders, Layers, TrendingUp, Bell,
  Shield, BookOpen, Cpu, FileText, Wrench, BarChart3,
} from "lucide-react";
import { getJSON, fmtINR } from "./api";
import { Badge, ToastHost } from "./components/ui";
import { bindNavigator } from "./nav";

import Overview from "./pages/Overview";
import Control from "./pages/Control";
import Intraday from "./pages/Intraday";
import SwingBook from "./pages/SwingBook";
import LongTermBook from "./pages/LongTermBook";
import Research from "./pages/Research";
import NewsAlerts from "./pages/NewsAlerts";
import Fundamentals from "./pages/Fundamentals";
import EngineRoom from "./pages/EngineRoom";
import Performance from "./pages/Performance";
import LlmUsage from "./pages/LlmUsage";
import Logs from "./pages/Logs";

const PAGES: Record<string, { title: string; subtitle: string }> = {
  overview:  { title: "Overview", subtitle: "All three books at a glance — value, P&L, open positions" },
  control:   { title: "Control Center", subtitle: "Start/stop, trading mode, risk parameters, approvals and every manual trigger" },
  intraday:  { title: "Intraday Book", subtitle: "15-min strategies · ATR exits · square-off 15:10 IST" },
  swing:     { title: "Swing Book", subtitle: "EOD scans · Timing/Durability scorecard · hold days–weeks" },
  ltbook:    { title: "Long-Term Book", subtitle: "Tranche accumulation of durable compounders · thesis stops only" },
  research:  { title: "Research & Guidance", subtitle: "LLM concall verdicts · the guidance ledger · management credibility" },
  news:      { title: "News & Alerts", subtitle: "Scraped headlines · sentiment · LLM impact triage on your names" },
  fundamentals: { title: "Fundamentals", subtitle: "Financial health for everything the engine tracks" },
  engine:    { title: "Engine Room", subtitle: "Outcomes · calibration · backtest lab · event & surveillance calendars" },
  performance: { title: "Performance", subtitle: "Results after costs, by book and by strategy" },
  llm:       { title: "LLM Usage", subtitle: "Live token consumption by provider, model and feature" },
  logs:      { title: "System Logs", subtitle: "Runtime log tail — what the bot is doing right now" },
};

const NAV: { label: string; items: { key: string; label: string; icon: React.ReactNode }[] }[] = [
  {
    label: "Portfolio",
    items: [
      { key: "overview", label: "Overview", icon: <PieChart size={15} /> },
      { key: "performance", label: "Performance", icon: <BarChart3 size={15} /> },
    ],
  },
  {
    label: "Trading Books",
    items: [
      { key: "intraday", label: "Intraday", icon: <DollarSign size={15} /> },
      { key: "swing", label: "Swing", icon: <Layers size={15} /> },
      { key: "ltbook", label: "Long-Term", icon: <TrendingUp size={15} /> },
    ],
  },
  {
    label: "Research",
    items: [
      { key: "research", label: "Research & Guidance", icon: <BookOpen size={15} /> },
      { key: "news", label: "News & Alerts", icon: <Bell size={15} /> },
      { key: "fundamentals", label: "Fundamentals", icon: <Shield size={15} /> },
    ],
  },
  {
    label: "Engine",
    items: [
      { key: "control", label: "Control Center", icon: <Sliders size={15} /> },
      { key: "engine", label: "Engine Room", icon: <Wrench size={15} /> },
      { key: "llm", label: "LLM Usage", icon: <Cpu size={15} /> },
      { key: "logs", label: "System Logs", icon: <FileText size={15} /> },
    ],
  },
];

export default function App() {
  const [page, setPage] = useState("overview");
  useEffect(() => { bindNavigator(setPage); }, []);
  const [bot, setBot] = useState<any>(null);
  const [pf, setPf] = useState<any>(null);
  const [pendingCount, setPendingCount] = useState(0);

  // Light global poll for the header / sidebar status strip.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [b, p, a] = await Promise.all([
          getJSON("/api/bot/status"),
          getJSON("/api/portfolio/summary"),
          getJSON("/api/approvals"),
        ]);
        if (alive) { setBot(b); setPf(p); setPendingCount(Array.isArray(a) ? a.length : 0); }
      } catch { /* server away */ }
    };
    tick();
    const t = setInterval(tick, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const meta = PAGES[page];

  return (
    <div className="flex h-screen bg-[#040814] overflow-hidden text-slate-300">
      {/* ── Sidebar ── */}
      <aside className="w-60 flex-shrink-0 glass-panel border-r border-slate-800 flex flex-col">
        <div className="p-5 border-b border-slate-800/80 flex items-center gap-3">
          <div className={`w-8 h-8 rounded-lg grad-primary flex items-center justify-center ${bot?.status === "RUNNING" ? "active-pulse" : ""}`}>
            <Activity size={17} className="text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-200 to-purple-400 m-0 leading-none">
              Conviction Engine
            </h1>
            <span className="text-[9px] text-slate-500 uppercase tracking-widest">NSE · Paper Trading</span>
          </div>
        </div>

        <div className="px-5 py-3 border-b border-slate-800/80 space-y-1.5 text-[10px]">
          <div className="flex justify-between items-center">
            <span className="text-slate-500">Bot</span>
            <Badge text={bot?.status ?? "…"} />
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-500">Market</span>
            <Badge text={bot?.market_open ? "OPEN" : "CLOSED"} tone={bot?.market_open ? "OK" : "PENDING"} />
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-500">IST</span>
            <span className="font-mono text-slate-400">{bot?.market_time_ist ?? "—"}</span>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
          {NAV.map((group) => (
            <div key={group.label}>
              <div className="px-3 pb-1 text-[9px] font-bold uppercase tracking-widest text-slate-600">{group.label}</div>
              <div className="space-y-0.5">
                {group.items.map((item) => (
                  <button key={item.key} onClick={() => setPage(item.key)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] transition-all relative ${
                      page === item.key
                        ? "grad-primary text-white shadow-lg shadow-indigo-600/20 font-medium"
                        : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
                    }`}>
                    {item.icon}
                    {item.label}
                    {item.key === "control" && pendingCount > 0 && (
                      <span className="absolute right-2.5 bg-rose-500 text-white text-[9px] px-1.5 py-0.5 rounded-full font-bold active-pulse">
                        {pendingCount}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="p-4 border-t border-slate-800/80 text-[9px] text-slate-600 leading-relaxed">
          Paper trading — not financial advice. Validate everything in the Engine Room before trusting it.
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="h-16 border-b border-slate-800/80 bg-slate-950/40 backdrop-blur-md flex items-center justify-between px-7 flex-shrink-0 z-10">
          <div>
            <h2 className="text-base font-bold text-slate-100 m-0">{meta.title}</h2>
            <p className="text-[11px] text-slate-500 m-0 leading-tight">{meta.subtitle}</p>
          </div>
          <div className="text-right hidden sm:block">
            <div className="text-[9px] text-slate-500 uppercase tracking-wider">Intraday Pool</div>
            <div className="text-sm font-bold font-mono text-slate-100">{fmtINR(pf?.total_value)}</div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-6">
          {page === "overview" && <Overview go={setPage} />}
          {page === "control" && <Control />}
          {page === "intraday" && <Intraday />}
          {page === "swing" && <SwingBook />}
          {page === "ltbook" && <LongTermBook />}
          {page === "research" && <Research />}
          {page === "news" && <NewsAlerts />}
          {page === "fundamentals" && <Fundamentals />}
          {page === "engine" && <EngineRoom />}
          {page === "performance" && <Performance />}
          {page === "llm" && <LlmUsage />}
          {page === "logs" && <Logs />}
        </div>
      </main>
      <ToastHost />
    </div>
  );
}
