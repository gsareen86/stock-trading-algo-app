# theme-research-agent

## Intent

Go and find out, when name matching cannot: search for Indian listed companies that participate
in a theme, and let a person drive that search conversationally.

## Why

`theme-engine` resolves a chain tier to candidates by matching supplier descriptions against
company names and NSE industry classifications. That is the only company-level data the
platform holds, and it is far too shallow for the job. Measured against the live universe:

| Company | NSE industry | Actually does |
|---|---|---|
| Kaynes Technology India | Capital Goods | Building an OSAT semiconductor plant |
| CG Power and Industrial Solutions | Capital Goods | Semiconductor assembly JV |
| Tata Elxsi | Information Technology | Semiconductor design services |
| Dixon Technologies | Consumer Durables | Electronics contract manufacturing |

A tier for *semiconductor assembly and test* matches **none of them** — no name and no industry
string contains a semiconductor word. The engine therefore reports that a tier has no Indian
exposure while at least two real candidates sit unmatched in its own universe.

**That is the engine's most dangerous output**, because it is a confident negative. A missing
candidate is a gap a reader might notice; a stated "no Indian exposure" closes the question and
is believed. `theme-engine` had to soften the wording to what it actually knows — *no company
matched on name or industry* — and this change is what makes the stronger statement earnable.

The gap is a **knowledge** gap, not a data gap. "Which Indian listed companies are building OSAT
plants" is answerable from public information the platform does not hold and cannot cheaply
acquire, and it changes month to month. That is what search is for.

## In scope

**A targeted fallback, run automatically**

When a tier resolves to nothing, search for Indian listed companies that participate in it. The
input is a tier and its reasoning; the output is proposed symbols with citations.

**Validation against the universe, before anything is offered**

Every proposed name is resolved against the platform's own universe before it can become a
candidate. A name that does not resolve is recorded as *proposed but not found* and is never
shown as something to buy. This is the property that makes the whole change safe, and it is the
same one `theme-engine` relies on — the difference is only that the model now proposes company
names rather than supplier categories, so the check moves from implicit to explicit.

**An ad-hoc research conversation**

A chat surface for driving the same tools by hand: expand a theme, search a tier, check a
company against a theme, look up what management said. Useful for the case the automatic path
cannot anticipate — a half-formed idea, a name someone mentioned, a theme the concept list has
never heard of.

**Citations, always**

Every proposal carries the sources it came from. A candidate with no citation is not a
candidate; it is a model's recollection, and this platform does not act on those.

## Out of scope

- **Any stance, conviction, target or recommendation.** The chat may research and propose. It
  may not say whether to buy. Verdicts stay with the four strategies and the boundary is a
  refusal, not a convention: nothing in this change may write a stance, and nothing it produces
  may become an `Evidence` row.
- **Non-Indian candidates.** Unchanged from `theme-engine`. Research is global; picks are not.
- **Narrowing.** Search may only *add* names to tiers that resolved to nothing or few. It can
  never remove a candidate, gate one, or reorder anything.
- **Trading.** `Ledger.fill()` remains the one execution boundary, reached deliberately.
- **Replacing detection.** Themes still surface on counted breadth and persistence. Search finds
  *companies within a theme*, never the theme itself — otherwise the counts stop meaning
  anything and the engine goes back to asking a model what is hot.

## The risk this change actually carries

`theme-engine`'s chain expansion is safe largely because the model proposes **categories**,
which cannot be bought. Resolution against the universe is what turns a category into a name,
and that step is the platform's own.

Here the model proposes **names**, and that removes the structural safety. Indian markets make
this worse than average: Bharat Electronics and Bharat Dynamics are different companies, several
Tata entities are separately listed, and a plausible-sounding company may be unlisted, delisted,
BSE-only or renamed.

So the mitigation is not "prompt carefully". It is that a proposed name is inert until the
universe confirms it, every claim carries a citation a person can open, and the exposure grade
for a search-proposed candidate records exactly that: proposed by search, corroborated by
nothing the platform measured.

## Risks

- **A confident hallucination with a plausible citation.** Mitigated by universe validation and
  by never promoting a search-proposed candidate above the weakest exposure grade without
  independent corroboration.
- **A chat that becomes an advice surface.** Mitigated by refusing stance-shaped output and by
  keeping the chat a way to *drive* the research tools rather than a way around them.
- **Search costs money and the platform already has a budget.** Provider requests are metered
  like the financials provider, and an exhausted allowance degrades to "not searched", never to
  a guess.
- **A theme the concept list has never heard of.** The chat is the honest answer to that until
  the list grows — and what people search for is the best evidence of which concepts to add.
