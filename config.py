"""
Central configuration for the virtual trading bot.
All tunables live here so they can be safely edited without hunting through modules.
"""
from pathlib import Path

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
STOP_LOSS_PCT = 0.05              # 5% stop-loss
TAKE_PROFIT_PCT = 0.10            # 10% target (1:2 RR)
MAX_OPEN_POSITIONS = 5            # With 1L capital, 5 concurrent positions
MAX_POSITION_SIZE_PCT = 0.20      # max 20% of capital in any single stock
MIN_COMPOSITE_SCORE = 60          # 0-100; only trade above this
MIN_FUNDAMENTAL_SCORE = 40        # fundamental floor
MIN_CONFIDENCE_THRESHOLD = 0.60   # ML will use this in Phase 2
NO_TRADE_BEFORE = "09:30"         # skip first 15 min volatility
NO_TRADE_AFTER = "15:00"          # no new entries in last 30 min

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
STRATEGY_WEIGHTS = {
    "ema_crossover": 0.25,
    "rsi_mean_reversion": 0.25,
    "bollinger_breakout": 0.25,
    "momentum": 0.25,
}

# ----- Bot control defaults -----
DEFAULT_MODE = "manual"           # 'manual' | 'auto' | 'dry_run'  (user chose manual)
APPROVAL_TIMEOUT_MIN = 10         # auto-reject pending approvals after N minutes
SIGNAL_POLL_INTERVAL_SEC = 900    # 15 min - matches candle interval

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
