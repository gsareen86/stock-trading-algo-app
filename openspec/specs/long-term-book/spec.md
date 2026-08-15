# Long-Term Book

Status: baseline — not yet exercised through a change under `openspec/changes/`.

The 1–3+ year, thesis-driven book. Off by default (`LT_BOOK_ENABLED`, env-backed,
`False`). No time stop — only thesis stops. Reviewed quarterly plus event-driven.

## Requirements

### Requirement: Entry requires high durability, not timing
The system MUST admit a candidate to the Long-Term book only when Durability
(`specs/conviction-engine-scoring-routing`) is at or above `LT_DURABILITY_GATE` (70.0) —
note this is a stricter bar than the 60.0 `POSITIONAL_DURABILITY_STRONG` threshold used to
produce the `LONG_TERM` watch label; a `LONG_TERM`-labeled candidate is not automatically
admitted to this book. Timing is not required for entry.

#### Scenario: LONG_TERM-labeled candidate below the book's own gate
- GIVEN a ticker classifies as `LONG_TERM` horizon (durability ≥ 60, the routing
  threshold)
- WHEN it is considered for actual entry into the Long-Term book
- THEN entry still requires durability ≥ 70 (`LT_DURABILITY_GATE`) — being labeled
  `LONG_TERM` is necessary but not sufficient

### Requirement: Staggered tranche accumulation
The system MUST build a position in up to 3 tranches (`LT_TRANCHE_FRACTIONS`, roughly
equal thirds), with at least `LT_MIN_TRANCHE_GAP_DAYS` (10) between tranches, triggered by
classification into the book, a higher-low/RS turn or 10–15% drawdown with thesis intact,
or confirmed guidance delivery at the next quarterly results.

#### Scenario: Second tranche trigger arrives before the minimum gap has elapsed
- GIVEN tranche 1 was bought 4 days ago, and today a 12% drawdown with thesis intact
  would normally trigger tranche 2
- WHEN the tranche logic evaluates the position
- THEN tranche 2 does not fire yet — it waits until `LT_MIN_TRANCHE_GAP_DAYS` (10) have
  elapsed since tranche 1, even though the price trigger condition is already met

### Requirement: Swing-to-long-term conversion channel
The system MUST convert a swing/positional position into this book (rather than treating
it as a fresh entry) when `LT_CONVERT_FROM_SWING` is true and that position reaches +2R
unrealized with durability ≥ `LT_DURABILITY_GATE`.

#### Scenario: Swing position reaches +2R with high durability
- GIVEN an open positional/swing position has taken its +2R partial de-risk
  (`specs/positional-swing-trading`) and its current durability score is 75 (above the
  70 gate)
- WHEN the conversion check runs
- THEN the remaining runner quantity is moved into the Long-Term book as its first
  tranche, rather than continuing to be managed by the swing book's trailing-stop/time-stop
  rules

### Requirement: Exits are thesis-driven, never time-based
The system MUST NOT apply a time stop to Long-Term positions. It MUST exit or halve a
position on: two consecutive quarters of guidance miss
(`LT_GUIDANCE_MISS_STREAK_EXIT`, sourced from `specs/concall-research-and-guidance-ledger`);
a governance tripwire (promoter pledge +10pp QoQ, auditor resignation, promoter stake sale
>2–3pp in a quarter, SEBI action); or valuation extremes (PEG > 4 with RS rolling over,
trim only). It MAY halve a position as optional crash protection when close is below the
40-week MA (`LT_CRASH_MA_WEEKS`) and the market regime is DEFENSIVE.

#### Scenario: Guidance miss streak
- GIVEN a held position has MISSED guidance for 2 consecutive reconciled quarters
  (`specs/concall-research-and-guidance-ledger`)
- WHEN the quarterly review runs
- THEN a thesis-stop exit is triggered, independent of the position's current price/P&L

### Requirement: Thesis-stopped names are quarantined from re-entry
The system MUST prevent re-entry into a thesis-stopped name for `LT_REENTRY_QUARANTINE_DAYS`
(90) days.

#### Scenario: Durability recovers within the quarantine window
- GIVEN a name was thesis-stopped 30 days ago (guidance-miss streak), and its durability
  score has since recovered above `LT_DURABILITY_GATE`
- WHEN the Long-Term book's entry logic considers it again
- THEN it is still excluded — the 90-day quarantine is time-based, not conditioned on the
  durability score recovering

## Known gaps / gotchas

- Off by default and gated by a single env-backed flag (`LT_BOOK_ENABLED`) — a spec or
  code reader must check this flag's current value before assuming this book is active.
- Own position ledger (`lt_positions`/`lt_trades`), own sizing/exit logic written inline
  in `longterm/book.py` — not shared with the other two books.
- No broker reference anywhere in this module — paper-only bookkeeping, no execution
  abstraction at all (contrast with positional's stubbed broker classes).
- Uses `pos_market_regime` (the same Minervini-style 18/20-month-ROC regime signal as the
  positional book) for its DEFENSIVE crash-protection check — a cross-book dependency
  worth knowing about when changing either.

## Source modules

`longterm/book.py`.
