# Tasks: verdict-narratives

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: verdict-narratives (new), decision-model (MODIFIED), platform-api (MODIFIED)

## Domain
- [x] `Verdict.with_narrative(text, trace_id)` — copy-with, sets those two fields only
- [x] `Verdict.citable_numbers` — values, thresholds, numbers in labels/ids, conviction

## Narratives
- [x] `app/narratives/guidance/*.md` — one per strategy plus a shared base
- [x] `app/narratives/prompts.py` — build messages from a verdict; evidence only, no prices
- [x] `app/narratives/guard.py` — extract numbers from prose; accept by correct rounding
- [x] `app/narratives/generator.py` — build → call → validate → attach, never raise

## API
- [x] `POST /verdicts/evaluate?narrate=true`, default false
- [x] Narration failures reported per verdict, not as a request failure

## Tests
- [x] Invented number rejects the whole narrative
- [x] Rounded evidence value accepted; near-miss rejected
- [x] Label-derived numbers (200-day, 52-week) accepted
- [x] Currency, percent, multiplier and comma-grouped forms all extracted
- [x] Unknown cited evidence id rejects
- [x] Gateway returning None leaves the verdict unchanged
- [x] Narration cannot alter stance, conviction, gates or evidence
- [x] Live: a real local model produces a passing narrative
