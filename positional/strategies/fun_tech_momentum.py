"""
Fundamental-Technical Momentum Alpha Strategy — Ashwin Raghavan style.

A hyper-systematic CANSLIM-style model custom-tailored for Indian equities,
where corporate earnings surprises drive massive institutional momentum.

Rules:
1. Quantitative Fundamental Screen:
   - Check quarterly EPS and Sales from yfinance (cached).
   - Must satisfy:
     (QoQ EPS >= 1.5 * YoY Qtr EPS) OR (QoQ Sales >= 1.5 * YoY Qtr Sales)
     AND
     (QoQ EPS >= 1.1 * Preceding Qtr EPS)
2. Technical Entry Setup:
   - Daily chart.
   - Price must be trading within 15% of its 52-week highs.
   - Forms a tight, low-volatility consolidation base (high tight flag or mini-VCP) lasting 2 to 6 weeks.
   - Trigger: Close above consolidation resistance on volume expansion > 100% of 20-day average volume.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import yfinance as yf

from config import CACHE_DIR, POS_FTM_TIGHT_RANGE_LIMIT
from data.universe import to_yf_ticker
from positional.strategies.base import BasePositionalStrategy, PositionalSignal

log = logging.getLogger(__name__)


def _extract_quarterly_metrics(df_q: pd.DataFrame) -> Optional[dict]:
    """Sort and extract the last 5 quarters of Sales and EPS/NetIncome."""
    if df_q is None or df_q.empty:
        return None

    # Sort columns descending (newest first)
    df_q = df_q.sort_index(axis=1, ascending=False)

    # Need at least 5 quarters for Q0 vs Q4 YoY comparison
    if df_q.shape[1] < 5:
        log.debug("FunTech: insufficient quarters in financials table (got %d, need 5+)", df_q.shape[1])
        return None

    # 1. Total Revenue / Sales
    sales_labels = ["Total Revenue", "Operating Revenue", "Revenue"]
    sales_row = None
    for label in sales_labels:
        if label in df_q.index:
            sales_row = df_q.loc[label].dropna()
            break

    # 2. EPS or Net Income (to proxy EPS growth ratio)
    eps_labels = ["Basic EPS", "Diluted EPS", "Net Income Common Stockholders", "Net Income"]
    eps_row = None
    for label in eps_labels:
        if label in df_q.index:
            eps_row = df_q.loc[label].dropna()
            break

    if sales_row is None or eps_row is None or len(sales_row) < 5 or len(eps_row) < 5:
        log.debug("FunTech: failed to locate sales or earnings rows in yfinance quarterly_financials")
        return None

    return {
        "sales": [float(x) for x in sales_row.iloc[:5]],
        "eps": [float(x) for x in eps_row.iloc[:5]]
    }


def get_quarterly_data(ticker: str) -> Optional[dict]:
    """Retrieve quarterly metrics from local JSON cache or fetch from yfinance (7-day TTL)."""
    cache_path = Path(CACHE_DIR) / f"quarterly_{ticker.replace('.', '_')}.json"
    
    # Cache hit check (7 days TTL)
    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < 7 * 24 * 3600:
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except Exception:
            pass

    try:
        yf_t = to_yf_ticker(ticker)
        t = yf.Ticker(yf_t)
        q = t.quarterly_financials
        metrics = _extract_quarterly_metrics(q)
        if metrics:
            # Ensure directory exists and write
            cache_path.parent.mkdir(exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(metrics, f)
            log.info("FunTech: cached quarterly financials for %s", ticker)
            return metrics
    except Exception as e:
        log.warning("FunTech: yfinance quarterly fetch failed for %s: %s", ticker, e)
    return None


class FunTechMomentumStrategy(BasePositionalStrategy):
    name = "fun_tech_momentum"

    def __init__(self, tight_range_limit: float = POS_FTM_TIGHT_RANGE_LIMIT):
        self.tight_range_limit = tight_range_limit

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        # Need at least 260 daily bars for 52-week high calculation
        needed = 260
        if df is None or len(df) < needed:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason=f"need {needed}+ EOD daily bars (got {len(df) if df is not None else 0})")

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float)
        
        price = float(close.iloc[-1])
        vol_today = float(volume.iloc[-1])

        # ── 1. The Quantitative Fundamental Screen ────────────────────────────
        metrics = get_quarterly_data(ticker)
        if not metrics:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="Fundamental: Quarterly financials data unavailable or insufficient")

        # Q0 = current qtr (idx 0), Q1 = preceding qtr (idx 1), Q4 = YoY qtr (idx 4)
        sales = metrics["sales"]
        eps = metrics["eps"]

        q0_eps, q1_eps, q4_eps = eps[0], eps[1], eps[4]
        q0_sales, q4_sales = sales[0], sales[4]

        # EPS surprise YoY or Sales surprise YoY
        eps_yoy_growth = q0_eps >= 1.5 * q4_eps if q4_eps > 0 else (q0_eps > 0 and q4_eps <= 0)
        sales_yoy_growth = q0_sales >= 1.5 * q4_sales if q4_sales > 0 else False
        
        # QoQ EPS growth vs preceding quarter
        eps_qoq_growth = q0_eps >= 1.1 * q1_eps if q1_eps > 0 else (q0_eps > 0 and q1_eps <= 0)

        passed_fundamental = (eps_yoy_growth or sales_yoy_growth) and eps_qoq_growth
        
        # Detail growth values for logging / signal meta
        eps_yoy_ratio = q0_eps / q4_eps if q4_eps > 0 else 0.0
        sales_yoy_ratio = q0_sales / q4_sales if q4_sales > 0 else 0.0
        eps_qoq_ratio = q0_eps / q1_eps if q1_eps > 0 else 0.0

        if not passed_fundamental:
            reason = (f"Fundamental: Failed financial momentum (EPS YoY={eps_yoy_ratio:.2f}x, "
                      f"Sales YoY={sales_yoy_ratio:.2f}x, EPS QoQ={eps_qoq_ratio:.2f}x)")
            return PositionalSignal(ticker, "HOLD", self.name, 45.0, price, reason=reason)

        # ── 2. The Technical Entry Setup ─────────────────────────────────────
        
        # A. 52-Week Proximity Check
        high_52w = float(high.tail(252).max())
        proximity_pct = (high_52w - price) / high_52w * 100 if high_52w > 0 else 100.0
        
        if proximity_pct > 15.0:
            reason = f"Technical: Price is {proximity_pct:.1f}% below 52-week high (limit is 15.0%)"
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price, reason=reason)

        # B. Consolidation Base (resembling high tight flag or mini-VCP lasting 2-6 weeks)
        # Scan different base lengths (from 10 to 30 trading days) ending yesterday
        found_base = False
        best_base_len = 0
        best_range = 100.0
        best_res = 0.0

        for base_len in range(10, 31, 5):
            # Exclude today's breakout candle
            slice_high = high.iloc[-base_len - 1 : -1]
            slice_low = low.iloc[-base_len - 1 : -1]
            slice_close = close.iloc[-base_len - 1 : -1]
            
            c_high = float(slice_high.max())
            c_low = float(slice_low.min())
            c_res = float(slice_close.max())  # Consolidation resistance high water mark
            
            base_range = (c_high - c_low) / c_high * 100 if c_high > 0 else 100.0
            
            if base_range <= self.tight_range_limit:
                found_base = True
                if base_range < best_range:
                    best_range = base_range
                    best_base_len = base_len
                    best_res = c_res

        if not found_base:
            reason = f"Technical: No tight 2-6 week consolidation base detected (range exceeds {self.tight_range_limit}%)"
            return PositionalSignal(ticker, "HOLD", self.name, 55.0, price, reason=reason)

        # C. Volatility Dry-Up Check (last 5 days ATR vs last 20 days ATR)
        atr = self._atr(df, period=14)
        atr_5d = float(atr.iloc[-6:-1].mean()) or 1.0
        atr_20d = float(atr.iloc[-21:-1].mean()) or 1.0
        vol_dry = atr_5d / atr_20d < 0.95

        if not vol_dry:
            reason = f"Technical: Tight base found ({best_base_len}d range={best_range:.1f}%) but volatility is expanding (ATR 5d/20d={atr_5d/atr_20d:.2f})"
            return PositionalSignal(ticker, "HOLD", self.name, 57.0, price, reason=reason)

        # D. Breakout & Volume Trigger
        vol_avg_20d = float(volume.iloc[-21:-1].mean()) or 1.0
        vol_ratio = vol_today / vol_avg_20d
        
        is_breakout = price > best_res
        is_vol_expansion = vol_ratio >= 2.0

        if not is_breakout:
            reason = f"Technical: Awaiting breakout close above consolidation resistance ({best_res:.2f})"
            return PositionalSignal(ticker, "HOLD", self.name, 59.0, price, reason=reason)
            
        if not is_vol_expansion:
            reason = f"Technical: Breakout price confirmed but volume too low ({vol_ratio:.1f}x vs 2.0x threshold)"
            return PositionalSignal(ticker, "HOLD", self.name, 60.0, price, reason=reason)

        # ── SUCCESSFUL BUY SIGNAL TRIGGERED ──
        # Calculate conviction and score
        base_score = 75.0
        vol_kicker = min(8.0, (vol_ratio - 2.0) * 2.0)
        fund_kicker = min(7.0, (eps_yoy_ratio - 1.5) * 1.5 + (sales_yoy_ratio - 1.5) * 1.0)
        quality_kicker = (quality_score - 50.0) / 10.0
        
        score = self._clip(base_score + vol_kicker + fund_kicker + quality_kicker)

        final_reason = (
            f"Fundamental-Technical Breakout: Tight consolidation breakout (Base {best_base_len}d, Range {best_range:.1f}%) "
            f"on {vol_ratio:.1f}x average volume. Solid financial momentum: YoY EPS={eps_yoy_ratio:.1f}x, "
            f"YoY Sales={sales_yoy_ratio:.1f}x, QoQ EPS={eps_qoq_ratio:.1f}x."
        )

        meta = {
            "base_length_days": best_base_len,
            "base_range_pct": round(best_range, 2),
            "resistance_broken": round(best_res, 2),
            "daily_vol_ratio": round(vol_ratio, 2),
            "eps_yoy_ratio": round(eps_yoy_ratio, 2),
            "sales_yoy_ratio": round(sales_yoy_ratio, 2),
            "eps_qoq_ratio": round(eps_qoq_ratio, 2),
            "proximity_52w_pct": round(proximity_pct, 2)
        }

        return PositionalSignal(
            ticker=ticker,
            action="BUY",
            strategy=self.name,
            score=score,
            price=price,
            reason=final_reason,
            hold_days=15,  # Moderate hold period (PEAD drift window)
            conviction="high" if score >= 82.0 else "medium",
            meta=meta
        )
