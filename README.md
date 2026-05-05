# Virtual Trading Bot — Indian Stock Market (NSE)

A self-contained paper-trading bot for NIFTY 500 with two independent trading modules:

| Module | Timeframe | Hold period | Strategies |
|---|---|---|---|
| **Intraday** | 15-min candles | Same-day square-off by 15:10 IST | 9 strategies |
| **Positional** | Daily candles | 3–30 trading days | 7 strategies |

Both modules share the same dashboard, approval queue, cost model, and DB.

---

## Architecture overview

```
python main.py
    ├── Thread: scheduler/runner.py     — intraday bot (polls every 15 min)
    ├── Thread: positional/runner.py    — positional bot (daily scan + exit check)
    └── Subprocess: dashboard/app.py   — Streamlit UI on :8501
```

**One command starts everything.** No separate terminal for the scheduler.

---

## 1. Install

Python 3.10+ required.

```bash
git clone <repo-url>
cd stock-trading-algo-app

python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

---

## 2. Database setup

Two backends — switch via `DB_BACKEND` env var (auto-loaded from `.env`):

| Backend | When to use | Setup |
|---|---|---|
| `sqlite` (default) | Local dev / offline | Zero config |
| `postgres` | Production / persistent history | Supabase or any libpq Postgres |

### 2a. SQLite (default — just works)

```bash
python main.py --init
```

Creates `db/trading_bot.db` and seeds the bot control row. That's it.

### 2b. Supabase / Postgres

1. Copy `.env.example` → `.env` and fill in:
   ```
   DB_BACKEND=postgres
   SUPABASE_DB_URL=postgresql://postgres:<password>@<host>:5432/postgres
   ```
   URL-encode special characters in the password (`@` → `%40`, `#` → `%23`).

2. Initialize the schema:
   ```bash
   python -m db.models
   ```

3. (Optional) migrate existing SQLite data to Supabase:
   ```bash
   python -m db.migrate_sqlite_to_supabase
   ```

### Bootstrap (Windows / PowerShell one-shot)

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Does: git init, initial commit, GitHub repo creation, psycopg install, SQLite → Supabase migration.

---

## 3. Running the application

### Start everything (recommended)

```bash
python main.py
```

Opens the Streamlit dashboard at **http://localhost:8501** and starts both the
intraday and positional runners as background threads. Go to the **Control Panel**
tab and click **▶ START** to begin trading.

### Other modes

```bash
python main.py --init             # initialise DB then exit
python main.py --runner-only      # intraday + positional runners, no dashboard
python main.py --dashboard-only   # dashboard UI only (no trading)
python main.py --positional-only  # positional runner only
python main.py --reset            # wipe DB completely (destructive!)
```

> **Do not run `streamlit run dashboard/app.py` directly** for normal use — that
> starts only the UI with no bot runners attached. Use it only for dashboard
> development work.

### Trading modes

Set in the dashboard **Control Panel** or via `DEFAULT_MODE` in `config.py`:

| Mode | Behaviour |
|---|---|
| `manual` | Every signal queues for your approval (approve/reject per trade) |
| `auto` | Bot executes all signals above the composite score threshold automatically |
| `dry_run` | Signals logged to DB but no positions opened |

---

## 4. Project layout

```
stock-trading-algo-app/
├── config.py                   # ALL tunables — edit here, nowhere else
├── main.py                     # entry point; starts all three processes
├── requirements.txt
│
├── data/
│   ├── universe.py             # NIFTY 500 loader (NSE CSV + fallback list)
│   ├── fetcher.py              # yfinance + parquet disk cache
│   ├── news_scraper.py         # RSS scraper (MoneyControl, ET, LiveMint, BS)
│   └── fundamentals.py        # yfinance fundamentals + 0-100 scoring
│
├── strategies/                 # INTRADAY strategies (15-min candles)
│   ├── base.py                 # BaseStrategy + Signal dataclass
│   ├── moving_average.py       # EMA crossover (9/21)
│   ├── rsi_mean_reversion.py   # RSI 30/70 with divergence
│   ├── bollinger_breakout.py   # Bollinger band breakout + squeeze
│   ├── momentum.py             # price-volume momentum
│   ├── opening_range_breakout.py  # ORB — 09:15-09:30 IST range
│   ├── vwap_reversion.py       # VWAP ± dynamic band mean-reversion
│   ├── supertrend.py           # Supertrend(10, 3.0) direction filter
│   ├── gap_play.py             # Gap-and-go + gap-fade (first 30 min)
│   └── pair_trading.py        # Z-score stat-arb on 8 NIFTY pairs
│
├── positional/                 # POSITIONAL strategies (daily candles)
│   ├── strategies/
│   │   ├── base.py             # BasePositionalStrategy + PositionalSignal
│   │   ├── trend_following.py  # EMA ribbon (9/21/55) + ADX > 25
│   │   ├── breakout_retest.py  # 52-week high breakout + retest entry
│   │   ├── quality_momentum.py # Quality ≥ 70 + 63d return + RSI cross 50
│   │   ├── vcp_breakout.py     # Minervini VCP pattern
│   │   ├── sector_rotation.py  # Top-3 NSE sector indices rotation
│   │   ├── mean_reversion.py   # Oversold bounce on quality stocks
│   │   └── earnings_momentum.py # Post-earnings announcement drift (PEAD)
│   ├── screener.py             # Filters lt_universe by quality + FII holding
│   ├── scorer.py               # Composite scoring for positional signals
│   ├── risk.py                 # Daily ATR sizing, delivery costs, exit checks
│   └── runner.py               # Pre-market scan + EOD exit management
│
├── scoring/
│   └── composite.py            # Blends technical + fundamental + sentiment
│
├── engine/
│   ├── paper_broker.py         # Indian intraday cost model (Zerodha-style)
│   ├── portfolio.py            # Cash, positions, P&L, snapshots
│   ├── atr_exits.py            # ATR-based stops, T1 partial, trail stop
│   └── risk_manager.py         # Position sizing, capital limits
│
├── nlp/
│   └── sentiment.py            # VADER scorer + optional FinBERT
│
├── longterm/                   # Fundamental quality scoring infrastructure
│   ├── quality.py              # 5-bucket quality scorer (ROE/ROCE/D-E/growth/governance)
│   ├── universe.py             # FII/DII holding filter
│   ├── screener_scraper.py     # Screener.in scraper
│   └── tasks.py                # Orchestration tasks
│
├── analytics/
│   └── metrics.py              # Sharpe, Sortino, drawdown, win-rate, strategy P&L
│
├── scheduler/
│   └── runner.py               # Intraday main loop (15-min poll)
│
├── dashboard/
│   └── app.py                  # Streamlit multi-tab UI
│
├── db/
│   └── models.py               # Schema + SQLite/Postgres dual-backend layer
│
├── cache/                      # parquet price data (auto-managed)
├── logs/                       # bot.log
└── data/
    └── nifty500.csv            # NIFTY 500 constituent list
```

---

## 5. Intraday module

### How a trade decision is made

On each 15-minute cycle (for a random 50-stock sample of NIFTY 500 plus all
open positions):

1. **Fetch** 30 days of 15-min OHLCV candles from yfinance (parquet cache,
   10-min TTL). Stale or missing data is refetched automatically.

2. **NIFTY regime filter**: if `NIFTY 50 close < EMA(20)` on 15-min → market is
   bearish → block all new LONG entries for the cycle.

3. **No-trade windows**: new entries are blocked during 09:15–09:30 (opening
   volatility window) and 11:30–13:00 (low-edge dead zone).

4. **Run all 9 strategies** → each produces `Signal(action, score 0-100, reason)`.

5. **Composite score**:
   - Technical = weighted average of strategy scores (weights in `config.STRATEGY_WEIGHTS`)
   - Fundamental = yfinance P/E, ROE, D/E, margins → 0-100 (BUY blocked if < 40)
   - Sentiment = rolling 24h news sentiment (BUY blocked if < −0.4)
   - Composite = `tech×0.50 + fund×0.25 + sentiment×0.25`

6. **Entry decision**: composite ≥ 60 → BUY (LONG or SHORT based on signal direction).

7. **Position sizing** (ATR-based):
   ```
   Stop distance = 1.5 × ATR(14)
   Qty = (capital × 4%) / stop_distance
   Cap at 20% of capital per position
   ```

8. **ATR exit ladder** (all on the same position):
   - **T1** (partial): +1×ATR → sell 50% of quantity
   - **Trailing stop**: after T1, trail at `high-water-mark − 1×ATR`
   - **T2 / hard TP**: +3×ATR → close remainder
   - **Hard stop**: −1.5×ATR from entry

9. **Intraday square-off**: all open positions force-closed at **15:10 IST**
   regardless of P&L (configurable via `SQUARE_OFF_TIME`).

### Intraday strategies

| Strategy | Timeframe | Edge |
|---|---|---|
| EMA Crossover (9/21) | 15-min | Trend initiation |
| RSI Mean Reversion | 15-min | Oversold/overbought reversals |
| Bollinger Breakout | 15-min | Volatility expansion |
| Price-Volume Momentum | 15-min | Trend continuation |
| Opening Range Breakout (ORB) | 15-min | 09:15-09:30 range breakout |
| VWAP Reversion | 15-min | Mean reversion to VWAP ± band |
| Supertrend (10, 3.0) | 15-min | Trend direction filter |
| Gap-and-go / Gap-fade | 15-min | First-30-min gap edge |
| Pair Trading (8 pairs) | 15-min | Z-score stat-arb on correlated pairs |

Pair trading universe: HDFCBANK/ICICIBANK, RELIANCE/ONGC, TCS/INFY,
HCLTECH/WIPRO, MARUTI/TATAMOTORS, SBIN/AXISBANK, HINDUNILVR/ITC, TATASTEEL/JSWSTEEL.

---

## 6. Positional module

### How to enable

The positional module is **off by default**. Enable it via the dashboard
**Control Panel** → toggle `Positional Enabled`, or directly in the DB:

```sql
UPDATE bot_control SET positional_enabled = 1 WHERE id = 1;
```

### Capital allocation

```
Total capital: ₹1,00,000
  Intraday pool: ₹60,000   (existing bot uses this)
  Positional pool: ₹40,000 (new positional module)
    Max per position: 25% = ₹10,000
    Max open positions: 5
    Reserved buffer: 20% for adding to winners
```

### Scan schedule

| Time (IST) | Action |
|---|---|
| 08:45 (pre-market) | Universe scan — generate signals, queue entries |
| 15:20 (EOD) | Exit check — evaluate stops, T1, time stops, event guard |

### Universe

Tickers must pass all of:
- Present in `lt_universe` (`in_universe = 1`)
- `lt_quality.total_score ≥ 60 / 100`
- `lt_universe.fii_pct ≥ 5%` (institutional interest confirmed)
- Quality data scored within the last 30 days

Falls back to a hardcoded Tier-1 list of 24 NIFTY 50 large-caps when the DB is cold.

### Positional strategies

| Strategy | Weight | Setup | Typical hold |
|---|---|---|---|
| Quality Momentum | 25% | Quality ≥ 70 + 63d return > 15% + RSI cross 50 | 15–25 days |
| Trend Following | 20% | EMA ribbon 9>21>55 + ADX > 25, pullback entry | 12–18 days |
| Breakout Retest | 20% | 52W high breakout + retest (prior resistance → support) | 8–15 days |
| VCP Breakout | 15% | Minervini pattern: 2+ contracting corrections + volume dry-up | 10–20 days |
| Sector Rotation | 10% | Top-3 NSE sector indices by 20d return, catching-up stocks | 10–20 days |
| Mean Reversion | 5% | Quality stock 15–25% below 52W high + RSI < 35 + vol spike | 8–12 days |
| Earnings Momentum | 5% | Post-earnings drift: positive surprise gap + consolidation entry | 10–15 days |

### Positional risk model

```
Risk per trade:    2% of positional pool
Stop distance:     2.0 × ATR(14) daily
T1 partial exit:   +1.5×ATR (sell 50%)
Final target:      +4.0×ATR
Trailing stop:     after T1, trail at HWM − 1.5×ATR
Time stop:         exit flat position after 10 trading days
Max hold:          30 trading days (hard limit)
Event guard:       auto-exit 2 days before earnings / ex-dividend
Correlation cap:   reject new entry if r > 0.75 with any open position
```

### Positional cost model (delivery, differs from intraday)

- STT: 0.1% on **both** buy and sell legs (vs 0.025% sell-only for intraday)
- Stamp duty: 0.015% on buy (vs 0.003% intraday)
- All other charges same as intraday (brokerage, exchange, SEBI, GST, slippage)

---

## 7. Trading costs (intraday, per leg)

All auto-computed in `engine/paper_broker.py`:

| Charge | Rate |
|---|---|
| Brokerage | min(₹20, 0.03% of turnover) |
| STT (sell leg only) | 0.025% |
| Exchange txn (NSE) | 0.00322% |
| SEBI charges | ₹10/crore |
| GST | 18% on brokerage + exchange + SEBI |
| Stamp duty (buy leg) | 0.003% |
| Slippage | 0.05% against you on every fill |

Round-trip cost ≈ 0.10–0.15% of turnover.

---

## 8. Risk methodology

### ATR-based exits (intraday)

Replaces fixed percentage SL/TP with volatility-normalised levels. Wilder ATR-14
on 15-min candles. Clips implausible ATR values to `[0.3%, 8%]` of price.

```
Initial stop:   entry − 1.5×ATR
T1 target:      entry + 1.0×ATR  (50% qty out → locks in profit)
Final target:   entry + 3.0×ATR  (runner)
Trail stop:     after T1: HWM − 1.0×ATR
```

For SHORT positions all levels are mirrored.

### NIFTY trend filter

`USE_NIFTY_TREND_FILTER = True` (default): BUY signals are blocked when
`NIFTY 50 close < EMA(20)` on 15-min candles. SELL/SHORT signals are always
allowed. Prevents the bot from accumulating longs into a broad bear move.

### Sentiment gate

`SENTIMENT_BLOCK_THRESHOLD = -0.4`: BUY signals for a specific stock are
blocked when its rolling 24h news sentiment drops below −0.4. SELL signals are
not gated on sentiment (bad news accelerates selling, which we want to ride).

---

## 9. DB schema summary

Key tables:

| Table | Purpose |
|---|---|
| `positions` | All open/closed intraday + positional positions |
| `positional_positions` | Positional-specific metadata (quality score, conviction, days held) |
| `pending_approvals` | Approval queue (both intraday and positional) |
| `positional_signals` | Log of all positional signals for analytics |
| `signals` | Log of all intraday signals |
| `trades` | Every executed trade leg |
| `portfolio_snapshots` | Equity curve snapshots (every cycle) |
| `fundamentals` | Cached yfinance fundamentals per ticker |
| `lt_universe` | NIFTY 500 universe with FII/DII/promoter holding data |
| `lt_quality` | 5-bucket quality scores (profitability, cash, solvency, growth, governance) |
| `news` | Scraped news articles with sentiment scores |
| `bot_control` | Single control row: status, mode, positional_enabled |
| `cycle_log` | Per-cycle run log for cross-process visibility |

---

## 10. Dashboard tabs

| Tab | Contents |
|---|---|
| Control Panel | Start/stop, mode toggle, positional enable, live parameter edit, pending approvals |
| Portfolio | Equity curve vs NIFTY 50, open positions, unrealised P&L |
| Trades | Full trade history with cost breakdown |
| Signals | All generated signals (intraday + positional) with scores |
| Analytics | Sharpe, Sortino, max drawdown, win rate, strategy P&L breakdown |
| News | Latest scraped articles with per-ticker sentiment |
| Fundamentals | NIFTY 500 fundamental scores |
| Long-Term Research | lt_quality scores, FII/DII holding data |

---

## 11. Configuration

All tunables live in `config.py`. Key parameters:

```python
# Capital
INITIAL_CAPITAL = 100_000.0          # ₹1 Lakh

# Intraday risk
RISK_PER_TRADE_PCT = 0.04            # 4% per trade
MAX_OPEN_POSITIONS = 5
MIN_COMPOSITE_SCORE = 60

# Intraday ATR exits
ATR_STOP_MULT = 1.5
ATR_T1_MULT = 1.0
ATR_TP_MULT = 3.0
TRAIL_ATR_MULT = 1.0

# Market hours (IST)
MARKET_OPEN = "09:15"
SQUARE_OFF_TIME = "15:10"
NO_TRADE_BEFORE = "09:30"
NO_TRADE_AFTER = "15:00"
NO_TRADE_WINDOWS = [("11:30", "13:00")]   # dead zone — no new entries

# Positional risk
POSITIONAL_CAPITAL_PCT = 0.40        # 40% of INITIAL_CAPITAL
POSITIONAL_RISK_PCT = 0.02           # 2% per trade
POSITIONAL_MAX_POSITIONS = 5
POSITIONAL_MIN_COMPOSITE_SCORE = 65
POSITIONAL_ATR_STOP_MULT = 2.0
POSITIONAL_TIME_STOP_DAYS = 10

# Scoring weights (intraday)
TECHNICAL_WEIGHT = 0.50
FUNDAMENTAL_WEIGHT = 0.25
SENTIMENT_WEIGHT = 0.25

# Intraday strategy weights (must sum to 1.0)
STRATEGY_WEIGHTS = {
    "ema_crossover": 0.10,  "rsi_mean_reversion": 0.10,
    "bollinger_breakout": 0.10,  "momentum": 0.10,
    "orb": 0.18,  "vwap_reversion": 0.13,
    "supertrend": 0.12,  "gap_play": 0.10,  "pair_trading": 0.07,
}
```

---

## 12. Weekly performance report

```bash
python -c "
from analytics.metrics import portfolio_summary, trade_stats, strategy_breakdown
import json
print(json.dumps({
    'summary': portfolio_summary(),
    'trades': trade_stats(),
    'by_strategy': strategy_breakdown().to_dict('records'),
}, indent=2, default=str))
"
```

---

## 13. Troubleshooting

### Positional bot is not trading

Check that `positional_enabled = 1` in `bot_control`. Then verify:
- `lt_universe` has rows with `in_universe = 1` (run the Long-Term Research tab to populate)
- `lt_quality` has rows with `total_score ≥ 60` (run quality scorer from dashboard)
- The scan time (08:45 IST) has passed and the market is open

### Intraday bot shows no signals

Common causes:
- NIFTY trend filter is blocking all longs (bearish day). This is intentional. Shorts should still fire.
- All sampled tickers have composite score < 60.
- The bot is `STOPPED` — click ▶ START on the Control Panel.

### yfinance rate limit / empty data

yfinance imposes soft rate limits. The cache (parquet, `cache/` directory) prevents
most repeat hits. If a ticker consistently returns empty data it is likely delisted or
the `.NS` suffix is wrong. Check `to_yf_ticker()` in `data/universe.py`.

### Windows Smart App Control (pyarrow DLL blocked)

The dashboard avoids pyarrow by default (all tables rendered as HTML, not `st.dataframe`).
If you still see a DLL error:

```bash
pip install --upgrade --force-reinstall --only-binary=:all: pyarrow
```

Or allow the specific DLL via Windows Security → App & browser control → Smart App Control settings.

### DB locked (SQLite)

SQLite allows only one writer at a time. Both threads acquire short locks via
`get_conn()` context manager. If you see `database is locked` errors it usually
means a crashed process left an open connection. Restart `python main.py`.

---

## 14. Expanding to live money (later)

The live-money boundary is `engine/paper_broker.py → execute()`. Replace it with
a real broker adapter (Zerodha Kite / Upstox / Angel One). Everything else is
unchanged.

Checklist before going live:
1. Paper trade for at least 4 weeks (one full earnings cycle).
2. Sharpe ratio > 1.0, max drawdown within your risk tolerance.
3. Set a hard cash limit at the broker level independent of this bot.
4. Test the `--reset` → `--init` flow so you can recover from DB corruption.
5. For positional trades: verify the delivery STT costs match your broker's actual rates.

---

## 15. Phase 2 (future)

Feature flags in `config.py` (all `False` by default):

```python
ENABLE_ML_META_MODEL = False     # LightGBM win-probability filter (gate trades at P>0.60)
ENABLE_ADAPTIVE_WEIGHTS = False  # Adaptive strategy weights based on recent performance
ENABLE_FINBERT = False           # Heavier sentiment model (GPU recommended)
```

Phase 2 activation requires ≥ 200 closed trades as training data.

---

> **This is NOT financial advice.** Paper results ≠ live results. Always run
> on paper for at least a month before committing real capital.
