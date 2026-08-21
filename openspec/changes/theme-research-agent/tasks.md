# Tasks: theme-research-agent

Depends on `theme-engine` for the tiers this searches and the universe it validates against.

## Spec
- [x] `proposal.md`, `tasks.md`
- [x] Deltas: themes (ADDED), tool-registry (ADDED), platform-configuration (ADDED)
- [ ] `openspec/specs/` merged on archive

## Decide first
- [ ] **Search provider.** Tavily and Brave both have usable free tiers and return excerpts;
      SerpAPI is richer and paid. Whichever is chosen, the client is injectable and every test
      runs offline against recorded results
- [ ] **Model for proposals.** Local gemma cannot search, so the loop is search-then-summarise
      rather than a model with built-in retrieval — which is the better shape anyway, because
      the citation comes from the search result rather than from the model's recollection

## Search
- [ ] `app/tools/web_search/` — declared contract, results carry title, URL, excerpt
- [ ] Rate-limited via `app/core/rate_limit.py`; metered by a monthly allowance like the
      financials provider, reusing `MonthlyRequestBudget`
- [ ] Unreachable, unconfigured and exhausted are three distinct empty results

## Proposals
- [ ] `app/tools/theme_participants/` — tier in, proposed companies out, schema-validated
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
- [ ] `resolve_tier` falls back to search only when name matching produced nothing
- [ ] A tier records whether it was searched, so "searched and found nothing" and "never
      searched" are distinguishable
- [ ] Migration `0009` — proposal provenance and per-tier search state

## Conversation
- [ ] `POST /research/ask` — a bounded tool-calling loop over the declared tools only
- [ ] Reuses `research_max_tool_rounds`; no unbounded loop
- [ ] Refuses stance-shaped requests and offers the four verdicts instead
- [ ] Web: a research surface, with every claim's tool result reachable

## Tests
- [ ] A tier with matches is not searched; a tier without one is
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

## The case that motivated this
- [ ] **Regression test**: a tier for semiconductor assembly and test must surface Kaynes and
      CG Power, both of which sit in the universe classified as "Capital Goods" and match
      nothing on name or industry. If this change cannot find them it has not worked
- [ ] Once it can, revisit `resolve.py`'s softened wording — "no company matched on name or
      industry" was written because the platform could not yet make the stronger claim
