# Virtual Trading Bot — Indian Stock Market (NSE)

> **Living specification**: [`openspec/specs/`](openspec/specs/) is the maintained
> source of truth for current system behavior — read it before relying on this README's
> strategy-inventory tables, which have drifted before (see `openspec/project.md`). This
> README's install/run/troubleshooting sections are still accurate day-to-day.

A self-contained paper-trading bot for NIFTY 500 with three trading modules:

| Module | Timeframe | Hold period | Strategies |
|---|---|---|---|
| **Intraday** | 15-min candles | Same-day square-off by 15:10 IST | 10 strategies |
| **Positional** | Daily candles | 3–30 trading days | 4 strategies + Minervini VCP scanner |
| **Long-Term** | Daily candles | 1–3+ years | Thesis-driven exits only; off by default |

All three share the same dashboard, cost model, and DB (separate capital pools and
position ledgers per module — see `openspec/specs/`).

---

## Architecture overview

```
python main.py
    ├── Thread: scheduler/runner.py     — intraday bot (polls every 15 min)
    ├── Thread: positional/runner.py    — positional bot (daily scan + exit check)
    └── Unified FastAPI Server          — Unified backend and React frontend served on :8000
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

Opens the React dashboard at **http://localhost:8000** and starts both the
intraday and positional runners as background threads. Go to the **Control Panel**
tab and click **▶ START** to begin trading.

### Other modes

```bash
python main.py --init             # initialise DB then exit
python main.py --runner-only      # intraday + positional runners, no dashboard
python main.py --dashboard-only   # API server UI only (no trading)
python main.py --positional-only  # positional runner only
python main.py --reset            # wipe DB completely (destructive!)
```

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
├── strategies/                 # INTRADAY strategies (15-min candles) — 10 total
│   ├── base.py                 # BaseStrategy + Signal dataclass
│   ├── moving_average.py       # EMA crossover (9/21)
│   ├── rsi_mean_reversion.py   # RSI 30/70 with divergence
│   ├── bollinger_breakout.py   # Bollinger band breakout + squeeze
│   ├── momentum.py             # price-volume momentum
│   ├── vwap_momentum.py        # VWAP momentum pullback — highest strategy weight (0.20)
│   ├── opening_range_breakout.py  # ORB — 09:15-09:30 IST range
│   ├── vwap_reversion.py       # VWAP ± dynamic band mean-reversion
│   ├── supertrend.py           # Supertrend(10, 3.0) direction filter
│   ├── gap_play.py             # Gap-and-go + gap-fade (first 30 min)
│   └── pair_trading.py        # Z-score stat-arb on 8 NIFTY pairs
│
├── positional/                 # POSITIONAL strategies (daily candles) — 4 + scanner
│   ├── scanner.py              # Minervini Trend Template + VCP (weight 0.30)
│   ├── strategies/
│   │   ├── base.py                    # BasePositionalStrategy + PositionalSignal
│   │   ├── brahma_vishnu_mahesh.py    # regime + sector RS + multi-year breakout (0.25)
│   │   ├── fun_tech_momentum.py       # CANSLIM-style earnings accel + base breakout (0.25)
│   │   └── young_momentum.py          # "1-2-3-4" impulse-leg continuation (0.20)
│   ├── screener.py, universe.py, universe_sync.py   # universe build/sync
│   ├── scorer.py, pillars.py   # Timing/Durability scorecard — see openspec/specs/
│   ├── risk.py                 # Daily ATR sizing, delivery costs, exit checks
│   ├── broker.py               # PaperBroker (real); Sharekhan/Zerodha are stubs
│   ├── research.py, concalls.py, guidance.py  # LLM concall research + guidance ledger
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
├── frontend/                   # React frontend (Vite dev / production build)
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
   - Composite = `tech×TECHNICAL_WEIGHT + fund×FUNDAMENTAL_WEIGHT + sentiment×SENTIMENT_WEIGHT`
     — currently `0.70 / 0.05 / 0.25` in `config.py` (fundamentals carry little weight
     intraday by design; see `openspec/specs/configuration-and-feature-flags/` for why
     this is stated as a formula, not fixed numbers — they're config.py's current
     values, not a constant)

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

| Strategy | Timeframe | Edge | Weight |
|---|---|---|---|
| EMA Crossover (9/21) | 15-min | Trend initiation | 0.08 |
| RSI Mean Reversion | 15-min | Oversold/overbought reversals | 0.07 |
| Bollinger Breakout | 15-min | Volatility expansion | 0.07 |
| Price-Volume Momentum | 15-min | Trend continuation | 0.08 |
| **VWAP Momentum Pullback** | 15-min | Pullback-to-VWAP in trend direction — highest weight, best backtested Sharpe (~2.1) per `config.py` | **0.20** |
| Opening Range Breakout (ORB) | 15-min | 09:15-09:30 range breakout | 0.16 |
| VWAP Reversion | 15-min | Mean reversion to VWAP ± band | 0.10 |
| Supertrend (10, 3.0) | 15-min | Trend direction filter | 0.12 |
| Gap-and-go / Gap-fade | 15-min | First-30-min gap edge | 0.08 |
| Pair Trading (8 pairs) | 15-min | Z-score stat-arb on correlated pairs | 0.04 |

Weights are `config.STRATEGY_WEIGHTS` as of this writing — see
`openspec/specs/intraday-trading/` for the maintained current values.

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

The 4 files below plus the Minervini scanner (`positional/scanner.py`, not in
`strategies/`) are the real, current lineup — this replaces an earlier version of this
table that named 7 files no longer (or never) present in the repo.

| Strategy | Weight | Setup | Source |
|---|---|---|---|
| Minervini VCP | 30% | Trend-template filter + Volatility Contraction Pattern (2+ contracting corrections, volume dry-up) | `positional/scanner.py` |
| Brahma-Vishnu-Mahesh | 25% | 3-part top-down: NIFTY above rising 20-week SMA, top-3 sector by 3M/6M relative strength, 1.5–3y+ base breakout on >3x weekly volume | `strategies/brahma_vishnu_mahesh.py` |
| Fun-Tech Momentum | 25% | CANSLIM-style: quarterly EPS/Sales acceleration screen + tight consolidation base breakout on >100% volume expansion | `strategies/fun_tech_momentum.py` |
| Young Momentum ("1-2-3-4") | 20% | Base breakout → 20–50% impulse leg in 5–15 sessions → pause not breaching 38.2% Fib retracement → buy-stop above pause high | `strategies/young_momentum.py` |

Weights are `config.POSITIONAL_STRATEGY_WEIGHTS`. See
`openspec/specs/positional-swing-trading/` for the maintained current lineup and scoring
detail.

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

## 10. Dashboard pages

The React dashboard is organised into four groups (sidebar):

| Group | Page | Contents |
|---|---|---|
| Portfolio | Overview | All three books at a glance: value, P&L, equity curve, drawdown, open positions |
| Portfolio | Performance | Results after costs — per book and per strategy |
| Trading Books | Intraday | Open/closed intraday positions, ATR exit ladder, full signal history |
| Trading Books | Swing | EOD scan scorecards (Timing/Durability/horizon), holdings with partial & stops, universe upload/sync |
| Trading Books | Long-Term | Tranche holdings, candidates (durability ≥ 70), LT trade log, thesis-stop status |
| Research | Research & Guidance | LLM concall verdicts + theses, guidance ledger with MET/BEAT/MISSED and credibility scores |
| Research | News & Alerts | Scraped headlines, sentiment leaderboard, LLM news-impact alerts with severity filters |
| Research | Fundamentals | Financial scorecards for every tracked name, pinned watchlist, Screener deep-links |
| Engine | Control Center | Start/stop, mode, risk parameters, approval queue, every manual trigger, cycle log |
| Engine | Engine Room | Signal outcomes (forward returns), calibration report, backtest lab, NSE event calendar, ASM/GSM lists, per-ticker hygiene checker |
| Engine | LLM Usage | Live token consumption by provider/model/feature, recent call log |
| Engine | System Logs | Auto-refreshing runtime log tail with level filter |

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

The application utilizes pyarrow for Parquet caching.
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
