# Design: feed-freshness-and-run-control

## Suppression and withdrawal are different questions

`insights-feed` established suppression: the same observation must not be re-raised every
morning. That is correct and it is why the feed is worth reading. Its unstated corollary is
what broke:

| | Question | Answer today | Answer after this change |
|---|---|---|---|
| Suppression | "Is this the same observation as one already standing?" | yes → don't write | unchanged |
| Refresh | "Is it still true, with a different number?" | *(never asked)* | update in place |
| Withdrawal | "Has it stopped being true?" | *(never asked)* | withdraw, with a reason |

The bug is entirely in the two rows nobody asked. `concentration:RELIANCE:35` suppressed every
later candidate — including, once the position closed, the absence of any candidate at all.
Absence was never an input.

## Preconditions become re-evaluable

Each generator in `rules.py` currently answers one question — *should this be raised now* —
and returns `Candidate`s. Reconciliation needs the inverse: given a standing row, is its
premise still true?

Rather than write a second set of rules that could drift from the first (the two-implementations
failure that `preview: true` exists to avoid elsewhere in this codebase), each generator gains
a **predicate keyed by dedupe key**. One cycle produces both: the candidate set, and a map from
dedupe key to "still true, and here is the current figure".

```
reconcile(standing, current_candidates_by_key):
    for row in standing:
        match current_candidates_by_key.get(row.dedupe_key):
            None            -> withdraw(row, reason)
            same figure     -> leave untouched
            moved figure    -> refresh(row, figure)
```

## The dangerous case: absence of evidence

`None` in that match is doing a lot of work, and it has three possible meanings:

1. the observation genuinely ended — the position closed, the thesis repaired;
2. the rule did not run this cycle — research was disabled, the symbol was not in scope;
3. the rule ran and its data source was unavailable — the provider was down.

Only the first is a withdrawal. Treating the other two the same way silently removes a valid
alert, which is worse than the staleness this change exists to fix: a stale insight is visibly
stale, and a withdrawn one is gone.

So reconciliation is **keyed on what the cycle actually re-evaluated**, not on what it failed to
produce. A cycle carries the set of `(kind, ticker)` pairs it genuinely assessed; anything
outside that set is untouched, and a rule whose source returned nothing reports that it could
not assess rather than that the observation ended. Four scenarios in the delta pin this down,
because it is the one way this design can do real damage.

**A cycle that only evaluates named symbols must not withdraw insights about the rest of the
book**, and a cycle run with research off must not withdraw the news insights research raised.

## Why `regime_change` is the awkward one

Its dedupe key carries the label (`regime_change:constructive`), which is deliberate — the
insight exists to mark a *transition*. But the body carries a level, and a level is a
measurement, so a transition insight is also carrying a figure that goes stale. Both are
right; they just have different lifetimes.

Resolution: the label continues to key identity, and the level is a refreshed measurement.
A regime that flips mints a new insight because the key changes. A regime that holds updates
its figure and keeps its age — which is what makes "constructive for six weeks" readable.

## Three timestamps, not two

`created_at` (first raised) and `read_at` (acknowledged) cannot express "raised on the 17th,
still true, measured today". `measured_at` is the third, and it is what a reader needs in order
to trust a number. Every figure the feed shows will carry the time it was established.

## The run control blocks, deliberately

A cycle over a handful of names takes seconds; over the universe it takes minutes. This change
ships a button that waits, because a button that waits honestly is better than no button, and
because `progress-visibility` is the change that has something real to stream. Making it
asynchronous here would mean inventing a job record that the next change would immediately
replace.

The one thing it must not do is lie on failure: a failed run leaves the existing feed on
screen. Replacing a populated feed with an empty state because a refresh failed is the
"empty book vs dead backend" confusion that `states.tsx` exists to prevent.
