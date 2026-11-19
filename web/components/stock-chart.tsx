"use client";

import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import type { Plan, StockChartBar, StockChartResponse } from "@/lib/api";

type RangeKey = "3M" | "6M" | "1Y" | "3Y";

function cssVar(name: string, fallbackRgb: string): string {
  if (typeof window === "undefined") return fallbackRgb;
  const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return val || fallbackRgb;
}

export type PlanOption = {
  strategyId: string;
  stance: string;
  plan: Plan;
};

export function StockChart({
  symbol,
  initialChart,
  plans,
  selectedPlanStrategy,
  onSelectPlanStrategy,
}: {
  symbol: string;
  initialChart: StockChartResponse | null;
  plans: PlanOption[];
  selectedPlanStrategy: string | null;
  onSelectPlanStrategy: (sid: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState<RangeKey>((initialChart?.range as RangeKey) ?? "1Y");
  const [chartData, setChartData] = useState<StockChartResponse | null>(initialChart);
  const [loadingRange, setLoadingRange] = useState(false);

  const [showEma20, setShowEma20] = useState(true);
  const [showSma50, setShowSma50] = useState(true);
  const [showSma150, setShowSma150] = useState(false);
  const [showSma200, setShowSma200] = useState(true);

  async function switchRange(next: RangeKey) {
    setRange(next);
    setLoadingRange(true);
    try {
      const res = await fetch(
        `/api/backend/stocks/${encodeURIComponent(symbol)}/chart?range=${next}`,
      );
      if (res.ok) {
        const body = (await res.json()) as StockChartResponse;
        setChartData(body);
      }
    } finally {
      setLoadingRange(false);
    }
  }

  useEffect(() => {
    const el = containerRef.current;
    const bars: StockChartBar[] = chartData?.bars ?? [];
    if (!el || !chartData?.available || bars.length === 0) return;

    const textPrimary = cssVar("--text-primary", "rgb(15, 23, 42)");
    const textMuted = cssVar("--text-muted", "rgb(100, 116, 139)");
    const borderSubtle = cssVar("--border-subtle", "rgb(226, 232, 240)");
    const surfaceRaised = cssVar("--surface-raised", "rgb(255, 255, 255)");
    const buyTone = cssVar("--stance-buy", "rgb(5, 150, 105)");
    const avoidTone = cssVar("--stance-avoid", "rgb(220, 38, 38)");
    const watchTone = cssVar("--stance-watch", "rgb(217, 119, 6)");
    const accentTone = cssVar("--accent", "rgb(79, 70, 229)");
    const improvingTone = cssVar("--quadrant-improving", "rgb(37, 99, 235)");

    const chart = createChart(el, {
      width: el.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: surfaceRaised },
        textColor: textMuted,
      },
      grid: {
        vertLines: { color: borderSubtle },
        horzLines: { color: borderSubtle },
      },
      rightPriceScale: {
        borderColor: borderSubtle,
      },
      timeScale: {
        borderColor: borderSubtle,
        timeVisible: false,
      },
      crosshair: {
        vertLine: { color: textPrimary, labelBackgroundColor: textPrimary },
        horzLine: { color: textPrimary, labelBackgroundColor: textPrimary },
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: buyTone,
      downColor: avoidTone,
      borderUpColor: buyTone,
      borderDownColor: avoidTone,
      wickUpColor: buyTone,
      wickDownColor: avoidTone,
    });
    candleSeries.setData(
      bars.map((b) => ({
        time: b.time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });
    volumeSeries.setData(
      bars.map((b) => ({
        time: b.time,
        value: b.volume,
        color: b.close >= b.open ? buyTone : avoidTone,
      })),
    );

    function addMa(
      visible: boolean,
      key: "ema20" | "sma50" | "sma150" | "sma200",
      color: string,
      title: string,
    ) {
      if (!visible) return;
      const pts = bars
        .filter((b) => b[key] !== null)
        .map((b) => ({ time: b.time, value: b[key] as number }));
      if (pts.length === 0) return;
      const s = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        title,
        priceLineVisible: false,
      });
      s.setData(pts);
    }

    addMa(showEma20, "ema20", watchTone, "EMA 20");
    addMa(showSma50, "sma50", accentTone, "SMA 50");
    addMa(showSma150, "sma150", improvingTone, "SMA 150");
    addMa(showSma200, "sma200", textMuted, "SMA 200");

    const activePlan = plans.find((p) => p.strategyId === selectedPlanStrategy)?.plan;
    if (activePlan) {
      candleSeries.createPriceLine({
        price: activePlan.entry,
        color: accentTone,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Entry ₹${activePlan.entry}`,
      });
      candleSeries.createPriceLine({
        price: activePlan.stop,
        color: avoidTone,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Stop ₹${activePlan.stop}`,
      });
      if (typeof activePlan.target === "number") {
        candleSeries.createPriceLine({
          price: activePlan.target,
          color: buyTone,
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: `Target ₹${activePlan.target}`,
        });
      }
    }

    chart.timeScale().fitContent();

    const observer = new ResizeObserver(() => {
      if (el) chart.applyOptions({ width: el.clientWidth });
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [
    chartData,
    showEma20,
    showSma50,
    showSma150,
    showSma200,
    plans,
    selectedPlanStrategy,
  ]);

  return (
    <section className="card-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Price Action &amp; Setup Levels
          </h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            Daily OHLCV candles, moving averages, and deterministic strategy plan overlays
          </p>
        </div>

        <div className="flex items-center gap-1 rounded-token bg-surface-sunken p-1">
          {(["3M", "6M", "1Y", "3Y"] as const).map((r) => (
            <button
              key={r}
              type="button"
              disabled={loadingRange}
              onClick={() => switchRange(r)}
              className={`rounded-token px-2.5 py-1 font-mono text-xs transition-colors ${
                range === r
                  ? "bg-surface-raised font-semibold text-text-primary shadow-xs"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-y border-border-subtle py-2.5">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="mr-1 text-[11px] text-text-muted">Overlays:</span>
          {[
            { label: "20 EMA", active: showEma20, toggle: () => setShowEma20((v) => !v) },
            { label: "50 SMA", active: showSma50, toggle: () => setShowSma50((v) => !v) },
            { label: "150 SMA", active: showSma150, toggle: () => setShowSma150((v) => !v) },
            { label: "200 SMA", active: showSma200, toggle: () => setShowSma200((v) => !v) },
          ].map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={item.toggle}
              className={`rounded-token border px-2 py-0.5 font-mono text-[11px] transition-colors ${
                item.active
                  ? "border-accent bg-accent-soft text-accent font-medium"
                  : "border-border-subtle bg-surface-sunken text-text-muted"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        {plans.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-[11px] text-text-muted">Plan lines:</span>
            <button
              type="button"
              onClick={() => onSelectPlanStrategy(null)}
              className={`rounded-token border px-2 py-0.5 text-[11px] ${
                selectedPlanStrategy === null
                  ? "border-border-strong bg-surface-sunken font-medium text-text-primary"
                  : "border-border-subtle text-text-muted"
              }`}
            >
              Off
            </button>
            {plans.map((p) => (
              <button
                key={p.strategyId}
                type="button"
                onClick={() => onSelectPlanStrategy(p.strategyId)}
                className={`rounded-token border px-2 py-0.5 text-[11px] ${
                  selectedPlanStrategy === p.strategyId
                    ? "border-accent bg-accent-soft font-semibold text-accent"
                    : "border-border-subtle bg-surface-sunken text-text-secondary"
                }`}
              >
                {p.strategyId}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {!chartData || !chartData.available || chartData.bars.length === 0 ? (
        <div className="mt-4 flex h-[360px] items-center justify-center rounded-token bg-surface-sunken px-6 text-center">
          <p className="text-sm text-text-secondary">
            {chartData?.reason ?? `Price history unavailable for ${symbol}.`}
          </p>
        </div>
      ) : (
        <div ref={containerRef} className="mt-3 w-full" style={{ height: 360 }} />
      )}
    </section>
  );
}
