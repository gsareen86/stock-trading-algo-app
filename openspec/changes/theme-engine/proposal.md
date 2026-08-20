# theme-engine

## Intent

Surface what is changing in the Indian market before it is a headline, and name every listed
company that stands to be paid by it — including the ones three steps down the chain.

## Why

The platform can answer questions about a name. It cannot answer the question that actually
precedes owning anything: *what is happening, and who benefits?*

The operator's own account of the gap is the specification for this change. In late 2021 they
identified the AI data-centre and model-training theme from general reading, and bought the
first tier correctly — the GPU designer, the fab, the lithography monopolist. What they missed
was everything **downstream of the physical constraint**: data centres need power, power needs
transformers, switchgear, cable and grid. That second-order leg ran for two years and they had
no way to see it coming, because they had no way to ask the question.

So the failure was not a news-reading failure and better headlines would not have fixed it. It
was a missing capability: *given this theme, what does it consume, and who supplies that?*

Two separate problems fall out, and conflating them is why this is hard:

| | Question | The hard part |
|---|---|---|
| **Detection** | What is emerging? | Telling a real theme from a loud month |
| **Propagation** | Who benefits, at what tier? | The part that was actually missed |

**India only.** Every theme, every chain and every candidate is resolved against NSE-listed
companies. A theme with no credible Indian listed expression must say so rather than reach for
a tenuous smallcap.

## In scope

**Detection — from where money is committed, not where it is discussed**

A theme surfaces on **breadth and persistence**, both of which are counted rather than judged:
how many distinct companies and sectors reference it, and for how many consecutive periods. The
sources, in descending order of signal:

- **Management commentary** — `research-data-sources` shipped the tool. "We are seeing
  unprecedented demand for X" appears in a transcript quarters before it appears in a price.
- **Order books and capex** — Indian industrials report order inflow quarterly. A step-change
  across several companies in one chain is the cleanest early signal that exists, and it is a
  number.
- **Policy** — the India-specific one, with no US analogue in the same form. Themes here are
  very often *policy-initiated*: PLI schemes, the Green Hydrogen Mission, railway and defence
  capex in the Union Budget. Public, dated, free.
- **Exchange filings** — new capacity, plants, JVs, large orders. `filings_scan` exists.
- **News** — last, and only for timeliness.

**Propagation — a chain, expanded by a model, resolved to listed companies**

A theme is expanded into the physical and economic inputs it consumes, tier by tier, and each
tier is resolved to NSE-listed suppliers. The expansion is the one part a model does better
than a rule: it is world knowledge, not a market judgement.

**Exposure, graded rather than asserted**

Each candidate carries how much of its business actually touches the theme — `established`
(segment disclosure supports it), `claimed` (management says so, unverified), or
`unestablished`. All three are displayable answers.

## The architectural decision this change makes

**This is the first time model output influences what the platform looks at.** Everything until
now has been deterministic screen → deterministic strategies → prose written afterwards. A
chain expansion steering the candidate set is genuinely new, and it is being taken deliberately
rather than slid in.

It is safe under one invariant, which the delta enforces:

> **A theme may widen attention. It may never narrow it.**

A theme can add names to examine. It can never remove one, gate one, rank one, or touch a
stance or a conviction. Every name a theme surfaces goes through the same four strategies,
unchanged, and every link in every chain is stored with its reasoning, individually visible and
individually rejectable.

"The LLM explains, it never decides" survives intact: the model hypothesises a *linkage*, and
the strategies still decide.

## Out of scope

- **Predicting.** This surfaces persistence and breadth earlier than a headline reader would,
  and answers a propagation question that currently cannot be asked. It does not forecast.
- **Any theme-derived score, rank or stance.** A theme is a lens, not a verdict. Ranking
  candidates by theme strength would be a cross-strategy score wearing a new hat.
- **Non-Indian listings.** The chain may name a foreign company as an *explanation* of a tier;
  it is never a candidate.
- **Trading a theme.** No sizing, no basket, no allocation. `Ledger.fill()` remains the one
  execution boundary.
- **Sentiment scoring.** The same rule `news_research` and `commentary` already follow.

## Risks

- **A model will confabulate a plausible chain.** Mitigated by making every link an artefact:
  stored with its stated reasoning, visible, rejectable, and never load-bearing on its own —
  a chain link produces a name to look at, and looking is what the strategies do anyway.
- **False themes.** A month of noise looks like an emerging theme at low breadth. Mitigated by
  requiring breadth *and* persistence across periods, and by reusing withdrawal from
  `feed-freshness-and-run-control`: a theme that stops appearing is withdrawn with its reason.
- **Commentary is scrape-only and slower than hoped.** Change 3 established there is no
  licensed transcript source. Order-book and policy signals therefore carry more weight than
  originally assumed, and detection must degrade to them when documents cannot be read.
- **Conglomerate attribution.** A company deriving 8% of revenue from a theme is not a theme
  play. Graded exposure exists for this, and `unestablished` is a real answer.
