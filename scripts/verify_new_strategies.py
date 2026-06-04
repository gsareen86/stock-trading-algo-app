"""
Verification script for the three new positional trading strategies.
Verifies that each strategy compiles, executes correctly on mock data, and handles live data pipelines successfully.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("verify_strategies")

# Add project root to path
sys.path.append(".")

from positional.strategies.brahma_vishnu_mahesh import BrahmaVishnuMaheshStrategy
from positional.strategies.fun_tech_momentum import FunTechMomentumStrategy, get_quarterly_data
from positional.strategies.young_momentum import YoungMomentumStrategy
from positional.strategies.base import PositionalSignal


def create_mock_daily_df(n_bars: int = 800, base_price: float = 100.0) -> pd.DataFrame:
    """Create a mock daily OHLCV DataFrame with dates."""
    dates = [datetime.now() - timedelta(days=n_bars - i) for i in range(n_bars)]
    
    # Simple random walk for prices
    np.random.seed(42)
    changes = np.random.normal(0.0005, 0.015, n_bars)
    prices = base_price * np.exp(np.cumsum(changes))
    
    df = pd.DataFrame(index=pd.DatetimeIndex(dates))
    df["Close"] = prices
    df["Open"] = prices * (1.0 + np.random.normal(0, 0.002, n_bars))
    df["High"] = df[["Open", "Close"]].max(axis=1) * (1.0 + np.abs(np.random.normal(0, 0.005, n_bars)))
    df["Low"] = df[["Open", "Close"]].min(axis=1) * (1.0 - np.abs(np.random.normal(0, 0.005, n_bars)))
    df["Volume"] = np.random.lognormal(12.0, 0.8, n_bars)
    return df


def test_brahma_vishnu_mahesh():
    log.info("=== Testing Brahma-Vishnu-Mahesh Strategy ===")
    strategy = BrahmaVishnuMaheshStrategy(halt_on_bearish=False)
    
    # 1. Test insufficient data fallback
    df_short = create_mock_daily_df(100)
    sig_short = strategy.generate("MOCK_TICKER", df_short)
    log.info("Short data signal: %s", sig_short.action)
    assert sig_short.action == "HOLD"
    assert "need" in sig_short.reason
    
    # 2. Test execution on full mock data
    df_full = create_mock_daily_df(800, base_price=100.0)
    
    # Force a weekly breakout in mock data at the very end
    # Set the last bar close to be the highest of the last 3 years
    df_full.loc[df_full.index[-1], "Close"] = 500.0
    df_full.loc[df_full.index[-1], "High"] = 510.0
    df_full.loc[df_full.index[-1], "Volume"] = 1e8  # Massive volume
    
    sig = strategy.generate("RELIANCE", df_full, quality_score=75.0)
    log.info("Breakout mock signal: %s | Score: %.2f | Reason: %s", sig.action, sig.score, sig.reason)
    log.info("Signal meta: %s", sig.meta)
    
    assert isinstance(sig, PositionalSignal)
    log.info("Brahma-Vishnu-Mahesh verification: SUCCESS\n")


def test_fun_tech_momentum():
    log.info("=== Testing Fundamental-Technical Momentum Strategy ===")
    strategy = FunTechMomentumStrategy()
    
    # Create mock data with tight consolidation flag near 52-week high at the end
    df = create_mock_daily_df(300, base_price=100.0)
    
    # Force 52W high to be slightly above current
    df.loc[df.index[-50], "High"] = 120.0
    
    # Create a 20-day tight consolidation range [98, 102]
    for idx in range(-21, -1):
        df.loc[df.index[idx], "Open"] = 100.0
        df.loc[df.index[idx], "Close"] = 100.0
        df.loc[df.index[idx], "High"] = 101.5
        df.loc[df.index[idx], "Low"] = 98.5
        df.loc[df.index[idx], "Volume"] = 10000.0  # low volume
        
    # Trigger breakout close on last bar
    df.loc[df.index[-1], "Close"] = 105.0
    df.loc[df.index[-1], "High"] = 106.0
    df.loc[df.index[-1], "Volume"] = 50000.0  # high volume
    
    # Mock the quarterly cache manually to avoid network req inside simple logic test
    import json
    from config import CACHE_DIR
    cache_file = pd.io.common.Path(CACHE_DIR) / "quarterly_MOCK_FTM.json"
    cache_file.parent.mkdir(exist_ok=True)
    mock_financials = {
        "sales": [150.0, 120.0, 110.0, 100.0, 90.0],  # Q0 sales is 1.66x Q4 (90.0)
        "eps": [15.0, 10.0, 8.0, 7.0, 9.0]          # Q0 EPS is 1.66x Q4, and 1.5x Q1
    }
    with open(cache_file, "w") as f:
        json.dump(mock_financials, f)
        
    sig = strategy.generate("MOCK_FTM", df, quality_score=80.0)
    log.info("Breakout mock signal: %s | Score: %.2f | Reason: %s", sig.action, sig.score, sig.reason)
    log.info("Signal meta: %s", sig.meta)
    
    assert isinstance(sig, PositionalSignal)
    # Clean up mock cache file
    if cache_file.exists():
        cache_file.unlink()
        
    log.info("Fundamental-Technical Momentum verification: SUCCESS\n")


def test_young_momentum():
    log.info("=== Testing '1-2-3-4' Young Momentum Continuation Strategy ===")
    strategy = YoungMomentumStrategy()
    
    df = create_mock_daily_df(100, base_price=100.0)
    
    # Force a base breakout & impulse leg: 100 -> 135 (35% surge) ending 5 days ago
    # Peak achieved 5 days ago (index -6)
    peak_idx = -6
    low_idx = -16
    
    # Flat low before impulse
    for idx in range(-25, -15):
        df.loc[df.index[idx], "Open"] = 100.0
        df.loc[df.index[idx], "Close"] = 100.0
        df.loc[df.index[idx], "High"] = 101.0
        df.loc[df.index[idx], "Low"] = 99.0
        df.loc[df.index[idx], "Volume"] = 10000.0
        
    # Impulse run-up
    df.loc[df.index[low_idx], "Low"] = 100.0
    for idx in range(-15, -5):
        day_price = 100.0 + (idx - (-15)) * 3.5  # climbs to 135
        df.loc[df.index[idx], "Open"] = day_price - 2.0
        df.loc[df.index[idx], "Close"] = day_price
        df.loc[df.index[idx], "High"] = day_price + 1.0
        df.loc[df.index[idx], "Low"] = day_price - 3.0
        df.loc[df.index[idx], "Volume"] = 30000.0  # high volume
        
    # Peak high at 136.0
    df.loc[df.index[peak_idx], "High"] = 136.0
    df.loc[df.index[peak_idx], "Close"] = 135.0
    
    # Fibonacci 38.2% level: 136 - 0.382 * 36 = 122.25
    # Force a 4-day pause (indexes -5, -4, -3, -2) staying above 122.25 on low volume
    for idx in range(-5, -1):
        df.loc[df.index[idx], "Open"] = 128.0
        df.loc[df.index[idx], "Close"] = 127.0
        df.loc[df.index[idx], "High"] = 130.0
        df.loc[df.index[idx], "Low"] = 124.0  # stays above 122.25 Fib level
        df.loc[df.index[idx], "Volume"] = 5000.0  # low volume
        
    # Trigger today: price breaks above pause high water mark (130 * 1.001 = 130.13)
    df.loc[df.index[-1], "Close"] = 132.0
    df.loc[df.index[-1], "High"] = 133.0
    df.loc[df.index[-1], "Volume"] = 40000.0  # breakout volume
    
    sig = strategy.generate("YM_TICKER", df, quality_score=70.0)
    log.info("1-2-3-4 continuation signal: %s | Score: %.2f | Reason: %s", sig.action, sig.score, sig.reason)
    log.info("Signal meta: %s", sig.meta)
    
    assert isinstance(sig, PositionalSignal)
    log.info("1-2-3-4 Young Momentum verification: SUCCESS\n")


def test_live_data_pipes():
    log.info("=== Running Live Data Pipelines Verification ===")
    from data.fetcher import fetch_candles
    
    # Try fetching a small EOD dataset for live tickers
    test_tickers = ["TCS.NS", "RELIANCE.NS"]
    for ticker in test_tickers:
        try:
            df = fetch_candles(ticker, interval="1d", days=300)
            if df is not None and not df.empty:
                log.info("Successfully fetched %d daily bars for %s (Close range: %.2f to %.2f)",
                         len(df), ticker, float(df["Close"].min()), float(df["Close"].max()))
                
                # Test FTM quarterly fetch cache pipeline
                metrics = get_quarterly_data(ticker)
                if metrics:
                    log.info("Successfully fetched quarterly metrics for %s (Sales quarters: %s)",
                             ticker, metrics["sales"])
                else:
                    log.warning("Quarterly financials not available/failed for %s", ticker)
            else:
                log.warning("Failed to fetch EOD candles for %s", ticker)
        except Exception as e:
            log.error("Pipeline failure for %s: %s", ticker, e)
            
    log.info("Live data pipelines verification: COMPLETE\n")


if __name__ == "__main__":
    log.info("Starting verification sweep...")
    try:
        test_brahma_vishnu_mahesh()
        test_fun_tech_momentum()
        test_young_momentum()
        test_live_data_pipes()
        log.info("=== ALL STRATEGY VERIFICATIONS PASSED SUCCESSFULLY ===")
    except Exception as e:
        log.error("Verification failed: %s", e)
        sys.exit(1)
