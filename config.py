"""
Central configuration for the virtual trading bot.
All tunables live here so they can be safely edited without hunting through modules.
"""
import os
from datetime import timezone, timedelta
from pathlib import Path

# Load .env BEFORE any os.environ.get() calls so that env vars set in .env
# are visible when module-level config values are computed at import time.
# This must stay at the top of this file.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass  # dotenv optional; env vars must be set another way

# Indian Standard Time offset (+05:30). Use datetime.now(IST) instead of
# datetime.now(timezone.utc) + timedelta(hours=5, minutes=30) everywhere.
IST = timezone(timedelta(hours=5, minutes=30))

# ----- Paths -----
BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / "db" / "trading_bot.db"
CACHE_DIR = BASE_DIR / "cache"
LOG_DIR = BASE_DIR / "logs"
CACHE_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ----- Capital -----
INITIAL_CAPITAL = 100_000.0       # INR (1 Lakh as per user choice)

# ----- Trading universe -----
# NIFTY 500 - fetched dynamically if possible, else this short starter list.
# User wants NIFTY 500. yfinance requires the ".NS" suffix for NSE stocks.
DEFAULT_WATCHLIST_FILE = BASE_DIR / "data" / "nifty500.csv"

# ----- Trading style -----
TRADING_STYLE = "intraday"        # 'intraday' | 'swing' | 'positional'
CANDLE_INTERVAL = "15m"           # 15-minute candles for intraday
LOOKBACK_DAYS = 30                # 30 days of 15-min history (yfinance cap ~60 days)
MARKET_OPEN = "09:15"             # IST
MARKET_CLOSE = "15:30"
SQUARE_OFF_TIME = "15:10"         # intraday auto square-off cutoff (was 15:15)
                                  # Moved 5 min earlier so the 15:15 poll tick
                                  # reliably catches it instead of slipping to
                                  # the 15:30 cycle (which is at/after close).
NEAR_CLOSE_START = "15:00"        # tighten polling cadence after this time
NEAR_CLOSE_POLL_INTERVAL_SEC = 300  # 5 min poll near close (vs 15 min default)
                                    # so square-off fires within ≤5 min of cutoff.

# ----- Risk -----
RISK_PER_TRADE_PCT = 0.04         # 4% capital risked per trade (moderate)
STOP_LOSS_PCT = 0.05              # 5% stop-loss (legacy fallback when ATR unusable)
TAKE_PROFIT_PCT = 0.10            # 10% target (1:2 RR; legacy fallback)
MAX_OPEN_POSITIONS = 5            # With 1L capital, 5 concurrent positions
MAX_POSITION_SIZE_PCT = 0.20      # max 20% of capital in any single stock
MIN_COMPOSITE_SCORE = 60          # 0-100; only trade above this
MIN_FUNDAMENTAL_SCORE = 40        # fundamental floor
MIN_CONFIDENCE_THRESHOLD = 0.60   # ML will use this in Phase 2
# BUY signals are blocked when rolling sentiment drops below this.
# Applies to LONGs only — SELL signals are not gated on sentiment.
SENTIMENT_BLOCK_THRESHOLD = -0.4
NO_TRADE_BEFORE = "09:30"         # skip first 15 min volatility
NO_TRADE_AFTER = "15:00"          # no new entries in last 30 min

# ----- ATR-based exits + partial T1 + trailing stop -----
# Replaces the fixed 5%/10% SL/TP with volatility-normalised exits, plus
# a "partial profit at 1×ATR + trail the remainder" mechanic. This is the
# single biggest win-rate / expectancy improvement for short-horizon
# Indian intraday on 15-min candles. See README "Risk methodology".
USE_ATR_EXITS = True              # master switch for ATR-driven exits
ATR_PERIOD = 14                   # standard Wilder period
ATR_STOP_MULT = 1.5               # initial stop = entry - 1.5*ATR
ATR_T1_MULT = 1.0                 # 1st profit target = entry + 1*ATR (50% qty out)
ATR_TP_MULT = 3.0                 # 2nd / final target = entry + 3*ATR (runner)
TRAIL_ATR_MULT = 1.0              # after T1, trail stop at hwm - 1*ATR
ATR_T1_PARTIAL_PCT = 0.5          # fraction of qty to exit at T1
# Bounds — a per-trade ATR that's <0.3% of price is implausible (likely
# stale / illiquid candle), and >8% triggers oversize stops; we clip to
# keep risk-of-ruin sensible.
ATR_MIN_PCT_OF_PRICE = 0.003
ATR_MAX_PCT_OF_PRICE = 0.08

# ----- Market-regime / trend filter -----
# Don't open longs when the broad market (NIFTY 50) is in a downtrend.
# Mechanism: latest 15-min close > EMA(20) of 15-min closes.
USE_NIFTY_TREND_FILTER = True
NIFTY_TREND_INTERVAL = "15m"
NIFTY_TREND_EMA_PERIOD = 20
NIFTY_TREND_LOOKBACK_DAYS = 5     # 5 trading days × 25 candles/day ≈ 125 bars
NIFTY_TREND_TICKER = "^NSEI"

# ----- Indian trading costs (Zerodha-style discount broker) -----
BROKERAGE_PER_ORDER = 20.0        # ₹20 flat per order (or 0.03% whichever lower)
BROKERAGE_PCT = 0.0003            # 0.03%
STT_DELIVERY = 0.001              # 0.1% on buy+sell for delivery
STT_INTRADAY_SELL = 0.00025       # 0.025% on sell leg only
EXCHANGE_TXN_CHARGE = 0.0000322   # NSE
SEBI_CHARGES = 0.000001           # ₹10 per crore
GST_RATE = 0.18                   # on brokerage + exchange + sebi
STAMP_DUTY_BUY = 0.00003          # 0.003% on buy leg (intraday)
SLIPPAGE_PCT = 0.0005             # 0.05% assumed slippage per trade

# ----- Scoring weights -----
# Intraday edge comes almost entirely from technicals + sentiment; fundamentals
# (P/E, book value, etc.) offer no intraday predictive power on 15-min candles.
# Weight distribution: technical 0.70, sentiment 0.25, fundamentals 0.05.
TECHNICAL_WEIGHT = 0.70
FUNDAMENTAL_WEIGHT = 0.05
SENTIMENT_WEIGHT = 0.25

# ----- Strategy weights (Phase 2 will make these adaptive) -----
# Weights sum to 1.0. vwap_momentum gets the highest single weight — it has
# the best Sharpe (~2.1) and win rate (48%) of the five evaluated strategies.
# It fires in trend regime; vwap_reversion covers rangebound days as complement.
STRATEGY_WEIGHTS = {
    # Legacy (long-biased) — retained for signal diversity but down-weighted
    "ema_crossover":       0.08,
    "rsi_mean_reversion":  0.07,
    "bollinger_breakout":  0.07,
    "momentum":            0.08,
    # Direction-balanced core
    "vwap_momentum":       0.20,   # winner: Sharpe ~2.1, 48% win rate
    "orb":                 0.16,   # strong first-hour edge
    "vwap_reversion":      0.10,   # rangebound complement to vwap_momentum
    "supertrend":          0.12,   # trend confirmation / confluence
    "gap_play":            0.08,   # first-30-min gap edge
    "pair_trading":        0.04,   # rangebound stat-arb (selective)
}

# ----- Opening Range Breakout (ORB) -----
# First N minutes after 09:15 IST define the day's range. After the window
# closes a 15-min close beyond either side fires a directional signal.
ORB_WINDOW_MIN = 15                # 09:15-09:30 IST
ORB_MIN_BREAKOUT_PCT = 0.10        # min % beyond OR-high/low to count as breakout

# ----- VWAP mean-reversion -----
VWAP_BAND_K = 1.8                  # multiplier on recent intraday return-stdev
VWAP_VOL_LOOKBACK = 8              # bars of returns used to size the band

# ----- VWAP Momentum Pullback -----
# Fires when price returns to VWAP in the direction of the local trend.
# EMA period determines the intraday trend (20 bars × 15 min = 5 hours context).
VWAP_MOMENTUM_EMA_PERIOD = 20      # EMA period on today's closes for trend detection
VWAP_MOMENTUM_BAND_PCT = 0.0025    # max distance from VWAP (0.25%) to qualify as "at VWAP"
VWAP_MOMENTUM_VOL_MULT = 1.2       # entry bar volume >= 1.2× rolling avg (momentum check)
VWAP_MOMENTUM_VOL_LOOKBACK = 10    # bars used to compute rolling volume average
VWAP_MOMENTUM_RSI_PERIOD = 14      # RSI period for momentum exhaustion filter
VWAP_MOMENTUM_RSI_OB = 70          # RSI above this → skip long (overbought)
VWAP_MOMENTUM_RSI_OS = 30          # RSI below this → skip short (oversold)

# ----- Supertrend -----
SUPERTREND_PERIOD = 10
SUPERTREND_MULT = 3.0

# ----- Gap-and-go / Gap-fade -----
GAP_GO_PCT = 1.5                   # |gap %| threshold for continuation
GAP_FADE_PCT = 2.0                 # |gap %| threshold for fade (needs weak vol)
GAP_GO_VOL_MULT = 1.5              # first-bar vol vs prior session avg
GAP_ENTRY_WINDOW_MIN = 30          # only fire within first 30 min after open

# ----- Pair trading (statistical arbitrage) -----
# Pairs are (A, B). Each pair generates two evaluations per cycle (one per
# leg) and the composite scorer ends up with one BUY + one SELL — perfect
# for direction-balanced exposure on rangebound days.
PAIR_TRADING_PAIRS: list[tuple[str, str]] = [
    ("HDFCBANK",  "ICICIBANK"),    # private banks
    ("RELIANCE",  "ONGC"),         # energy / oil
    ("TCS",       "INFY"),         # IT large-caps
    ("HCLTECH",   "WIPRO"),        # IT mid-caps
    ("MARUTI",    "TATAMOTORS"),   # autos
    ("SBIN",      "AXISBANK"),     # banks (PSU vs private)
    ("HINDUNILVR", "ITC"),         # FMCG
    ("TATASTEEL", "JSWSTEEL"),     # metals
]
PAIR_Z_ENTRY = 2.0                 # |z| ≥ 2.0 → enter
PAIR_Z_LOOKBACK = 60               # 15-min bars; ~2 trading days

# ----- Time-of-day no-trade windows -----
# Disable NEW entries during the listed (start, end) IST windows. The 11:30-
# 13:00 "dead zone" produces a disproportionate share of false breakouts in
# Indian markets. Existing positions still get exit-managed normally.
NO_TRADE_WINDOWS: list[tuple[str, str]] = [
    ("11:30", "13:00"),
]

# ----- Bot control defaults -----
DEFAULT_MODE = "auto"             # 'manual' | 'auto' | 'dry_run'
APPROVAL_TIMEOUT_MIN = 10         # auto-reject pending approvals after N minutes
SIGNAL_POLL_INTERVAL_SEC = 900    # 15 min - matches candle interval

# How many tickers each cycle samples from the full universe. Bigger means
# more chance of finding a high-conviction signal but linearly higher
# cycle latency (yfinance fetch dominates). With FETCH_BATCH_WORKERS=8 in
# data/fetcher.py, expect roughly:
#   50  tickers ≈ 10-15 s per cycle
#   100 tickers ≈ 20-30 s
#   500 tickers ≈ 100-180 s   (use a longer poll interval if you do this)
CYCLE_SAMPLE_SIZE = 50

# ----- News sources (free RSS) -----
NEWS_SOURCES = {
    "moneycontrol_markets": "https://www.moneycontrol.com/rss/marketsnews.xml",
    "moneycontrol_business": "https://www.moneycontrol.com/rss/business.xml",
    "moneycontrol_results": "https://www.moneycontrol.com/rss/results.xml",
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "livemint_markets": "https://www.livemint.com/rss/markets",
    "business_standard": "https://www.business-standard.com/rss/markets-106.rss",
}

NEWS_REFRESH_MIN = 30             # rescrape news every 30 min
SENTIMENT_ENGINE = "finbert"      # 'vader' or 'finbert' — finbert is finance-tuned, more accurate

# ----- Benchmark -----
BENCHMARK_TICKER = "^NSEI"        # NIFTY 50

# ----- Logging -----
LOG_LEVEL = "INFO"

# ─── Positional / Swing Trading Module (Minervini VCP Strategy) ──────────────
# Operates as a separate EOD (End-of-Day) scanner with its own capital pool.
# Capital is INDEPENDENT of the intraday pool — 1 Lakh dedicated to positional.

POSITIONAL_ENABLED = False            # toggled via dashboard control panel

# Capital — separate 1 Lakh pool (does not mix with intraday INITIAL_CAPITAL)
POSITIONAL_CAPITAL = 100_000.0        # INR — 1 Lakh
POSITIONAL_MAX_POSITIONS = 5          # concentrated portfolio: 1L ÷ 5 = 20K/trade
POSITIONAL_MAX_POSITION_PCT = 0.20    # max 20% of positional capital per position

# Hard stop & trailing stop (Minervini method)
POSITIONAL_HARD_STOP_PCT = 0.08       # 8% below entry — configurable
POSITIONAL_EMA_TRAIL_PERIOD = 21      # 21-day EMA for trailing stop
POSITIONAL_EMA_TRAIL_CONSECUTIVE = 2  # closes below 21 EMA before SELL alert

# Time stop
POSITIONAL_TIME_STOP_DAYS = 15        # exit if <2% move after N trading days
POSITIONAL_TIME_STOP_MIN_MOVE_PCT = 2.0

# Re-entry window
POSITIONAL_REENTRY_WINDOW_DAYS = 14   # check for re-entry within N days of exit
POSITIONAL_REENTRY_VOL_MULT = 1.3     # re-entry: close above 21 EMA on high volume

# Minervini Trend Template filters
POSITIONAL_52W_PROXIMITY_PCT = 15.0   # price within 15% of 52-week high
POSITIONAL_MIN_TREND_SCORE = 60       # minimum VCP/trend composite to qualify

# VCP (Volatility Contraction Pattern) detection
POSITIONAL_VCP_ATR_PERIOD = 10        # 10-day ATR for weekly ATR% comparison
POSITIONAL_VCP_CONTRACTION_WEEKS = 3  # ATR% must shrink over N consecutive weeks
POSITIONAL_VCP_CONTRACTION_RATIO = 0.85  # each week's ATR% < prev * this ratio
POSITIONAL_VCP_VOLUME_DRY_PCT = 0.80  # down-day vol < 80% of 20-day avg vol

# Market Regime Engine (Minervini macro filter)
POSITIONAL_NIFTY_ROC_MONTHS = 18      # 18-month ROC for Nifty 50
POSITIONAL_SMALLCAP_ROC_MONTHS = 20   # 20-month ROC for Nifty Smallcap 250
POSITIONAL_NIFTY_ROC_DEFENSIVE = 45.0    # ROC > 45 → DEFENSIVE
POSITIONAL_SMALLCAP_ROC_DEFENSIVE = 80.0 # ROC > 80 → DEFENSIVE
POSITIONAL_DEFENSIVE_SIZE_MULT = 0.35    # size × 0.35 when DEFENSIVE
POSITIONAL_NIFTY_TICKER = "^NSEI"
POSITIONAL_SMALLCAP_TICKER = "^CNXSC"
POSITIONAL_GOLD_TICKER = "GOLDBEES.NS"

# Fundamental universe filters (applied to Screener.in CSV)
POSITIONAL_FUND_MIN_ROCE = 15.0       # ROCE > 15%
POSITIONAL_FUND_MIN_ROE = 15.0        # ROE > 15%
POSITIONAL_FUND_MIN_SALES_GROWTH = 15.0  # Sales Growth YoY > 15%
POSITIONAL_FUND_MAX_DE = 1.0          # Debt/Equity < 1

# EOD schedule
POSITIONAL_SCAN_TIME = "16:00"        # 4:00 PM IST — after market close
POSITIONAL_ALERT_TIME = "16:30"       # 4:30 PM IST — send Telegram summary
POSITIONAL_EXIT_TIME  = "15:20"       # 15:20 IST — intraday guard check
POSITIONAL_APPROVAL_TIMEOUT_MIN = 120

# Delivery costs (differ from intraday)
STT_DELIVERY_BUY_PCT   = 0.001        # 0.1% on buy
STT_DELIVERY_SELL_PCT  = 0.001        # 0.1% on sell
STAMP_DUTY_DELIVERY_PCT = 0.00015     # 0.015% on buy

# Broker selection for positional trades
POSITIONAL_BROKER = os.environ.get("POSITIONAL_BROKER", "paper").lower()
# "paper" — paper trading (default); "sharekhan" or "zerodha" when API keys added

# Telegram notifications
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# Legacy aliases kept for backward compat with old positional strategies code
POSITIONAL_CAPITAL_PCT = 0.40
POSITIONAL_MIN_COMPOSITE_SCORE = 65
POSITIONAL_MIN_QUALITY_SCORE = 60
POSITIONAL_MIN_FII_PCT = 5.0
POSITIONAL_CANDLE_INTERVAL = "1d"
POSITIONAL_LOOKBACK_DAYS = 365
POSITIONAL_RISK_PCT = 0.02
POSITIONAL_ATR_PERIOD = 14
POSITIONAL_ATR_STOP_MULT = 2.0
POSITIONAL_ATR_T1_MULT = 1.5
POSITIONAL_ATR_TP_MULT = 4.0
POSITIONAL_TRAIL_ATR_MULT = 1.5
POSITIONAL_T1_PARTIAL_PCT = 0.50
POSITIONAL_MIN_HOLD_DAYS = 3
POSITIONAL_MAX_HOLD_DAYS = 30
POSITIONAL_EVENT_GUARD_DAYS = 2

POSITIONAL_STRATEGY_WEIGHTS = {
    "trend_following":   0.20,
    "breakout_retest":   0.20,
    "quality_momentum":  0.25,
    "vcp_breakout":      0.15,
    "sector_rotation":   0.10,
    "mean_reversion":    0.05,
    "earnings_momentum": 0.05,
}

# Delivery STT / stamp legacy names
POS_EMA_FAST = 9
POS_EMA_MID  = 21
POS_EMA_SLOW = 55
POS_ADX_PERIOD = 14
POS_ADX_THRESHOLD = 25
POS_BREAKOUT_52W_PROXIMITY_PCT = 2.0
POS_BREAKOUT_MAX_PULLBACK_PCT  = 5.0
POS_BREAKOUT_VOL_MULT = 1.5
POS_QUALITY_MIN_SCORE = 70
POS_MOMENTUM_63D_MIN_PCT = 15
POS_RSI_PERIOD = 14
POS_RSI_ENTRY_LEVEL = 50
POS_VCP_BASE_MIN_DAYS = 20
POS_VCP_BASE_MAX_DAYS = 120
POS_VCP_CONTRACTION_RATIO = 0.85
POS_VCP_VOLUME_DRY_RATIO = 0.80
POS_VCP_BREAKOUT_VOL_MULT = 1.5
SECTOR_INDEX_TICKERS = {
    "IT": "^CNXIT", "Bank": "^NSEBANK", "FMCG": "^CNXFMCG",
    "Pharma": "^CNXPHARMA", "Auto": "^CNXAUTO", "Metal": "^CNXMETAL",
    "Energy": "^CNXENERGY", "Realty": "^CNXREALTY",
}
POS_SECTOR_LOOKBACK = 20
POS_SECTOR_TOP_N = 3
POS_MR_BELOW_52W_MIN_PCT = 15
POS_MR_BELOW_52W_MAX_PCT = 25
POS_MR_RSI_THRESHOLD = 35
POS_MR_VOL_SPIKE_MULT = 2.0
POS_MR_MIN_QUALITY_SCORE = 65
POS_EARNINGS_WINDOW_DAYS = 3
POS_EARNINGS_MAX_GAP_PCT = 8.0

# ----- Feature flags (Phase 2) -----
ENABLE_ML_META_MODEL = False      # Phase 2
ENABLE_ADAPTIVE_WEIGHTS = False   # Phase 2
ENABLE_FINBERT = True             # ProsusAI/finbert via transformers — finance-tuned

# ----- LLM integration -----
# Master switches — set to False to disable individual features without removing code.
LLM_ENABLE_SENTIMENT    = True   # Replace/augment FinBERT with LLM sentiment
LLM_ENABLE_VETO         = True   # Pre-trade quality gate (PROCEED / REDUCE / SKIP)
LLM_ENABLE_REGIME       = True   # Narrative market regime (BULLISH/BEARISH/VOLATILE/AVOID)
LLM_ENABLE_EVENTS       = True   # Earnings / corporate-action extraction from news
LLM_ENABLE_EOD_REVIEW   = True   # End-of-day trade analysis + parameter recommendations
LLM_ENABLE_META_WEIGHTS = True   # Hourly adaptive strategy weight rebalancing

# Provider selection — set LLM_PROVIDER=anthropic or LLM_PROVIDER=openrouter in .env
# "openrouter" is the default (free models available, no Anthropic account needed).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openrouter").lower()

if LLM_PROVIDER == "anthropic":
    # Requires ANTHROPIC_API_KEY. Haiku for fast per-cycle calls; Sonnet for EOD review.
    LLM_DEFAULT_MODEL    = "claude-haiku-4-5"
    LLM_SENTIMENT_MODEL  = "claude-haiku-4-5"
    LLM_VETO_MODEL       = "claude-haiku-4-5"
    LLM_REGIME_MODEL     = "claude-haiku-4-5"
    LLM_EVENTS_MODEL     = "claude-haiku-4-5"
    LLM_EOD_MODEL        = "claude-sonnet-4-6"   # better pattern recognition for daily review
    LLM_META_MODEL       = "claude-haiku-4-5"
else:
    # OpenRouter — requires OPENROUTER_API_KEY.
    # Override any individual model via OPENROUTER_MODEL env var.
    # Find model IDs at https://openrouter.ai/models (filter by :free for free tier).
    _OR_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-3-27b-it:free")
    LLM_DEFAULT_MODEL    = _OR_MODEL
    LLM_SENTIMENT_MODEL  = _OR_MODEL
    LLM_VETO_MODEL       = _OR_MODEL
    LLM_REGIME_MODEL     = _OR_MODEL
    LLM_EVENTS_MODEL     = _OR_MODEL
    LLM_EOD_MODEL        = _OR_MODEL
    LLM_META_MODEL       = _OR_MODEL

LLM_MAX_RETRIES       = 2    # retries on 429 / 5xx
LLM_REQUEST_TIMEOUT_S = 30   # per-request timeout in seconds

# Emit a clear startup line so you can always verify which model/provider is active.
import logging as _logging
_logging.getLogger(__name__).debug(
    "LLM config: provider=%s model=%s", LLM_PROVIDER, LLM_DEFAULT_MODEL
)
print(f"[config] LLM provider={LLM_PROVIDER}  model={LLM_DEFAULT_MODEL}", flush=True)
