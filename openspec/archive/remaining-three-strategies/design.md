# Design: remaining-three-strategies

## 1. What is a gate, decided once and applied three times

Minervini set the precedent loosely; three more strategies force it to be explicit.

**A gate answers: can this instrument be assessed at all by this strategy?** Not enough bars.
Never trades. No fundamentals when the strategy is fundamental. Those make an assessment
impossible, and a failed one forces `AVOID`.

**A hostile market is not a gate.** Brahma-Vishnu-Mahesh's BRAHMA leg checks whether the Nifty
is above a rising 20-week average, and the predecessor had a flag to *halt* on a bearish
reading. Here it is a criterion with dominant weight instead, for a reason worth stating: a
bear market does not make a stock unassessable, it makes it unattractive — which is exactly
what a low conviction says. Making it a gate would also force every BVM verdict in the market
to `AVOID` simultaneously, at which point conviction carries no information at all.

Fundamentals are the interesting boundary case. For Fun-Tech they *are* a gate — a
fundamental-screen strategy with no fundamentals is not a weak signal, it is no signal. For the
other two they are irrelevant, so their absence is not even recorded.

## 2. The fundamentals seam is four fields wide

```python
QuarterPoint:  period_end: date, value: float
QuarterlyFundamentals:
    symbol, eps: list[QuarterPoint], revenue: list[QuarterPoint], source_ref
```

Most-recent-first, because every comparison Fun-Tech makes is "latest versus something older",
and a caller reversing the list is the kind of off-by-one that silently inverts a growth test.

`market-data-foundation` deferred this precisely so it could be defined by a real consumer
rather than guessed. The predecessor's 361-line module also computed growth buckets and quality
scores — those are *decisions*, they get rewritten from spec in the screening change, and
importing them here would smuggle old scoring assumptions into a new strategy.

## 3. Brahma-Vishnu-Mahesh: three legs, three evidence groups

- **BRAHMA** — Nifty resampled to weekly, close above a rising 20-week SMA. Weekly because
  the strategy is explicitly a weekly-chart method; resampling daily bars is what the platform
  already has, and `1wk` from the provider would disagree at week boundaries.
- **VISHNU** — the instrument's sector index ranked against the other seven on a blend of
  3-month and 6-month relative strength versus the Nifty. Top three passes.
- **MAHESH** — a breakout from a horizontal range of at least 1.5 years, confirmed by weekly
  volume above 3× its average.

Sector membership comes from the universe snapshot's industry string, mapped through a data
file. When the sector is unknown or its index has no data, VISHNU is recorded as **not passed
with the reason stated**, not silently skipped — a criterion that quietly disappears would
inflate the proportion of criteria passed and therefore the conviction.

## 4. Fun-Tech: the surprise test is an OR, and that matters

The fundamental screen is:

```
(EPS_latest >= 1.5 × EPS_year_ago  OR  Revenue_latest >= 1.5 × Revenue_year_ago)
AND  EPS_latest >= 1.1 × EPS_previous_quarter
```

The OR is deliberate and is preserved as one criterion rather than split into two: a company
can show the acceleration this strategy hunts for through either line, and scoring them
separately would let a stock pass "half" of a test that has no half. The evidence row records
which side satisfied it.

Year-ago comparison uses the same quarter one year back — quarter four against quarter four —
because Indian results are seasonal and comparing Q3 to Q2 would read seasonality as growth.

## 5. Young Momentum: the pause is the whole signal

Base breakout, then a 20–50% impulse over 5–15 sessions, then a 2–6 day pause that must **not**
retrace past the 38.2% Fibonacci level of the impulse, on volume below the 20-day average.

The retracement bound is what separates this from Minervini: Minervini waits for several
contractions, this one buys the *first* pause. A deeper retracement is not a shallower signal —
it means the impulse failed, so the criterion is genuinely binary and the evidence records the
observed retracement against the 38.2% threshold.

The entry trigger — 0.1% above the pause high, with a stop below the pause low — is emitted as
informational evidence. It is a *level*, not a decision, and position sizing belongs to the
books increment.

## 6. Conviction formulas stay per-strategy and stay stated

Each strategy weights its own criteria; none of the four share a formula, and none is
comparable to another. That is not an oversight to tidy up later — a shared scale is the first
step back towards the confluence scorecard, because once two convictions are comparable
somebody will compare them.

Each is a documented arithmetic expression over its own evidence, reproducible with the LLM
switched off, exactly as Minervini's is.

## 7. Shared mechanics live in indicators

Weekly resampling, range breakout, tightness, impulse detection and Fibonacci levels are used
by more than one strategy and go in `indicators.py`. Anything that reads like one strategy's
judgement stays in that strategy's package — the test is whether a second strategy would want
it unchanged.
