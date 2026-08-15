# Market Hygiene & Surveillance

Status: baseline — not yet exercised through a change under `openspec/changes/`.

Stage-0 hard gates: surveillance-list exclusion, liquidity floors, and microcap
safeguards. Deliberately kept as a narrow, standalone capability (rather than folded into
each book) because it applies asymmetrically across books — see the gap below.

## Requirements

### Requirement: ASM/GSM surveillance exclusion is fail-open
The system MUST exclude a ticker from the positional/long-term universe when it is a
*known* current entry on the ASM/GSM surveillance lists (`UNIVERSE_EXCLUDE_SURVEILLANCE`,
default on), refreshed on a throttle (`SURVEILLANCE_REFRESH_HOURS`, 12h). Missing or stale
surveillance data MUST NOT exclude a ticker — only a positive, known match blocks.

#### Scenario: Surveillance list fetch fails
- GIVEN the NSE ASM/GSM list scrape fails for this refresh cycle
- WHEN the universe filter runs
- THEN no ticker is excluded on surveillance grounds this cycle (fail-open), using
  whatever list was last successfully fetched if one exists

### Requirement: Tiered liquidity floors by book
The system MUST apply different minimum 60-day-median-daily-traded-value floors by book:
₹25 Cr/day for intraday-eligible names (`LIQUIDITY_FLOOR_INTRADAY_CR`), ₹5 Cr/day for
swing (`LIQUIDITY_FLOOR_SWING_CR`), ₹2 Cr/day for long-term (`LIQUIDITY_FLOOR_LT_CR`) —
**however, see the gap below: the intraday floor is defined but not actually enforced by
this module for intraday entries, since `data/hygiene.py` is never called from the
intraday path.**

#### Scenario: Swing entry on a thinly-traded name
- GIVEN a candidate's 60-day median daily traded value is ₹3 Cr (below the ₹5 Cr swing
  floor, but above the ₹2 Cr long-term floor)
- WHEN it is evaluated for a positional/swing entry vs. a long-term entry
- THEN it is excluded from the swing book on liquidity grounds but would pass the
  long-term book's looser floor — the same ticker can be liquid enough for one book and
  not another

### Requirement: Microcap safeguards
The system MUST apply extra constraints below `MICROCAP_MCAP_THRESHOLD_CR` (₹3,000 Cr):
cap microcaps at 35% of the swing book (`MICROCAP_MAX_BOOK_PCT`), halve per-trade risk
(`MICROCAP_RISK_MULT`, 0.5×), require ≥20% free float (`MICROCAP_MIN_FREE_FLOAT_PCT`),
reject pledge above 25% (`MICROCAP_MAX_PLEDGE_PCT`), and assume higher slippage (0.4% vs.
0.05% for large caps).

#### Scenario: Microcap with acceptable free float but high pledge
- GIVEN a sub-₹3,000cr-market-cap stock with 25%+ promoter pledge
- WHEN it is evaluated for the microcap safeguards
- THEN it is rejected on the pledge gate regardless of its free-float standing

## Known gaps / gotchas

- **`data/hygiene.py` is imported by `positional/universe_sync.py`, `positional/runner.py`,
  `positional/risk.py`, `longterm/book.py`, and `api/server.py` — never by anything under
  `engine/` or `strategies/`. The intraday book has no hygiene gate applied to it at all**,
  despite `LIQUIDITY_FLOOR_INTRADAY_CR` existing as a defined constant — that constant is
  effectively unused by the intraday path today. This is the single most concrete gap
  found in this codebase between "a constant exists suggesting a rule" and "the rule is
  actually enforced."

## Source modules

`data/hygiene.py` (282 lines).
