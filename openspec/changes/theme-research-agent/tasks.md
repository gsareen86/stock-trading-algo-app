# Tasks: theme-research-agent

Depends on `theme-engine` for the tiers this decomposes and the universe it validates against.

## Spec
- [x] `proposal.md`, `tasks.md`
- [x] Deltas: themes (ADDED), tool-registry (ADDED), platform-configuration (ADDED)
- [x] Themes delta rewritten from fallback to augmentation, matching the reframed proposal
- [ ] `openspec/specs/` merged on archive

## Decided
- [x] **Two tools, not one, because they carry different risk.** Decomposition proposes
      *categories* and is model-only, offline-capable and safe by the same argument that makes
      chain expansion safe. Participant search proposes *names* and is the half that needs a
      provider, an allowance and universe validation. Collapsing them would put the safe half
      behind the provider that the risky half needs
- [x] **Search provider: Tavily**, because it returns excerpts written for a model to read
      rather than a page of link titles, and its free tier needs no card. The client is a
      protocol and every test runs offline against recorded results; Brave or SerpAPI is an
      adapter, not a rewrite
- [x] **Model for proposals.** Search-then-summarise rather than a model with built-in
      retrieval — the citation then comes from the search result rather than from the model's
      recollection, which is the whole safety argument

## Decomposition — the augmentation half
- [ ] `app/tools/tier_decompose/` — tier in, sub-categories out, each with supplier descriptions
- [ ] Sub-categories are categories, never company names or tickers
- [ ] Runs against **every** tier, not only unresolved ones
- [ ] A tier that cannot be decomposed resolves by its coarse description, and says so

## Search
- [ ] `app/tools/web_search/` — declared contract, results carry title, URL, excerpt
- [ ] Rate-limited via `app/core/rate_limit.py`; metered by a monthly allowance like the
      financials provider, reusing `MonthlyRequestBudget`
- [ ] Unreachable, unconfigured and exhausted are three distinct empty results

## Proposals
- [ ] `app/tools/theme_participants/` — sub-category in, proposed companies out, schema-validated
- [ ] Each proposal carries name, rationale and at least one source; uncited ones discarded
- [ ] Proposals name **companies**, never tickers — symbol resolution is the platform's
- [ ] Invalid output is `INVALID_OUTPUT`, never a partial list

## Validation — `app/themes/propose.py`
- [ ] Resolve proposed names against the universe: exact, then normalised, then unambiguous
      prefix
- [ ] **Ambiguity produces nothing.** Bharat Electronics and Bharat Dynamics are different
      companies, and several Tata entities are separately listed
- [ ] Unresolved proposals recorded as *proposed but not found*, never offered
- [ ] Search-derived candidates graded `unestablished`, basis naming search and its source
- [ ] Corroboration by the company's own commentary may raise the grade to `claimed`

## Wiring
- [ ] Every tier is decomposed; sub-categories resolve by the ordinary path
- [ ] Search runs only for a sub-category that description matching left empty
- [ ] A sub-category records whether it was searched, so "searched and found nothing" and
      "never searched" are distinguishable
- [ ] Migration `0010` — sub-categories, proposal provenance, per-sub-category search state

## Conversation
- [ ] `POST /research/ask` — a bounded tool-calling loop over the declared tools only
- [ ] Reuses `research_max_tool_rounds`; no unbounded loop
- [ ] Refuses stance-shaped requests and offers the four verdicts instead
- [ ] Web: a research surface, with every claim's tool result reachable

## Tests
- [ ] A resolved tier is decomposed anyway, and keeps every candidate it had
- [ ] A sub-category with matches is not searched; one without is
- [ ] Unavailable, unconfigured and exhausted search each degrade distinctly
- [ ] **A proposal matching nothing in the universe is never offered**
- [ ] **An ambiguous proposal produces no candidate**
- [ ] A foreign company is never a candidate
- [ ] An uncited proposal is discarded
- [ ] Search-derived candidates are graded `unestablished` and say why
- [ ] Corroborated candidates may be `claimed`, citing commentary not search
- [ ] **Verdicts identical with research on and off**
- [ ] Research removes no existing candidate and reorders nothing
- [ ] **No evidence row cites a search result**
- [ ] A stance-shaped request is declined
- [ ] A conversation writes no trade
- [ ] The tool loop is bounded
- [ ] Every provider client injectable; every test offline

## The case that motivated this, measured
Both halves are load-bearing and the fixture proves it. Against thirty real business
descriptions:

- **CG Power** is found by **decomposition alone**. Its description says "outsourced
  semiconductor assembly and testing" outright, so an OSAT sub-category matches it on four
  terms and ranks it first — where the coarse tier "semiconductor fabrication" tied it on one
  term with Infosys, Shree Cement and Voltas
- **Kaynes** is found by **search alone**. Its description says "integrated electronics
  manufacturer" and nothing more; the OSAT plant is real and post-dates the profile, so no
  granularity of description matching can reach it
- **EUV lithography** matches nothing, which is the correct answer and worth as much as the two
  names

- [ ] **Regression test**: an OSAT sub-category surfaces CG Power by description and Kaynes by
      search, and a lithography sub-category surfaces nobody
- [ ] Once it can, revisit `resolve.py`'s softened wording — "no company matched on name or
      industry" was written because the platform could not yet make the stronger claim
