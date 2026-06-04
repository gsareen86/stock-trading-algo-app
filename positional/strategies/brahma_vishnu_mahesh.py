"""
Brahma-Vishnu-Mahesh Strategy — Vijay Thakkar style.

Top-down quantitative routine designed to only trade inside the strongest pockets of the market.
- [ BRAHMA ]: Market Regime Filter. Evaluates Nifty 50 on a weekly chart.
             Price must be trading above its rising 20-week SMA.
             If bearish, slashes score / conviction to represent sizing reduction or halt.
- [ VISHNU ]: Sector Outperformance Tracker. Ranks major NSE sectors based on rolling 3-month and 6-month
             Relative Strength against Nifty 50. Keeps only stocks inside the top 3 highest-performing sectors.
- [ MAHESH ]: Multi-Year Breakout Setup. Scans for stocks breaking out of a horizontal range
             or cup-and-handle structure of 1.5 to 3+ years on weekly volume > 3x average.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import IST, SECTOR_INDEX_TICKERS, POS_BVM_HALT_ON_BEARISH
from positional.strategies.base import BasePositionalStrategy, PositionalSignal
from positional.sectors import SECTOR_MAP as _SECTOR_MAP, ticker_sector as _ticker_sector

log = logging.getLogger(__name__)

# Cache for sectoral performance to avoid repeated downloads in the same scan run
_sector_performance_cache: Dict[str, float] = {}
_perf_cache_date: Optional[str] = None


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily candles to weekly candles (W-FRI ending)."""
    if df is None or df.empty:
        return pd.DataFrame()
    
    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        
    df_weekly = df.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()
    return df_weekly


def _fetch_weekly_nifty_regime() -> Tuple[bool, str]:
    """
    [ BRAHMA ] Check: Is Nifty 50 weekly close above its rising 20-week SMA?
    Returns (is_bullish, reason_str).
    """
    try:
        from data.fetcher import fetch_candles
        # Fetch 200 trading days (~40 weeks) of daily candles for Nifty 50
        nifty_df = fetch_candles("^NSEI", interval="1d", days=300)
        if nifty_df is None or nifty_df.empty:
            return False, "Nifty 50 data unavailable"
        
        nifty_w = _resample_weekly(nifty_df)
        if len(nifty_w) < 22:
            return False, f"Nifty weekly data insufficient (got {len(nifty_w)} weeks, need 22+)"
        
        close = nifty_w["Close"].astype(float)
        sma20 = close.rolling(window=20).mean()
        
        current_close = float(close.iloc[-1])
        current_sma = float(sma20.iloc[-1])
        prev_sma = float(sma20.iloc[-2])
        
        is_above = current_close > current_sma
        is_rising = current_sma > prev_sma
        
        is_bullish = is_above and is_rising
        reason = (f"Nifty={current_close:.1f} vs SMA20={current_sma:.1f} "
                  f"({'above' if is_above else 'below'} & {'rising' if is_rising else 'falling'})")
        return is_bullish, reason
    except Exception as e:
        log.warning("Brahma: market regime check failed: %s", e)
        return False, f"Error: {e}"


def _get_top_sectors() -> List[str]:
    """
    [ VISHNU ] Calculate Relative Strength of all major sectors over 3M and 6M windows.
    Returns list of top 3 sector keys descending.
    """
    global _sector_performance_cache, _perf_cache_date
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _perf_cache_date == today and _sector_performance_cache:
        # Rank and return top 3
        sorted_sectors = sorted(_sector_performance_cache.items(), key=lambda x: x[1], reverse=True)
        return [k for k, _ in sorted_sectors[:3]]

    returns: Dict[str, float] = {}
    try:
        from data.fetcher import fetch_candles
        
        # 1. Fetch benchmark Nifty 50 daily candles
        nifty_df = fetch_candles("^NSEI", interval="1d", days=180)
        if nifty_df is None or len(nifty_df) < 130:
            log.warning("Vishnu: Nifty 50 data insufficient for relative strength calculations")
            return []
            
        nifty_close = nifty_df["Close"].astype(float)
        
        # Lookback offsets (63 trading days ~ 3 months, 126 trading days ~ 6 months)
        # Verify index boundaries
        n = len(nifty_close)
        idx_3m = min(63, n - 1)
        idx_6m = min(126, n - 1)
        
        nifty_ret_3m = (float(nifty_close.iloc[-1]) - float(nifty_close.iloc[-idx_3m])) / float(nifty_close.iloc[-idx_3m]) * 100
        nifty_ret_6m = (float(nifty_close.iloc[-1]) - float(nifty_close.iloc[-idx_6m])) / float(nifty_close.iloc[-idx_6m]) * 100
        
        # 2. Fetch all sectors and calculate their Relative Strength
        for sector_key, yticker in SECTOR_INDEX_TICKERS.items():
            try:
                sec_df = fetch_candles(yticker, interval="1d", days=180)
                if sec_df is None or len(sec_df) < 130:
                    continue
                    
                sec_close = sec_df["Close"].astype(float)
                sec_ret_3m = (float(sec_close.iloc[-1]) - float(sec_close.iloc[-idx_3m])) / float(sec_close.iloc[-idx_3m]) * 100
                sec_ret_6m = (float(sec_close.iloc[-1]) - float(sec_close.iloc[-idx_6m])) / float(sec_close.iloc[-idx_6m]) * 100
                
                # Relative Strength sum
                rs_3m = sec_ret_3m - nifty_ret_3m
                rs_6m = sec_ret_6m - nifty_ret_6m
                
                returns[sector_key] = rs_3m + rs_6m
            except Exception as e:
                log.debug("Vishnu: sector %s calculations failed: %s", sector_key, e)
    except Exception as e:
        log.warning("Vishnu: sector outperformance tracking failed: %s", e)

    if returns:
        _sector_performance_cache = returns
        _perf_cache_date = today
        sorted_sectors = sorted(returns.items(), key=lambda x: x[1], reverse=True)
        return [k for k, _ in sorted_sectors[:3]]
    return []


class BrahmaVishnuMaheshStrategy(BasePositionalStrategy):
    name = "brahma_vishnu_mahesh"

    def __init__(self, halt_on_bearish: bool = POS_BVM_HALT_ON_BEARISH):
        self.halt_on_bearish = halt_on_bearish

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        # Minimum daily bars needed to build 3 years of weekly chart context (3 * 252 = 756 bars)
        # Let's verify we have at least 500 daily bars (~2 years)
        needed = 500
        if df is None or len(df) < needed:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason=f"need {needed}+ EOD daily bars (got {len(df) if df is not None else 0})")

        close_daily = df["Close"].astype(float)
        price = float(close_daily.iloc[-1])

        # ── [ BRAHMA ]: Market Regime Filter ────────────────────────────────
        is_market_bullish, brahma_reason = _fetch_weekly_nifty_regime()
        if not is_market_bullish and self.halt_on_bearish:
            return PositionalSignal(
                ticker, "HOLD", self.name, 30.0, price,
                reason=f"Brahma: Bearish Market Regime Filter ({brahma_reason}) — trading halted",
                meta={"market_regime": "BEARISH", "brahma_reason": brahma_reason}
            )

        # ── [ VISHNU ]: Sector Outperformance Tracker ──────────────────────
        raw_sector = _ticker_sector(ticker)
        sector_key = None
        if raw_sector:
            for k, v in _SECTOR_MAP.items():
                if k in raw_sector:
                    sector_key = v
                    break

        if sector_key is None:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason=f"Vishnu: Sector unknown ({raw_sector or 'None'}) — cannot evaluate outperformance")

        top_sectors = _get_top_sectors()
        if not top_sectors:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="Vishnu: Sector ranking unavailable")

        is_sector_strong = sector_key in top_sectors
        if not is_sector_strong:
            return PositionalSignal(
                ticker, "HOLD", self.name, 45.0, price,
                reason=f"Vishnu: Sector '{sector_key}' not in top 3 outperforming sectors {top_sectors}",
                meta={"sector": sector_key, "top_sectors": top_sectors}
            )

        # ── [ MAHESH ]: Stock Execution Matrix ──────────────────────────────
        # Resample daily stock data to weekly
        df_weekly = _resample_weekly(df)
        
        # Verify weekly data length (need at least 79 weeks for 1.5 year lookback)
        min_weeks = 79
        if len(df_weekly) < min_weeks:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason=f"Mahesh: Insufficient weekly data (got {len(df_weekly)} weeks, need {min_weeks}+)")

        close_w = df_weekly["Close"].astype(float)
        high_w = df_weekly["High"].astype(float)
        low_w = df_weekly["Low"].astype(float)
        vol_w = df_weekly["Volume"].astype(float)

        # Calculate previous multi-year maximums (excluding current week)
        # 1.5 Year (78 weeks)
        lookback_1_5y = min(78, len(df_weekly) - 2)
        h_max_1_5y = float(high_w.iloc[-lookback_1_5y - 1 : -1].max())
        l_min_1_5y = float(low_w.iloc[-lookback_1_5y - 1 : -1].min())

        # 3 Years (156 weeks)
        lookback_3y = min(156, len(df_weekly) - 2)
        h_max_3y = float(high_w.iloc[-lookback_3y - 1 : -1].max())
        l_min_3y = float(low_w.iloc[-lookback_3y - 1 : -1].min())

        # Consolidation check: prevent chasing vertical blow-offs by ensuring historical range is relatively compact
        consolidation_pct_1_5y = (h_max_1_5y - l_min_1_5y) / h_max_1_5y * 100 if h_max_1_5y > 0 else 100.0
        
        # We check breakouts of either a 1.5-year high or a 3-year high
        is_breakout_1_5y = price > h_max_1_5y and consolidation_pct_1_5y <= 50.0
        is_breakout_3y = price > h_max_3y

        is_breakout = is_breakout_1_5y or is_breakout_3y
        if not is_breakout:
            reason = f"Mahesh: Awaiting multi-year breakout (1.5Y resistance={h_max_1_5y:.2f}, 3Y resistance={h_max_3y:.2f})"
            return PositionalSignal(ticker, "HOLD", self.name, 55.0, price, reason=reason)

        # Volume spike check: Breakout week volume > 3x average of previous 20 weeks
        vol_avg_20w = float(vol_w.iloc[-21:-1].mean()) or 1.0
        vol_current = float(vol_w.iloc[-1])
        vol_ratio = vol_current / vol_avg_20w

        is_vol_spike = vol_ratio >= 3.0
        if not is_vol_spike:
            reason = f"Mahesh: Breakout price confirmed but volume spike too weak ({vol_ratio:.1f}x vs 3.0x threshold)"
            return PositionalSignal(ticker, "HOLD", self.name, 58.0, price, reason=reason)

        # ── SUCCESSFUL BUY SIGNAL TRIGGERED ──
        # Calculate conviction and score
        base_score = 72.0
        if is_breakout_3y:
            base_score += 6.0  # 3-year breakouts carry stronger momentum
        
        # Add volume kicker and quality kicker
        vol_kicker = min(8.0, (vol_ratio - 3.0) * 1.5)
        quality_kicker = (quality_score - 50.0) / 10.0
        
        score = self._clip(base_score + vol_kicker + quality_kicker)
        
        # If market regime is bearish but halt_on_bearish=False, slash position size by 70%
        final_conviction = "high" if is_breakout_3y else "medium"
        final_reason = (
            f"BVM Breakout: {('3-Year' if is_breakout_3y else '1.5-Year')} horizontal breakout in outperforming sector '{sector_key}', "
            f"volume spike {vol_ratio:.1f}x (threshold 3x). {brahma_reason}"
        )
        
        meta = {
            "breakout_type": "3-Year" if is_breakout_3y else "1.5-Year",
            "sector": sector_key,
            "sector_rank": top_sectors.index(sector_key) + 1,
            "resistance_broken": h_max_3y if is_breakout_3y else h_max_1_5y,
            "weekly_vol_ratio": round(vol_ratio, 2),
            "market_regime": "BULLISH" if is_market_bullish else "BEARISH",
            "slash_position_size": not is_market_bullish
        }

        # Slash score by 70% if bearish market regime (if we are allowed to proceed instead of halt)
        if not is_market_bullish:
            score = self._clip(score * 0.3)
            final_conviction = "low"
            final_reason = f"[SIZING SLASHED - BEARISH BRAHMA] {final_reason}"

        return PositionalSignal(
            ticker=ticker,
            action="BUY",
            strategy=self.name,
            score=score,
            price=price,
            reason=final_reason,
            hold_days=30,  # Longer-term positional holding
            conviction=final_conviction,
            meta=meta
        )
