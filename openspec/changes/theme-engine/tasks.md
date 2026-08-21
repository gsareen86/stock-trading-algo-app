# Tasks: theme-engine

Depends on `research-data-sources` — shipped. Commentary, financials, NSE index data and the
rate limiter are all in place.

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: themes (new), tool-registry (ADDED), web-shell (ADDED), platform-api (ADDED)
- [ ] `openspec/specs/themes/` created on archive; `project.md` surface table updated

## Persistence
- [x] Migration `0008` — `theme_runs`, `themes`, `theme_references`, `chain_links`,
      `theme_candidates`
- [x] Links carry reasoning, proposing model, and an accepted/rejected status that survives runs
- [x] Themes carry `first_seen_at`, `withdrawn_at`, `withdrawal_reason` — the same lifecycle
      `feed-freshness-and-run-control` gave insights, for the same reason
- [x] Runs are append-only and record which sources were unavailable

## Sources — `app/themes/sources.py`
- [x] Commentary adapter — concepts per company from their own transcripts, document limit
      respected, one unreadable document never loses the others
- [x] Policy adapter — scheme and budget coverage, **unattributed by construction** so a
      single announcement cannot inflate breadth; it corroborates a theme, never manufactures
      one
- [x] `compose_gatherer` — composes what answered; "not configured" and "could not be read"
      are recorded as the different facts they are
- [x] Every adapter signals a dead source by failing rather than by returning empty, so
      "answered with nothing recent" stays distinguishable from "could not be read"
- [x] Filings adapter — each announcement its own document, attributed to its company;
      weaker signal than commentary, stronger provenance

### Two corrections to what this file previously said
- [x] **Order books are not in the financials endpoint.** `quarter_results` carries sales,
      expenses, margins, profit and EPS and nothing about order inflow. Order books are
      disclosed in commentary — a sentence in a transcript, not a line item — so the
      commentary adapter is where that signal lives and `order_book` is one of its concepts
- [x] **Policy comes from English financial media, not PIB.** PIB's release listing is an
      ASP.NET postback page serving no links, and its RSS returns Hindi whatever the language
      parameter says, which English phrase matching cannot read. Indian financial media cover
      schemes in English within hours and the platform already reads those feeds. Recorded so
      nobody spends the same afternoon on PIB

## Detection — `app/themes/detect.py`
- [x] Concept extraction from documents, per company per period
- [x] Breadth (distinct companies, distinct sectors) and persistence (consecutive periods)
- [x] Minimum breadth and persistence thresholds, declared and configurable
- [x] Every reference stored with company, period and source ref
- [x] Counting is pure and reproducible over the same inputs

## Expansion — `app/tools/theme_chain/`
- [x] Declared tool: theme in, ordered tiers of inputs out, schema-validated
- [x] Output carries reasoning per tier and the model that produced it
- [x] Invalid output is an `INVALID_OUTPUT` result, never a partial chain
- [x] Tiers describe **inputs and supplier categories**, never instruments

## Resolution — `app/themes/resolve.py`
- [x] Supplier descriptions to universe instruments, via industry and business description
- [x] Unresolved descriptions recorded, never guessed
- [x] A tier with no Indian listed suppliers reports that plainly
- [x] Foreign companies may appear in reasoning, never as candidates

## Grading — `app/themes/exposure.py`
- [x] `established` / `claimed` / `unestablished`, each citing what supports it
- [x] Reads financials only for candidates actually opened — the provider allows 500 requests
      a month and speculative grading across a whole chain would spend it
- [x] No numeric exposure strength anywhere

## The invariant
- [x] Themes are additive only — no gate, no exclusion, no reordering
- [x] Assert `app/themes/` contains no function that scores or ranks instruments
- [x] Assert verdicts are byte-identical with themes active and disabled

## API
- [x] `POST /themes/run`, `GET /themes/runs`, `GET /themes/runs/{id}`
- [x] `GET /themes/{id}` — chain, tiers, candidates, grades
- [x] `POST /themes/links/{id}/reject`
- [x] Withdrawn themes excluded by default, requestable

## Web
- [x] Themes surface: current themes, evidence counts, sources reachable
- [x] Chain rendered tier by tier, reasoning visible in place, links rejectable
- [x] Candidates link to Stock; grades as named categories
- [x] "No run yet", "run produced no reading" and "no themes found" are three renderings
- [x] Nothing on the surface carries a theme-derived stance, score or ordering

## Wiring — themes widen a cycle and label its verdicts
- [x] `screen` takes theme candidates and **unions** them into the eligible set. The only
      operation performed on the screened list is a union, so the invariant is enforced by
      construction rather than by care
- [x] A theme name outside the universe is ignored; a failing theme source leaves the screen
      exactly as it was — widening is a bonus, losing the screen would be a regression
- [x] `theme_labels` node runs **after** narration, where every verdict already exists and is
      frozen. Remove the node and every verdict is byte-identical, which is the invariant
      proved by topology
- [x] Widening is reported (`theme_added`) so a longer instrument list is distinguishable from
      a screen that behaved differently

## Scheduling
- [x] `app/core/scheduler.py` — APScheduler, off by default, weekly theme run configurable
- [x] **Reload guard.** `uvicorn --reload` runs two processes and both execute the app factory,
      so a naive scheduler fires every job twice — silently, in development only. Two theme
      runs colliding is exactly what `running_run` refuses, so the symptom would have been a
      mysterious "already in progress" pointing nowhere near the cause
- [x] A failing job never reaches the scheduler: a job that dies takes its own run down, a
      scheduler that dies takes every future run and nobody notices for a week
- [ ] Wire the weekly job to the runner in `create_app`

## Tests
- [x] One company in one period is not a theme; broad-but-single-period is not a theme
- [x] Every reference traces to company, period and source
- [x] Unreadable commentary still produces themes from policy and filings, and records the gap
- [x] Every source unavailable → "no reading", not "no themes"
- [x] Tiers are dependency-ordered; every link carries reasoning and its model
- [x] Invalid model output produces no chain
- [x] **A rejected link stops contributing candidates, and stays rejected across runs**
- [x] A tier with no Indian exposure says so and offers no substitute
- [x] A foreign company in reasoning never becomes a candidate
- [x] Exposure grades cite what supports them; unestablished is still listed; no numeric grade
- [x] A faded theme is withdrawn with its reason, keeping its first-seen date
- [x] **An unavailable source never withdraws a theme**
- [x] Breadth and persistence recompute identically over the same inputs
- [x] **Verdicts identical with themes on and off** — asserted against a real cycle
- [x] **Grep `app/themes/` for ranking or scoring over instruments — none**
- [x] Rejection writes no trade

## Validation against the exchange's own themes
- [x] NSE publishes index constituents as archive CSVs (`/api/equity-stockIndices` 404s);
      NIFTY INDIA DEFENCE captured as a fixture
- [x] Baseline: themes the exchange already recognises need no chain expansion to find
- [x] **Expansion tested against them, and the answer is uncomfortable.** With all nineteen
      NIFTY INDIA DEFENCE constituents as the entire universe — every one available to be
      found — resolution finds **three**: BEL, BHARATFORG, SOLARINDS. It misses HAL, Bharat
      Dynamics, Mazagon Dock, Cochin Shipyard, Garden Reach, Zen, Paras, MTAR and Midhani.
      Seventeen of nineteen classify as "Capital Goods" and one carries "Defence" in its name.
      Recorded as a characterisation test so the number is visible rather than assumed;
      `theme-research-agent` exists to move it
