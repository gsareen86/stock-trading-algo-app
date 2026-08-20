# Tasks: theme-engine

Depends on `research-data-sources` — shipped. Commentary, financials, NSE index data and the
rate limiter are all in place.

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: themes (new), tool-registry (ADDED), web-shell (ADDED), platform-api (ADDED)
- [ ] `openspec/specs/themes/` created on archive; `project.md` surface table updated

## Persistence
- [ ] Migration `0008` — `theme_runs`, `themes`, `theme_references`, `chain_links`,
      `theme_candidates`
- [ ] Links carry reasoning, proposing model, and an accepted/rejected status that survives runs
- [ ] Themes carry `first_seen_at`, `withdrawn_at`, `withdrawal_reason` — the same lifecycle
      `feed-freshness-and-run-control` gave insights, for the same reason
- [ ] Runs are append-only and record which sources were unavailable

## Sources
- [ ] `app/tools/policy_scan/` — government scheme and policy announcements, dated, with
      source refs; empty on failure, never raising
- [ ] Order-book and capex extraction from `/historical_stats` quarterly results
- [ ] Commentary retrieval via the shipped `commentary` tool, cached per document
- [ ] Filings via the existing `filings_scan`
- [ ] Each source records availability per run; detection degrades to what answered

## Detection — `app/themes/detect.py`
- [ ] Concept extraction from documents, per company per period
- [ ] Breadth (distinct companies, distinct sectors) and persistence (consecutive periods)
- [ ] Minimum breadth and persistence thresholds, declared and configurable
- [ ] Every reference stored with company, period and source ref
- [ ] Counting is pure and reproducible over the same inputs

## Expansion — `app/tools/theme_chain/`
- [ ] Declared tool: theme in, ordered tiers of inputs out, schema-validated
- [ ] Output carries reasoning per tier and the model that produced it
- [ ] Invalid output is an `INVALID_OUTPUT` result, never a partial chain
- [ ] Tiers describe **inputs and supplier categories**, never instruments

## Resolution — `app/themes/resolve.py`
- [ ] Supplier descriptions to universe instruments, via industry and business description
- [ ] Unresolved descriptions recorded, never guessed
- [ ] A tier with no Indian listed suppliers reports that plainly
- [ ] Foreign companies may appear in reasoning, never as candidates

## Grading — `app/themes/exposure.py`
- [ ] `established` / `claimed` / `unestablished`, each citing what supports it
- [ ] Reads financials only for candidates actually opened — the provider allows 500 requests
      a month and speculative grading across a whole chain would spend it
- [ ] No numeric exposure strength anywhere

## The invariant
- [ ] Themes are additive only — no gate, no exclusion, no reordering
- [ ] Assert `app/themes/` contains no function that scores or ranks instruments
- [ ] Assert verdicts are byte-identical with themes active and disabled

## API
- [ ] `POST /themes/run`, `GET /themes/runs`, `GET /themes/runs/{id}`
- [ ] `GET /themes/{id}` — chain, tiers, candidates, grades
- [ ] `POST /themes/links/{id}/reject`
- [ ] Withdrawn themes excluded by default, requestable

## Web
- [ ] Themes surface: current themes, evidence counts, sources reachable
- [ ] Chain rendered tier by tier, reasoning visible in place, links rejectable
- [ ] Candidates link to Stock; grades as named categories
- [ ] "No run yet", "run produced no reading" and "no themes found" are three renderings
- [ ] Nothing on the surface carries a theme-derived stance, score or ordering

## Tests
- [ ] One company in one period is not a theme; broad-but-single-period is not a theme
- [ ] Every reference traces to company, period and source
- [ ] Unreadable commentary still produces themes from policy and filings, and records the gap
- [ ] Every source unavailable → "no reading", not "no themes"
- [ ] Tiers are dependency-ordered; every link carries reasoning and its model
- [ ] Invalid model output produces no chain
- [ ] **A rejected link stops contributing candidates, and stays rejected across runs**
- [ ] A tier with no Indian exposure says so and offers no substitute
- [ ] A foreign company in reasoning never becomes a candidate
- [ ] Exposure grades cite what supports them; unestablished is still listed; no numeric grade
- [ ] A faded theme is withdrawn with its reason, keeping its first-seen date
- [ ] **An unavailable source never withdraws a theme**
- [ ] Breadth and persistence recompute identically over the same inputs
- [ ] **Verdicts identical with themes on and off**
- [ ] **Grep `app/themes/` for ranking or scoring over instruments — none**
- [ ] Rejection writes no trade

## Validation against the exchange's own themes
- [ ] Load NSE's ~40 `THEMATIC INDICES` and their constituents from `/api/allIndices`
- [ ] Baseline: themes the exchange already recognises need no chain expansion to find
- [ ] **Expansion is tested against them** — expanding "defence indigenisation" should
      rediscover most of `NIFTY INDIA DEFENCE`. If it cannot, expansion is not working, and
      this is the test that says so rather than a hope
