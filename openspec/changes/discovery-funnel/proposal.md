# discovery-funnel

## Intent

Make Ideas answer "where should I be looking" instead of re-answering "what do you think of the
names I already typed".

## Why

**Ideas and Stock are currently the same screen.** Both call `POST /verdicts/evaluate`; Ideas
passes four symbols and Stock passes one. Ideas' default list is hard-coded to
`["RELIANCE","TCS","INFY","HDFCBANK"]` and Stock's default is `"RELIANCE"`. Neither surface can
tell you anything you did not already name.

That is the gap in the whole platform. It screens the NIFTY 500 for *eligibility*, evaluates
whatever it is handed, and has no answer to "what is worth looking at this week". A research
platform whose entry point is a symbol box requires you to have already done the research.

Two things exist and are thrown away:

* **Sector relative strength is already computed.** `_vishnu` ranks eight sector indices on RS
  versus the Nifty, per stock, then discards the ranking and keeps one boolean.
* **Every strategy already knows its own entry, stop and exit.** Minervini's pivot is the VCP
  base high; its stop is the base low; its exit is a 10-week average break. These are computed
  and never surfaced, so a BUY verdict tells you a name is attractive and not what to do about
  it.

## In scope

**Ideas becomes a top-down funnel** — market, then sectors, then names:

- **Market** — the benchmark's level and regime, measured now, against both Nifty 50 and
  Nifty 500.
- **Sector rotation** — every sector index placed by relative strength *and the direction that
  strength is moving*: leading, weakening, lagging, improving. A sector that is strong and
  rolling over reads differently from one that is weak and turning, and a flat ranked list
  cannot show the difference.
- **Movers within a sector** — constituents that actually did something, with the measurement
  that says so.

**A scan of the whole universe**, on a schedule and on demand:

- Every eligible NIFTY 500 name evaluated by all four strategies, persisted as one dated run.
- **Ranked by each name's strongest single strategy view, named** — never by an average, a
  count or a blend.
- **Business quality as a facet, not a gate** (see below).

**A plan attached to every actionable verdict** — entry, stop, target and expected holding
period, each derived by the strategy that produced the verdict and each traceable to evidence.

## Out of scope

- **Any blended score.** This is the change where one would look most useful and it is the
  thing the rebuild exists to remove. Ranking by *one named strategy's* conviction is
  attributable; ranking by a function of four is the confluence scorecard.
- **Ranking inside `screening/`.** That capability's spec requires that no ranking function
  exists there, asserted by a test. Ordering is a discovery concern and lives in its own module.
- **A model choosing candidates.** The scan is deterministic. Narration happens after the
  ranking and cannot change it.
- **Automatic orders.** A plan is a proposal. `Ledger.fill()` remains the one execution
  boundary and is reached deliberately.
- **Backtesting the plans.** Whether these exits would have worked is `backtesting`'s question
  and needs its own change.

## The quality filter is a facet, not a stage

The obvious funnel puts a fundamental quality gate early — ROCE, debt, sales growth — and cuts
500 names to 90 before the strategies run.

**That would break two of the four strategies.** Minervini and Young Momentum are price and
volume methods that deliberately do not ask about earnings quality; that independence is the
point of running four. A universe-wide fundamental gate ahead of them means they can never fire
on roughly three-quarters of the market, and nothing would report that they had been prevented
— they would simply appear to stop finding things.

So business quality is computed for every name and attached as a **facet** the reader can filter
and sort by, and it is a hard gate only inside the strategies that ask for it. The funnel
narrows on eligibility and on what the strategies actually say, not on a filter applied above
them.

## Risks

- **A ranked list is read as a recommendation**, whatever it is labelled. Mitigated by ranking
  on one named strategy's conviction, showing the other three beside it, and never presenting a
  number that is not attributable to a single strategy.
- **A weekly scan is a large job.** Screening the live NIFTY 500 costs ~330s on a cold cache and
  is fast on repeat; four strategies over the survivors is arithmetic. Narration is the
  expensive part and is confined to the ranked head, not the universe.
- **Derived plans will look more precise than they are.** Every plan figure carries the evidence
  it came from, and a plan is absent rather than approximated when the strategy has no basis
  for one.
