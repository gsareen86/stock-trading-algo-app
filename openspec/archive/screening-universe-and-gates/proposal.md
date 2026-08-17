# screening-universe-and-gates

## Intent

Narrow a universe to the names worth evaluating, before four strategies spend an evaluation
each on names that were never eligible — and record why every exclusion happened.

## Why

`agent-graph-and-a2a` left `screen` out of the cycle because this increment had not happened.
The gap is now the binding one: a cycle takes a caller-supplied list of symbols, which means
the platform can answer "what do the strategies think of RELIANCE" and cannot answer "what is
worth looking at today". The second question is the one an unattended daily cycle exists for.

Running the universe through the strategies directly is not the answer. NIFTY500 × four
strategies is two thousand evaluations, each fetching price history, to discover that a few
hundred names never had enough liquidity to trade in the first place.

There is a second reason, and it is about correctness rather than cost. **Eligibility and
opinion are different questions.** A stock under an NSE surveillance measure is not
*unattractive* — it is one the platform should not be forming a view on at all. Today nothing
expresses that: `app/strategies/gates.py` answers "can this strategy assess this name", which
is a per-strategy question asked after the work is already being done.

## In scope

- **`app/screening/`** — eligibility filters and the screener that applies them
- **Turnover floor in rupees**, not share count. `volume > 0` passes a stock that traded
  eleven shares.
- **Surveillance exclusion** — NSE's ASM and GSM lists, as bundled data with a documented
  refresh path
- **Price floor** and **minimum history**
- **Every exclusion carries its reason and the value that caused it**, in the same
  evidence shape the rest of the platform uses
- **The `screen` node**, wired into the cycle ahead of research
- **`GET /universe`** and **`POST /screen`**

## Out of scope

- **Screener.in scraping.** `project.md` pencilled it in here, and it does not belong: screening
  needs cheap filters applied to a whole universe, and a per-name web scrape is the opposite of
  cheap. Deep fundamentals are already served by the `FundamentalsSource` seam where a strategy
  actually needs them. Revisit it if a screen ever needs a fundamental filter.
- **Ranking the survivors.** A screen decides eligibility, not merit. Ordering the output by
  anything that looks like quality would be a cross-strategy score by another name — the exact
  thing this rebuild exists to remove.
- **Governance scoring.** `project.md` lists governance beside liquidity and surveillance. There
  is no free, reliable source for it, and an invented proxy would be worse than its absence.

## Risks

- **A screen that is too strict silently hides opportunities.** Mitigated by reporting every
  exclusion with its reason and measured value, so an empty screen is diagnosable rather than
  mysterious.
- **Surveillance lists go stale.** They are bundled data, and a stale list under-excludes. The
  snapshot records when the list was last updated so staleness is visible rather than assumed
  away — the same treatment the holiday calendar gets.
