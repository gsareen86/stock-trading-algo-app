# Design: verdict-model-and-minervini

## 1. The invariants live in the constructor

```python
Verdict:
    strategy_id, ticker, as_of
    stance:     BUY | WATCH | AVOID
    conviction: int 0-100
    gates:      tuple[GateResult, ...]
    evidence:   tuple[Evidence, ...]
    narrative:  str | None      # filled by verdict-narratives
    trace_id:   str | None
```

Four rules are checked when a `Verdict` is built, not when it is read:

1. **A failed hard gate forces `AVOID`.** Not "should" — the constructor rejects any other
   stance. This is the confluence-scorecard fix expressed as a type constraint, so a future
   strategy cannot reintroduce the bug by forgetting.
2. **Evidence ids are unique** within a verdict. Duplicates would make a narrative citation
   ambiguous, and an ambiguous citation is not a citation.
3. **Every gate's `evidence_ids` must exist.** A gate that cites nothing, or cites a row that
   was never emitted, is a claim with no backing.
4. **A verdict must carry evidence.** An empty evidence list means nothing was measured, which
   is not a judgement — it is a bug that would otherwise surface as a confident, unexplainable
   stance.

Conviction stays independent of the gates deliberately: it answers "how strong is this setup
*within this strategy*", and a gate answers "is this tradable at all". Folding the gate into
the score is precisely what the predecessor did.

## 2. Evidence is a measurement, not a sentence

```python
Evidence:
    id:         str          # stable within the verdict, e.g. "price_above_150dma"
    label:      str          # human phrasing
    value:      float | str
    threshold:  float | str | None
    operator:   ">=" | "<=" | ">" | "<" | "==" | "in" | "info"
    passed:     bool | None  # None for informational rows
    source_ref: str
    unit:       str | None
```

Carrying `threshold` and `operator` alongside `value` is what makes the row self-explaining.
"RS was 12.4%" is a number; "RS 12.4% ≥ 0% required — passed" is an argument, and the narrative
layer can render the second without inventing anything.

`passed=None` exists for context that is not a test — the last close, the number of
contractions found. Forcing every row into pass/fail would either drop that context or invent
thresholds for it.

`operator="info"` pairs with it so the renderer never has to guess whether a row is a claim.

## 3. Gates versus conviction, concretely

**Hard gates** in this strategy: sufficient price history, and non-zero traded volume. Both are
"can this even be assessed" questions. A stock with 40 bars cannot have a 200-day average, and
producing a confident verdict from a shorter window would be fabrication.

**The Trend Template's eight criteria are not gates.** They are the *score*: a stock failing
two of them is a weaker setup, not an unassessable one. Conviction is the share of criteria
passed, adjusted by VCP quality.

That split is the whole design. Gates answer *may we*; conviction answers *how much*. The
predecessor had one number answering both.

## 4. Conviction is a stated formula, not a feel

```
base        = 70 * (criteria_passed / 8)
vcp_bonus   = up to 25, from contraction count and tightness
volume_bonus= up to 5, for dry-up on the final contraction
conviction  = round(min(100, base + vcp_bonus + volume_bonus))
```

Two properties matter more than the exact weights. It is **reproducible** — same bars, same
number, no LLM involved. And it is **auditable** — every input is an evidence row, so a
conviction of 62 can be decomposed by a reader.

Stance follows from conviction and the Trend Template, both thresholds named as constants:
`BUY` needs the full template plus conviction ≥ 75; `WATCH` covers a partial setup; everything
else is `AVOID`.

## 5. VCP, and what it can honestly detect

Minervini's Volatility Contraction Pattern is successive pullbacks of decreasing depth on
declining volume. Detected here by finding swing pivots, measuring each pullback from local
high to local low, and requiring each contraction to be shallower than the last.

Two honest limits, recorded because a reader will otherwise assume more:

- **Pivot detection is windowed, not perfect.** A rolling-extremum approach finds the pivots
  that matter for a multi-week base but will disagree with a human chartist at the margins.
- **A two-contraction base is reported as such.** Minervini typically wants 2–4; fewer is
  reported with lower VCP quality rather than rejected, because "not yet a VCP" is a
  legitimate `WATCH`, not an `AVOID`.

## 6. Why the RS substitution is named, not hidden

Criterion 8 wants an IBD RS Rating — a percentile against every other stock — which needs the
universe ranked at once. This change evaluates named instruments, so it computes relative
return against a benchmark index instead.

The evidence id stays `rs_criterion` so the swap is invisible to downstream consumers, but the
*label and field* say `rs_vs_benchmark_pct`. A field called `rs_rating` holding something that
is not one would be believed by every reader afterwards, and quietly wrong numbers are the
thing this rebuild exists to stop.

## 7. Strategies mirror skills

Same registry pattern: `app/strategies/<name>/strategy.py` exporting `STRATEGY`, discovered by
convention, load failures recorded rather than swallowed. Two registries with different shapes
would be two things to learn; one pattern, used twice, is one.

A strategy `evaluate(instrument, context) -> Verdict | None` returns `None` only when it has no
opinion to offer at all — not as an error channel. Errors are gates that failed, which is a
verdict, because "I could not assess this" is information a reader wants.

## 8. Persistence needs no migration

`trading.verdicts` was created in `bootstrap-platform-skeleton` with exactly these columns —
`gates` and `evidence` as JSON, `narrative` and `trace_id` nullable. That it fits without
alteration is a small confirmation the decision model was understood before the schema was
written, rather than retrofitted onto it.
