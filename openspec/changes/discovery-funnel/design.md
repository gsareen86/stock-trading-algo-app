# Design: discovery-funnel

## Three questions that must not become one

The platform already keeps three apart, and this change adds a fourth without collapsing any:

| Question | Capability | Answer shape |
|---|---|---|
| Should we look at this at all? | `screening` | eligible / excluded, with a reason |
| Can this strategy assess it? | `strategies/gates.py` | blocked / assessable |
| Is the setup attractive? | each strategy | one `Verdict` |
| **Where should I be looking?** | **`discovery`** | **ordered candidates, each attributed** |

`discovery` is a new module rather than an addition to `screening` for a specific reason:
`screening`'s spec requires that no ranking function exists there, and a test asserts it by
searching the module. Ordering is exactly what this change introduces, so it must live
somewhere the invariant does not apply — and stating that boundary is cheaper than weakening a
test that has been protecting the right thing.

## Ranking without blending

The rule this rebuild exists to enforce is that no value is computed across strategies. A
ranked list is where that rule is hardest to keep, because ranking is a single ordering and
there are four opinions.

The resolution is that the ordering key is **one strategy's number, and the strategy is named**:

```
entry:
  ticker            ASIANPAINT
  ranked_by         minervini        ← named, always
  ranked_conviction 82               ← that strategy's own figure, unmodified
  verdicts          [minervini BUY 82, bvm WATCH 41, fun_tech AVOID 12, young_mom WATCH 38]
```

`82` is a real, attributable figure that already exists and means what it has always meant. It
is not comparable to `41` from another strategy — and it is never compared, because the ordering
never mixes strategies within one entry. Two entries are ordered by their own ranking figures,
each attributed, which is the same act as sorting a table of "the best thing anyone said about
this name".

What stays forbidden: averaging the four, counting agreement into a score, weighting by
strategy, or any figure whose provenance is more than one verdict. Agreement is available as a
**filter** — "show me where at least three say BUY" — because a count of stances is a selection
criterion, not a rating. A scenario asserts the ordering rule survives that filter.

## Sector placement: two axes, because one hides the interesting case

A ranked list of sector strength answers "who is strongest" and cannot answer "who is turning".
Those are different questions and the second is the one that matters for a swing horizon: a
sector that has been strong for six months and is now losing relative strength is the one to
stop adding to, and a flat ranking puts it at the top.

So placement is on relative strength *and its derivative*:

```
                 RS rising          RS falling
  RS > benchmark  improving→LEADING  LEADING→WEAKENING
  RS < benchmark  LAGGING→IMPROVING  weakening→LAGGING
```

Every placement publishes both measurements, the window and the benchmark, so a reader can
disagree with the placement and see why it was made. A sector without enough history to measure
a change is **unplaced**, never defaulted into a quadrant — the same rule `sectors.resolve`
already follows for an unrecognised industry.

`^CRSLDX` (Nifty 500) is the more honest benchmark for sector RS than `^NSEI`, since a sector's
strength relative to fifty large caps is partly a size effect. Both are available; the
comparison names which was used.

## Why quality is a facet

The conventional funnel is: liquidity gate → fundamental quality gate → technical filter →
strategies. It is wrong here, and specifically wrong rather than merely suboptimal.

Two of the four strategies are price-and-volume methods that deliberately do not ask about
earnings quality. Placing a fundamental gate above them means they never see roughly
three-quarters of the universe. Worse, the failure is silent: those strategies would appear to
have stopped finding setups, and nothing would report that they had been prevented from
looking. Independence between the four is the property this rebuild was built to protect, and a
gate above all of them removes it in one line of pipeline code.

So the funnel narrows on eligibility and on what strategies actually say:

```
NIFTY 500
  └─ eligibility (liquidity, surveillance, history)      screening — unchanged
      └─ all four strategies, every survivor              deterministic, ~arithmetic
          └─ quality facet attached, never subtracted     from CompanyFinancialsSource
              └─ ordered by strongest single view         discovery
                  └─ narration + plans on the head        the only expensive step
```

Quality remains a hard gate exactly where a strategy asks for one — `fun_tech_momentum` already
gates on earnings — because that is a strategy's own criterion, evaluated inside it, and
visible as a failed gate on that strategy's verdict alone.

Sector-awareness is not optional here. Debt-to-equity discriminates for a manufacturer and
means little for a bank, and the NIFTY 500 is heavily financial. A measure that does not apply
is reported as not applicable, never as failed — the difference between "this bank is
leveraged" and "this measure does not describe banks".

## Plans come from strategies, not from a model

"What price do I buy at, where do I get out, how long do I hold" is the question the platform
has been unable to answer. The tempting implementation is to ask the narration model. That
would produce numbers with no provenance, in a platform whose entire traceability argument is
that every number in prose maps to an evidence row.

Every strategy already computes what it needs:

| Strategy | Entry | Stop | Exit condition |
|---|---|---|---|
| Minervini | VCP pivot — the base high | base low | 10-week average break |
| Young Momentum | continuation breakout level | pause low | failure to make a higher high |
| Brahma-Vishnu-Mahesh | multi-year base breakout | base floor | sector leaves the leading set, or regime turns |
| Fundamental-Technical | confirmed-growth breakout | base low | growth no longer confirmed at results |

These are the strategies' own rules, so a plan is a *restatement* of the verdict rather than a
new opinion — which is why every plan level cites an evidence row from the same verdict, and
why a strategy with no basis for an exit publishes no plan rather than a default.

The holding period follows the same discipline: it is a **condition with a typical duration**,
not a date. "Until the 10-week average breaks, historically weeks to months" is true.
"Sell on 14 October" is not something the method knows.

## Scan cost, and where narration sits

Screening the live NIFTY 500 costs ~330s on a cold price cache and is fast on a warm one; the
cache is per-instrument parquet and already populated for the full index. Four strategies over
the survivors is pandas arithmetic — tens of seconds.

Narration is the cost: 500 names × 4 strategies against a local 12B model is thousands of calls
at minutes each, which is not a job, it is a week. Narrating only the ranked head is therefore
not a compromise but the design — and it is only sound because ranking is deterministic and
happens *before* narration. A model that narrated first and ranked second would be choosing
candidates.

A run is persisted whole and never overwritten, so Ideas reads a table rather than recomputing,
and so two runs can be compared — which is the only way to see that a name entered or left the
list.
