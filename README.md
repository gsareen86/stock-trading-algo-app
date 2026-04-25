# Virtual Trading Bot — Indian Stock Market (NSE)

A self-contained, zero-paid-API paper-trading bot for the Indian stock market
(NIFTY 500 universe) with:

- **4 classical strategies** (EMA crossover, RSI mean reversion, Bollinger
  breakout, price-volume momentum) blended by a weighted-vote engine.
- **News + sentiment** from free Indian financial RSS feeds (MoneyControl,
  Economic Times, LiveMint, Business Standard) scored with VADER
  (FinBERT optional).
- **Fundamentals** via `yfinance` (P/E, ROE, debt/equity, growth, margins)
  scored 0–100 and used as a pre-filter.
- **Realistic paper broker** with Zerodha-style discount brokerage, STT,
  GST, SEBI, stamp duty and slippage.
- **Streamlit GUI** with a full control panel:
  - start / pause / stop, emergency square-off
  - mode toggle: **Manual approval** / **Auto** / **Dry run**
  - pending-approvals queue with approve/reject buttons
  - live parameter editing (risk %, SL/TP, max positions, min score)
  - live equity curve vs NIFTY 50, positions, trade log, news,
    fundamentals, analytics, drawdown.

This is **Phase 1**. Phase 2 (after a week of live data) will add the
ML meta-model, adaptive strategy weights and walk-forward tuning.

---

## 1. Install

Python 3.10+ recommended.

```bash
cd StockTradingAlgoApp
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## 2. Initialize the DB

The bot supports two backends, switched via the `DB_BACKEND` env var (loaded
from `.env`):

* **`sqlite`** (default) — local file at `db/trading_bot.db`. Zero setup,
  great for offline development.
* **`postgres`** — Supabase (or any libpq-compatible Postgres). Use this for
  the deployed bot so trade history survives across machines.

### 2a. SQLite (default)

```bash
python main.py --init
```

Creates `db/trading_bot.db` and seeds the bot control row.

### 2b. Supabase (Postgres)

1. Copy `.env.example` to `.env`, set `DB_BACKEND=postgres`, and paste your
   Supabase connection string into `SUPABASE_DB_URL`. URL-encode any special
   characters in the password (`@` → `%40`, `#` → `%23`, etc.).
2. Initialize the schema:
   ```bash
   python -m db.models
   ```
3. (Optional) Migrate existing SQLite data into Supabase:
   ```bash
   # Make sure DB_BACKEND=sqlite in your shell first OR set explicitly:
   python -m db.migrate_sqlite_to_supabase
   ```
   The migration is idempotent — re-running it won't duplicate rows.

#### One-shot bootstrap (Windows / PowerShell)

`bootstrap.ps1` does the whole sequence in one go: cleans up any partial
`.git/`, runs `git init` + initial commit, creates the GitHub repo with
`gh repo create`, installs `psycopg`, and runs the SQLite → Supabase
migration. From a fresh PowerShell window inside the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Re-running it is safe — every step short-circuits if it's already done.

## 3. Run

```bash
python main.py
```

This launches two things:

1. The **bot runner** in a background thread (polls every 15 min).
2. The **Streamlit dashboard** — it opens automatically on
   http://localhost:8501

Open the dashboard, go to the **Control Panel** tab, and hit **▶ START**.

### Default mode: Manual approval
Every trade the bot wants to place will appear in the **Pending Approvals**
queue on the Control Panel. Click ✅ Approve or ❌ Reject. Unapproved
signals auto-expire after 10 min. Switch to **Auto** once you're comfortable.

### Other options
```bash
python main.py --runner-only       # bot only, no dashboard
python main.py --dashboard-only    # dashboard only (useful during dev)
python main.py --reset             # wipe DB (destructive!)
```

---

## 4. Project layout

```
StockTradingAlgoApp/
├── config.py                 # ALL tunables live here
├── main.py                   # entry point
├── requirements.txt
├── data/
│   ├── universe.py           # NIFTY 500 loader (NSE CSV + fallback)
│   ├── fetcher.py            # yfinance + caching
│   ├── news_scraper.py       # RSS scraper
│   └── fundamentals.py       # yfinance fundamentals + scoring
├── nlp/
│   └── sentiment.py          # VADER / FinBERT sentiment
├── strategies/
│   ├── base.py
│   ├── moving_average.py     # EMA crossover
│   ├── rsi_mean_reversion.py
│   ├── bollinger_breakout.py
│   └── momentum.py
├── scoring/
│   └── composite.py          # blends tech + fund + sentiment
├── engine/
│   ├── paper_broker.py       # Indian cost model
│   ├── portfolio.py          # cash, positions, P&L, snapshots
│   └── risk_manager.py       # position sizing, limits
├── analytics/
│   └── metrics.py            # Sharpe, Sortino, drawdown, win rate
├── dashboard/
│   └── app.py                # Streamlit app
├── scheduler/
│   └── runner.py             # main trading loop
├── db/
│   └── models.py             # SQLite schema + connection helpers
├── cache/                    # pickled price data (auto)
└── logs/                     # bot.log
```

---

## 5. How a trade decision is made

For each ticker in a random 50-stock sample of NIFTY 500 (plus all currently
open positions) on every cycle:

1. **Fetch** 30 days of 15-min OHLCV candles (cached).
2. **Run all 4 strategies** → each produces an action + 0-100 score.
3. **Aggregate technical** → weighted BUY/SELL vote.
4. **Fetch fundamentals** (cached 24h) → 0-100 score.
   - BUYs blocked if `fundamental_score < 40`.
5. **Aggregate news sentiment** over the last 24h (-1 to +1).
   - BUYs blocked if sentiment < -0.4.
6. **Composite score** =
   `tech*0.50 + fundamental*0.25 + sentiment(0-100)*0.25`.
7. **Decide**:
   - `AUTO` mode: execute buys if composite ≥ 60.
   - `MANUAL` mode: queue for your approval.
   - `DRY_RUN`: log to `signals` table, no action.
8. **Risk-size** the position: `qty = capital * risk% / (price * SL%)`,
   capped at 20% of capital.
9. **Attach SL / TP** (5% / 10% by default — editable live from dashboard).
10. **Evaluate exits** every cycle: stop-loss, take-profit, or auto
    square-off at **15:15 IST** (intraday mode).

---

## 6. Trading costs modeled

All per leg, auto-computed in `engine/paper_broker.py`:

- Brokerage: `min(₹20, 0.03% of turnover)` (Zerodha-style)
- STT (sell only, intraday): 0.025%
- Exchange txn charges (NSE): 0.00322%
- SEBI charges: ₹10 / crore
- GST: 18% on brokerage + exchange + SEBI
- Stamp duty (buy only, intraday): 0.003%
- Slippage: 0.05% against you on every fill

Round-trip typically ~0.10-0.15% of turnover.

---

## 7. What's coming in Phase 2

Phase 2 turns on *after week 1* of live data, once we have enough trades to
learn from:

- **Adaptive strategy weights**: strategies that actually make money get
  more capital; underperformers shrink.
- **ML meta-model** (LightGBM) trained on every historical trade — predicts
  win probability from technical + fundamental + sentiment features; we
  gate trades on `P(win) > 0.60`.
- **Walk-forward hyperparameter optimization** using Optuna.
- **Rejection learning**: your rejected signals in manual mode are fed
  back as negative examples so the bot learns your preferences.

Feature flags in `config.py`:
```python
ENABLE_ML_META_MODEL = False
ENABLE_ADAPTIVE_WEIGHTS = False
ENABLE_FINBERT = False
```

---

## 8. Weekly report

After your first week of running, generate a weekly performance report:

```bash
python -c "from analytics.metrics import portfolio_summary, trade_stats, strategy_breakdown; import json; print(json.dumps({'summary': portfolio_summary(), 'trades': trade_stats(), 'by_strategy': strategy_breakdown().to_dict('records')}, indent=2, default=str))"
```

(A prettier HTML/PDF report generator will come with Phase 2.)

---

## 8a. Troubleshooting — Windows Smart App Control (SAC)

If Windows Security pops up saying **"Part of this app has been blocked"** and
you see errors like:

```
ImportError: DLL load failed while importing lib:
An Application Control policy has blocked this file.
  File "...\site-packages\pyarrow\__init__.py"
```

That's Windows Smart App Control refusing to load an unsigned native DLL (in
this case usually `pyarrow.lib` or `arrow_compute.dll`). The v1 dashboard is
built to **avoid the pyarrow code path entirely** — it:

- renders every table via pure-Python HTML instead of `st.dataframe()`, and
- uses a plain HTML `<meta http-equiv="refresh">` tag for auto-refresh
  instead of `streamlit-autorefresh` (which is a Streamlit *custom component*,
  and any custom component forces Streamlit to import pyarrow).

If you previously installed `streamlit-autorefresh`, you can safely uninstall
it — the dashboard no longer calls it:

```
pip uninstall -y streamlit-autorefresh
```

If you still hit a DLL error from some other package, you have three options
(no need to weaken system security):

1. **Update the offending package** to a recent signed release:
   ```
   pip install --upgrade pyarrow numpy pandas
   ```
2. **Allow one specific DLL** via Windows Security → App & browser control →
   Smart App Control settings → *Allow an app through*. Pick only the exact
   DLL (e.g. `...\site-packages\pyarrow\lib.pyd`). This does **not** disable
   SAC globally, it only exempts that one file.
3. **Reinstall the package from pip with binary wheels** (wheels from pypi are
   signed for most major packages):
   ```
   pip install --force-reinstall --only-binary=:all: pyarrow
   ```

The dashboard will keep working without pyarrow — every table and chart is
drawn using HTML + Plotly, both of which run entirely in the browser.

---

## 9. Notes & caveats

- **yfinance intraday limit**: ~60 days of 15-min bars. For longer
  backtests, switch `CANDLE_INTERVAL` to `"1d"` in `config.py`.
- **NSE website rate-limits**: `universe.load_universe()` downloads
  the official NIFTY 500 CSV once per day; falls back to a bundled
  starter list if that fails.
- **News matching**: uses whole-word ticker symbol match on article
  titles + summaries. Short symbols (<3 chars) are skipped to avoid
  false positives with English words.
- **Intraday square-off** fires at 15:15 IST. Toggle off by raising
  `SQUARE_OFF_TIME` to `"23:59"` in `config.py` for swing trading.
- **This is NOT financial advice**. Paper results ≠ live results —
  always test on paper for at least a month before putting real money
  on it.

---

## 10. Moving to live money (later)

This repo has a **clean interface boundary** at `engine/paper_broker.py`.
When you're ready, replace the `execute()` function with a real broker
adapter (e.g. Zerodha Kite / Upstox / Angel One). The rest of the codebase
needs zero changes.

Before flipping that switch, you should have:
1. At least 1 month of paper results with positive Sharpe (>1.0).
2. Max drawdown you're comfortable living with.
3. Backtested the strategy on 2+ years of daily data.
4. Set hard cash limits at the broker level.

Good luck. 📈
