/* Per-ticker scan inspector — shared by the Swing Book and Long-Term Book.
   Shows WHY a row scored what it did: which strategies fired (in plain
   language), the raw scan reading, the pillar breakdown, a 1-year chart with
   the moving averages the strategies actually use — and one-click jumps to
   the Research, News and Fundamentals views for the same ticker. */
import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { X, Microscope, BookOpen, Bell, Shield } from "lucide-react";
import { fmtINR, fmtIST, getJSON } from "../api";
import { Badge, Btn } from "./ui";
import { goToTicker } from "../nav";

export const STRATEGY_INFO: Record<string, { name: string; desc: string; hold: string }> = {
  minervini_vcp: {
    name: "Minervini VCP",
    desc: "Stage-2 uptrend (price > rising 50/150/200 MAs, near 52-week high) plus a Volatility Contraction Pattern: successive pullbacks get tighter while volume dries up — supply is exhausted. Entry is the breakout from the final tight pivot.",
    hold: "~18 trading days",
  },
  brahma_vishnu_mahesh: {
    name: "Brahma-Vishnu-Mahesh",
    desc: "Multi-timeframe trend alignment: creation (base), preservation (trend intact across timeframes) and momentum legs must agree, gated by a market-health filter. Rides established trends rather than catching breakouts.",
    hold: "~30 trading days",
  },
  fun_tech_momentum: {
    name: "Fundamental-Technical Momentum",
    desc: "CANSLIM-style: strong earnings/sales acceleration combined with a tight technical range near highs. The fundamental engine confirms the move is earned, the technical setup times the entry.",
    hold: "~15 trading days",
  },
  young_momentum: {
    name: "Young Momentum",
    desc: "A fresh 20–50% impulse leg followed by a short, shallow pause (≤6 bars, retracing less than 38.2%). Enters the continuation while the move is still young — momentum begets momentum.",
    hold: "~10 trading days",
  },
  ipo_base: {
    name: "IPO First Base",
    desc: "O'Neil's new-issue playbook for listings under 12 months old (too young for the 220-day trend template): wait out the first ~25 sessions of price discovery, then buy the breakout from the first proper base — ≥3 weeks of consolidation, depth under 25%, price above the 10/21 EMA, breakout on ≥1.5× volume. Entries are blocked around lock-in expiry dates (known supply events).",
    hold: "~10 trading days",
  },
};

export function PillarBar({ label, value }: { label: string; value: number | null | undefined }) {
  const v = value == null ? null : Math.max(0, Math.min(100, Number(value)));
  const color = v == null ? "#334155" : v >= 70 ? "#10b981" : v >= 50 ? "#6366f1" : v >= 35 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className="w-24 text-slate-500 uppercase tracking-wider font-semibold">{label}</span>
      <div className="flex-1 h-2 bg-slate-800/80 rounded-full overflow-hidden">
        {v != null && <div className="h-full rounded-full" style={{ width: `${v}%`, background: color }} />}
      </div>
      <span className="w-8 text-right font-mono text-slate-300">{v == null ? "—" : Math.round(v)}</span>
    </div>
  );
}

export default function ScanInspector({ row, onClose }: { row: any; onClose: () => void }) {
  const [series, setSeries] = useState<any[] | null>(null);
  useEffect(() => {
    let alive = true;
    setSeries(null);
    getJSON(`/api/fundamentals/price-history/${row.ticker}?period=1Y`)
      .then((d) => {
        if (!alive) return;
        const rows = d.series ?? [];
        let ema = rows.length ? Number(rows[0].close) : 0;
        const k = 2 / 22;
        for (const p of rows) {
          ema = p.close * k + ema * (1 - k);
          p.ema21 = Math.round(ema * 100) / 100;
        }
        setSeries(rows);
      })
      .catch(() => alive && setSeries([]));
    return () => { alive = false; };
  }, [row.ticker]);

  const fired = String(row.strategies_fired || "").split(",").map((s: string) => s.trim()).filter(Boolean);

  return (
    <div className="bg-slate-950/70 border border-indigo-500/25 rounded-2xl p-4 space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Microscope size={15} className="text-indigo-400" />
        <span className="font-bold text-slate-100">{row.ticker}</span>
        <Badge text={row.alert_type} />
        {row.horizon && <Badge text={row.horizon} />}
        {row.conviction && <Badge text={row.conviction} />}
        <span className="text-[10px] text-slate-500">scanned {fmtIST(row.scanned_at)} @ {fmtINR(row.price)}</span>
        <span className="flex-1" />
        {/* One-click 360° view of the same stock */}
        <Btn onClick={() => goToTicker("research", row.ticker)} title="LLM research, thesis & guidance ledger for this stock">
          <BookOpen size={11} /> Research
        </Btn>
        <Btn onClick={() => goToTicker("news", row.ticker)} title="News, sentiment & impact alerts for this stock">
          <Bell size={11} /> News
        </Btn>
        <Btn onClick={() => goToTicker("fundamentals", row.ticker)} title="Financial scorecard for this stock">
          <Shield size={11} /> Fundamentals
        </Btn>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-200"><X size={15} /></button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="space-y-3">
          <div>
            <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1.5">
              Strategies that fired ({fired.length || 0})
            </div>
            {fired.length === 0 ? (
              <div className="text-[11px] text-slate-500">No strategy fired — this row is a WATCH/HOLD scored on the trend template alone.</div>
            ) : (
              <div className="space-y-2">
                {fired.map((key: string) => {
                  const info = STRATEGY_INFO[key];
                  return (
                    <div key={key} className="bg-slate-900/60 border border-slate-800/70 rounded-lg p-2.5">
                      <div className="flex items-center gap-2">
                        <Badge text={info?.name ?? key} tone="OK" />
                        <span className="text-[9px] text-slate-500">expected hold {info?.hold ?? "—"}</span>
                      </div>
                      <p className="text-[10px] text-slate-400 mt-1.5 mb-0 leading-relaxed">{info?.desc ?? ""}</p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div>
            <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1.5">Scan detail (trend template + VCP read)</div>
            <p className="text-[10px] text-slate-400 font-mono leading-relaxed whitespace-pre-wrap m-0 bg-slate-900/50 rounded-lg p-2.5 border border-slate-800/60">{row.reason || "—"}</p>
          </div>
          <div className="space-y-1.5">
            <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1.5">Scorecard pillars</div>
            <PillarBar label="Timing" value={row.timing_score} />
            <PillarBar label="Durability" value={row.durability_score} />
            <PillarBar label="Quality" value={row.quality_pillar} />
            <PillarBar label="Valuation" value={row.valuation_pillar} />
            <PillarBar label="Momentum" value={row.momentum_pillar} />
            <PillarBar label="Sentiment" value={row.sentiment_pillar} />
            <PillarBar label="Management" value={row.management_pillar} />
          </div>
        </div>

        <div>
          <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1.5">
            1-year price · 21-EMA (trail) · 50/200 DMA (trend template)
          </div>
          <div className="h-72 text-[10px] font-mono">
            {series === null ? (
              <div className="h-full flex items-center justify-center text-slate-500 text-xs">loading chart…</div>
            ) : series.length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-500 text-xs">price history unavailable</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" opacity={0.3} />
                  <XAxis dataKey="ts" stroke="#475569" minTickGap={50} />
                  <YAxis stroke="#475569" domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ backgroundColor: "#090d1a", borderColor: "#1e293b", color: "#e2e8f0" }} />
                  <Legend wrapperStyle={{ fontSize: "10px" }} />
                  <Line type="monotone" dataKey="close" name="Close" stroke="#e2e8f0" strokeWidth={1.6} dot={false} />
                  <Line type="monotone" dataKey="ema21" name="21 EMA" stroke="#f59e0b" strokeWidth={1} dot={false} />
                  <Line type="monotone" dataKey="sma50" name="50 DMA" stroke="#6366f1" strokeWidth={1} dot={false} />
                  <Line type="monotone" dataKey="sma200" name="200 DMA" stroke="#ef4444" strokeWidth={1} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
