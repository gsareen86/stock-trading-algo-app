# Tasks: skills-registry

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: skills-registry, platform-api

## Registry
- [x] `app/skills/types.py` — `SkillManifest`, `SkillResult`, `FailureReason`, `SkillContext`
- [x] `app/skills/registry.py` — discovery by convention, load-failure recording,
      input/output validation, failing soft
- [x] `app/skills/bindings.py` — `to_tool_definition`, `to_a2a_skill`
- [x] `app/skills/evidence.py` — the shared item shape all output schemas require

## Seed skills
- [x] `news_research/` — 7 RSS feeds + 80-name alias map, both as data resources
- [x] `event_calendar/` — upcoming earnings and corporate events
- [x] `filings_scan/` — recent exchange announcements
- [x] `peer_compare/` — relative price performance on the injected `PriceSource`

## API
- [x] `GET /skills` — manifests plus load failures, no handler references

## Tests (offline)
- [x] Manifest contract and duplicate-name rejection
- [x] Discovery finds a new skill; an unimportable one is recorded not swallowed
- [x] Input validation blocks the handler; output validation blocks the return
- [x] Missing `source_ref` fails output validation
- [x] Handler raise, unknown skill, distinct failure reasons
- [x] Both bindings render with no agent framework installed
- [x] Skill modules import no network client at module scope
- [x] `peer_compare` end to end on `FakePriceSource`, incl. unavailable peer
- [x] `news_research` against recorded feed fixtures, incl. alias matching
- [x] `GET /skills` shape and no handler leakage

## Verify & ship
- [x] `pytest`, `ruff`; `/skills` live
- [x] Archive deltas into `openspec/specs/`, move change to `openspec/archive/`
- [x] Commit, push
