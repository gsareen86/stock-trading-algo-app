# Intraday Trading

Status: baseline — not yet exercised through a change under `openspec/changes/`.

The always-on book: 15-min candles, same-day square-off, 10 strategies blended into one
composite score. Runs every cycle regardless of the `positional_enabled`/`LT_BOOK_ENABLED`
flags that gate the other two books.

## Requirements

### Requirement: Cycle gating — regime filter and no-trade windows
The system MUST block all new LONG entries when NIFTY 50's latest 15-min close is below
its EMA(20) (`USE_NIFTY_TREND_FILTER`, default on) — SHORT/SELL signals are never gated
by this filter. The system MUST also block all new entries (both directions) during
09:15–09:30 IST (opening volatility) and 11:30–13:00 IST (a configured "dead zone",
`NO_TRADE_WINDOWS`); existing positions continue to be exit-managed during these windows.

#### Scenario: Bearish NIFTY regime
- GIVEN NIFTY 50's 15-min close is below its EMA(20)
- WHEN a strategy fires a new LONG signal
- THEN the entry is blocked; a new SHORT signal on the same cycle is not blocked

### Requirement: Ten strategies blend into one technical score by configured weight
The system MUST run all 10 strategies in `strategies/` every cycle (ema_crossover,
rsi_mean_reversion, bollinger_breakout, momentum, vwap_momentum, orb, vwap_reversion,
supertrend, gap_play, pair_trading) and combine their scores via `config.STRATEGY_WEIGHTS`
into one technical score.

#### Scenario: Current strategy weights
- GIVEN the current `config.py` values
- WHEN the technical score is computed
- THEN `vwap_momentum` carries the single highest weight (0.20), followed by `orb`
  (0.16) and `supertrend` (0.12) — the remaining 7 strategies share the rest

### Requirement: Composite blends technical, fundamental, and sentiment
The system MUST compute the entry composite as
`technical×TECHNICAL_WEIGHT + fundamental×FUNDAMENTAL_WEIGHT + sentiment×SENTIMENT_WEIGHT`,
using the **intraday** fundamental scorer (`data/fundamentals.py`, not
`longterm/quality.py` — see `specs/fundamentals-quality-scoring`), and MUST block a BUY
outright when the fundamental score is below `MIN_FUNDAMENTAL_SCORE` (40) or sentiment is
below `SENTIMENT_BLOCK_THRESHOLD` (−0.4); SELL signals are never sentiment-gated.

#### Scenario: Current composite weights
- GIVEN the current `config.py` values (`TECHNICAL_WEIGHT=0.70`,
  `FUNDAMENTAL_WEIGHT=0.05`, `SENTIMENT_WEIGHT=0.25`)
- WHEN the composite is computed
- THEN fundamentals contribute only 5% — intentional, per an in-code comment stating
  fundamentals have little intraday predictive power on 15-min candles

### Requirement: Entry requires composite ≥ threshold, sized and exited by ATR
The system MUST require `composite >= MIN_COMPOSITE_SCORE` (60) to enter, MUST size the
position by `qty = (capital × RISK_PER_TRADE_PCT) / (1.5×ATR14)` capped at
`MAX_POSITION_SIZE_PCT` (20%) of capital and `MAX_OPEN_POSITIONS` (5) concurrent
positions, and MUST clip any computed ATR to `[0.3%, 8%]` of price before using it (an
ATR outside that band is treated as an implausible/stale candle).

#### Scenario: Implausible ATR
- GIVEN a ticker's computed ATR is 0.1% of price (implausibly tight — likely stale data)
- WHEN position sizing runs
- THEN the ATR is clipped to the 0.3% floor before the stop-distance/qty calculation,
  rather than producing an oversized position from a too-tight stop

### Requirement: ATR exit ladder — T1 partial, trail, final target, hard stop
The system MUST manage every open intraday position with: a hard stop at entry −1.5×ATR;
a T1 partial exit (sell 50% of quantity) at entry +1.0×ATR; after T1, a trailing stop at
high-water-mark −1.0×ATR on the remainder; and a final target at entry +3.0×ATR. For
SHORT positions, all levels are mirrored.

#### Scenario: T1 hit, then price reverses
- GIVEN a LONG position has hit T1 (50% closed, stop now trailing from HWM)
- WHEN price subsequently falls to HWM − 1.0×ATR
- THEN the remaining 50% is closed at the trailing stop, not held for the 3.0×ATR final
  target

### Requirement: Forced square-off regardless of P&L
The system MUST force-close every open intraday position at `SQUARE_OFF_TIME` (15:10 IST)
regardless of unrealized P&L or exit-ladder state.

#### Scenario: Position between T1 and final target at square-off time
- GIVEN a position has taken a T1 partial and is trailing, with unrealized profit beyond
  T1 but below the final target
- WHEN the clock reaches 15:10 IST
- THEN the remaining quantity is closed immediately, not left to the trailing stop or
  final target

### Requirement: No hygiene gate applies to intraday entries
Unlike the positional and long-term books, the system does not apply
`specs/market-hygiene-and-surveillance`'s ASM/GSM/liquidity/microcap checks to intraday
entries — `data/hygiene.py` is never imported under `engine/` or `strategies/`.

#### Scenario: A stock under GSM surveillance
- GIVEN a ticker is on the GSM surveillance list
- WHEN it is evaluated for an intraday entry
- THEN no surveillance-based exclusion applies (contrast with positional/long-term, where
  it would be excluded)

## Known gaps / gotchas

- No hygiene/surveillance gate (see Requirement above) and no live-broker path at all
  (not even a stub — see `specs/broker-execution-and-costs`) are both intraday-specific
  gaps relative to the other two books.
- Its own position ledger (`positions`/`trades` via `engine/portfolio.py`) is independent
  of the positional and long-term ledgers — three parallel, non-shared implementations of
  similar bookkeeping.
- No backtester exists for this book (`backtest/engine.py` covers positional/swing only).

## Source modules

`strategies/*` (10 files + `base.py`), `scheduler/runner.py`, `scoring/composite.py`,
`engine/atr_exits.py`, `engine/risk_manager.py`, `engine/portfolio.py`.
