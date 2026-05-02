"""
Central configuration for the virtual trading bot.
All tunables live here so they can be safely edited without hunting through modules.
"""
from datetime import timezone, timedelta
from pathlib import Path

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
TECHNICAL_WEIGHT = 0.50
FUNDAMENTAL_WEIGHT = 0.25
SENTIMENT_WEIGHT = 0.25

# ----- Strategy weights (Phase 2 will make these adaptive) -----
# Weights sum to 1.0. The four direction-balanced additions (orb, vwap_reversion,
# supertrend, gap_play, pair_trading) are weighted higher than the legacy
# long-biased trio because they're what produces SHORT signals on red days.
STRATEGY_WEIGHTS = {
    # Legacy (long-biased)
    "ema_crossover":       0.10,
    "rsi_mean_reversion":  0.10,
    "bollinger_breakout":  0.10,
    "momentum":            0.10,
    # Direction-agnostic additions
    "orb":                 0.18,   # highest impact — biggest expected lift
    "vwap_reversion":      0.13,   # rangebound-day workhorse
    "supertrend":          0.12,   # high-conviction trend confluence
    "gap_play":            0.10,   # first-30-min edge
    "pair_trading":        0.07,   # rangebound stat-arb (selective)
}

# ----- Opening Range Breakout (ORB) -----
# First N minutes after 09:15 IST define the day's range. After the window
# closes a 15-min close beyond either side fires a directional signal.
ORB_WINDOW_MIN = 15                # 09:15-09:30 IST
ORB_MIN_BREAKOUT_PCT = 0.10        # min % beyond OR-high/low to count as breakout

# ----- VWAP mean-reversion -----
VWAP_BAND_K = 1.8                  # multiplier on recent intraday return-stdev
VWAP_VOL_LOOKBACK = 8              # bars of returns used to size the band

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
DEFAULT_MODE = "manual"           # 'manual' | 'auto' | 'dry_run'  (user chose manual)
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
SENTIMENT_ENGINE = "vader"        # 'vader' or 'finbert'

# ----- Benchmark -----
BENCHMARK_TICKER = "^NSEI"        # NIFTY 50

# ----- Logging -----
LOG_LEVEL = "INFO"

# ----- Feature flags (Phase 2) -----
ENABLE_ML_META_MODEL = False      # Phase 2
ENABLE_ADAPTIVE_WEIGHTS = False   # Phase 2
ENABLE_FINBERT = False            # heavier model - keep off by default
