# Design: theme-engine

## The failure this is shaped around

> "I found the AI data-centre theme in late 2021 and bought NVIDIA, TSMC and ASML. I missed
> the energy, transformer and cable leg entirely."

Both halves matter. The theme was found — by reading, unaided. The chain was not, and no amount
of better reading would have produced it, because "who supplies the thing this consumes" is a
question you have to *ask*, and there was nothing to ask it of.

So the engine is two mechanisms, and they fail differently:

```
  sources ──► detection ──► THEME ──► expansion ──► chain ──► resolution ──► candidates
             (counted)               (model)                 (universe)      (graded)
             breadth +               tiers of                NSE-listed      established /
             persistence             inputs                  only            claimed /
                                                                             unestablished
```

Detection is arithmetic over documents. Expansion is world knowledge. Resolution is a lookup
against the universe. Only the middle step involves a model, and everything either side of it
is checkable.

## Why counting, and not asking a model what is hot

A model asked "what themes are emerging in India" will answer fluently, every time, whether or
not anything is emerging. The answer would be unfalsifiable and would change between runs.

Breadth and persistence are neither. "Fourteen companies across three sectors have referenced
this for three consecutive quarters" is a claim that can be wrong, checked, and disagreed with —
and it is the claim that separates a theme from a loud month. It is also the claim that would
have caught the data-centre power story: transformer and cable makers were saying it in their
order-book commentary long before the index noticed.

The model is used where its answer *is* the reliable kind: a data centre consumes power,
cooling and construction, and that does not vary by who is asked or when.

## The invariant, and why it is stated so bluntly

This is the first place model output reaches *what the platform looks at*. The line that keeps
it safe:

> **A theme may widen attention. It may never narrow it.**

Widening is cheap to make safe: a name a chain surfaces is still screened for eligibility and
still evaluated by all four strategies, and if they dislike it they say so. The model has
introduced a candidate, not an opinion.

Narrowing would be unsafe in a way that hides itself. If a theme could exclude, gate or reorder,
then a confabulated chain would remove real candidates and nothing in the output would show what
had been taken away — the same silent failure as putting a fundamental gate above four
strategies, which `discovery-funnel` refuses for the same reason.

Hence the scenarios asserting that verdicts are identical with themes on and off. If that test
ever fails, the invariant has been lost.

## Every link is an artefact

A chain link is stored as a row with its reasoning, not consumed as a transient prompt result:

```
theme      data centre buildout
tier 3     grid and power equipment
supplies   tier 2 (facility construction and fit-out)
because    "data centres draw continuous high load and require step-down
            transformation, switchgear and substantial cabling"
proposed   ollama/gemma4:12b, 2026-08-20
status     accepted | rejected
```

Three properties follow, and all three are requirements:

* **Visible** — a reader can see why a cable manufacturer is on their screen. Without this the
  engine is a black box recommending smallcaps.
* **Rejectable** — a wrong link is removed by the person who spotted it, and stays removed.
* **Never load-bearing** — the link produces a name to look at. It is not evidence, it cannot
  be cited, and it cannot move a conviction.

Rejection persisting across runs matters more than it looks. Without it, every run re-proposes
the same wrong link and the reader re-rejects it forever, which is how a review surface becomes
one people stop reading.

## Resolution is where India-only bites

The chain is expanded in terms of *inputs* — "high-voltage transformers", "power cable" — and
those have to become NSE symbols. Three outcomes, all of them legitimate:

| Outcome | Response |
|---|---|
| Suppliers exist and are listed | Candidates, graded |
| Suppliers exist, none listed in India | **"No Indian listed exposure"** |
| Description resolves to nothing | Recorded as unresolved, no candidate |

The second is the one that needs protecting. A tier like "EUV lithography" has no Indian
expression at all, and an engine that felt obliged to return something would hand over a
marginal smallcap with a superficially matching business description. Saying nothing is the
correct and more useful answer, and it is a scenario.

## Grading exposure, because conglomerates

An Indian index is full of companies for which a theme is 8% of revenue. Binary membership
would put them beside a pure play and imply they are the same trade.

Three grades, ordered by what supports them — segment disclosure, then management claim, then
nothing — and **no numeric strength**, deliberately. A number here would be sortable, and
sorting candidates by theme exposure is a ranking the platform does not permit. A named grade
is readable and refuses to become an ordering.

## What NSE gives for free

`research-data-sources` found that `/api/allIndices` returns, in the same payload as everything
else, about forty **thematic indices** — `NIFTY INDIA DEFENCE`, `NIFTY INDIA RAILWAYS PSU`,
`NIFTY EV & NEW AGE AUTOMOTIVE`, `NIFTY INDIA DIGITAL`, `NIFTY INDIA MANUFACTURING`,
`NIFTY MOBILITY`, `NIFTY CORE HOUSING`.

That is an official, exchange-maintained theme-to-constituent mapping, free, already fetched.
It is not a replacement for chain expansion — NSE will never publish a
"data-centre power chain" index, which is exactly the case that was missed — but it is two
useful things:

* a **baseline**, for themes the exchange already recognises;
* a **validation set**. If the chain expansion cannot rediscover most of `NIFTY INDIA DEFENCE`
  from the theme "defence indigenisation", the expansion is not working, and that is a test
  that can be written rather than a hope.

## Where this sits beside the rotation radar

`discovery-funnel` measures relative strength and its direction. This measures what companies
and policy are saying. They answer different halves of the same question and neither replaces
the other:

> **A theme says where to look before the price moves. Rotation says whether it has started.**

A theme with no price confirmation is early, or wrong. Rotation with no theme behind it is
noise. Shown together, disagreement between them is information — the same principle the four
strategies already work by.

## Cost, and the shape it forces

Detection reads documents, and `research-data-sources` established that commentary is
scrape-only: there is no licensed transcript source, so retrieval is slow and occasionally
fails. Three consequences:

* Theme runs are **weekly or ad-hoc**, never per-cycle.
* Documents are cached per URL and downloaded once, which is already how the tool behaves.
* Detection must **degrade to policy, filings and order-book data** when documents cannot be
  read, and record that it did — a run that quietly found fewer themes because a scrape failed
  would look like a quiet market.

Expansion is a handful of model calls per theme, not per company, so it is cheap and local.
Grading reads financials, which are metered at 500 requests a month — so grading is confined to
the candidates a reader actually opens, never applied across a whole chain speculatively.
