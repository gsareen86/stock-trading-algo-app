# theme-research-agent

## Intent

Refine a chain into the sub-categories that actually resolve, and let a person drive that
research conversationally.

## Reframed after `theme-engine` shipped

This change was written as a **fallback** — fire when a tier resolves to nothing. That was the
right shape when resolution classified companies by name and found three of nineteen defence
constituents. Classifying on business description took the same test to nineteen of nineteen,
so the premise the fallback rested on is gone, and the change is worth having for a different
and better reason.

**It is augmentation, not rescue.** A chain tier arrives coarse — *semiconductor fabrication* —
and coarse is what makes both its answers wrong. Decomposed into what the tier really contains:

| Sub-category | Indian listed exposure |
|---|---|
| EUV lithography | none, and truthfully none |
| Wafer fabrication | none today |
| Assembly and test (OSAT) | **Kaynes, CG Power** |
| Semiconductor design services | **Tata Elxsi, Cyient** |

The coarse tier produces either a misleading "no Indian exposure to semiconductors" or a vague
match that means little. The decomposed one produces a precise negative *and* real candidates —
and the precise negative is worth as much as the names, because it says where the value is
going and that it cannot be bought here.

So the agent runs against **every** tier, not only empty ones, and its output is finer supplier
descriptions that resolution then handles by the ordinary path.

## Why

Chain expansion produces tiers at the granularity a model volunteers, which is coarser than the
market. "Semiconductor fabrication" is one tier; the businesses inside it are lithography,
deposition, metrology, photoresist chemistry, wafer handling, assembly and test, and design
services. India has listed companies in two of those and none in the rest.

Resolution cannot fix that, because the input is already wrong: it is matching a coarse category
against companies that describe themselves precisely. It will either miss the specific ones or
return a vague set that means little, and neither answer tells a reader where the value in that
tier is actually going.

Decomposition is a **knowledge** problem — what does a fabrication plant consume, and what is a
distinct business rather than a step — answerable from public information the platform does not
hold and which changes over time. That is what search and a model are for.

The same machinery answers a second question worth asking on demand: *which Indian listed
companies participate in this specific thing*, for the sub-categories where description matching
still returns nothing.

## In scope

**Tier decomposition, run over every tier**

Given a tier and its reasoning, produce finer supplier descriptions. Those go back through
ordinary resolution, so a decomposed tier resolves by the same path as any other — and a
sub-category with genuinely no Indian exposure says so precisely instead of vaguely.

**Company proposals, where description matching finds nothing**

For a sub-category that still resolves to no instrument, search for participants by name. This
is the narrower half and it carries the sharper risk.

**Validation against the universe, before anything is offered**

Every proposed name is resolved against the platform's own universe before it can become a
candidate. A name that does not resolve is recorded as *proposed but not found* and is never
shown as something to buy. This is what makes the change safe: the model may propose company
names, but only the platform turns one into a candidate.

**An ad-hoc research conversation**

A surface for driving the same tools by hand — decompose a tier, search a sub-category, check a
company against a theme, read what management said. For the case the automatic path cannot
anticipate: a half-formed idea, a name someone mentioned, a theme the concept list has never
heard of.

**Citations, always**

Every proposal carries the sources it came from. A proposal with no citation is not a proposal,
it is a model's recollection, and this platform does not act on those.

## Out of scope

- **Any stance, conviction, target or recommendation.** The chat may research and propose. It
  may not say whether to buy. Verdicts stay with the four strategies and the boundary is a
  refusal, not a convention: nothing in this change may write a stance, and nothing it produces
  may become an `Evidence` row.
- **Non-Indian candidates.** Unchanged from `theme-engine`. Research is global; picks are not.
- **Narrowing.** Decomposition and search may only *add* sub-categories and names. Neither may
  remove a candidate, gate one, or reorder anything — a decomposed tier keeps everything the
  coarse tier resolved to.
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
