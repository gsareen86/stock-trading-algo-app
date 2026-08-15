# Instructions for AI agents working in this repo

This project uses **OpenSpec** for spec-driven development. `openspec/specs/` is the
source of truth for current system behavior; `openspec/changes/` is how behavior changes.
Read `openspec/project.md` first — it's the system map (architecture, stack, config
inventory).

## Before changing behavior

1. Find the relevant `openspec/specs/<capability>/spec.md` and read it. If none exists
   for the area you're touching, that's a gap — note it, don't skip the step.
2. If the change alters what the system *does* (not a pure refactor, typo fix, or
   comment), create `openspec/changes/<short-id>/`:
   - `proposal.md` — why, and what's in/out of scope (one sentence of intent; a good
     change is small enough to state in one)
   - `tasks.md` — implementation checklist
   - `design.md` — only if the technical approach needs explaining, not for every change
   - `specs/<capability>/spec.md` — the **delta**, using `## ADDED Requirements` /
     `## MODIFIED Requirements` / `## REMOVED Requirements` sections (same
     Requirement/Scenario shape as the main specs — see below)
3. Implement against the delta. Keep the change scoped to the one intent in the proposal
   — if you find yourself adding unrelated fixes, split them out.
4. **Archive when done**: merge the delta into `openspec/specs/<capability>/spec.md` (the
   ADDED/MODIFIED/REMOVED sections tell you exactly how the main spec should change), then
   move the change folder into `openspec/archive/`.

## The one rule that matters most

**A spec that isn't updated when its code changes is worse than no spec** — it becomes a
second thing to distrust, on top of the code. If you touch code covered by a
`Status: baseline` reference-depth spec, update that spec at archive time. This
repo already has one cautionary example: `docs/INVESTMENT_ENGINE_DESIGN.md` was headed
"Status: proposal" long after every phase in its own roadmap table had shipped. Don't let
`openspec/specs/` drift the same way.

## Spec format (for both `specs/` and change deltas)

```markdown
### Requirement: <Name>
The system MUST/SHOULD/MAY <one behavior, stated so someone outside the code could check
it>. (One requirement, one MUST — if it needs "and also," it's really two requirements.)

#### Scenario: <short, specific name>
- GIVEN <context/preconditions>
- WHEN <action/trigger>
- THEN <observable outcome>
- AND <additional outcome, if needed>
```

- Cover edge cases and gated/off states, not just the happy path — this codebase has
  many off-by-default flags (`LT_BOOK_ENABLED`, the six `LLM_ENABLE_*` toggles,
  `positional_enabled`, etc.); a Scenario for gated behavior **must** state the flag as a
  GIVEN, never assume it's on.
- Use RFC 2119 keywords deliberately: `MUST`/`SHALL` = non-negotiable current behavior,
  `SHOULD` = strong default with known exceptions, `MAY` = optional/conditional.
- When a spec's behavior depends on data that might be missing (fail-open gates, `None`
  pillar scores that get renormalized away, etc.), write that as its own Scenario rather
  than a footnote — this codebase has several fail-open gates and they're easy to miss.

## Depth is calibrated, not uniform — don't flatten it

Two capabilities (`fundamentals-quality-scoring`, `conviction-engine-scoring-routing`)
and one mechanism spec (`configuration-and-feature-flags`) carry full
Requirement+Scenario depth because they're where near-term work lands or are the named
pain point. The rest are intentionally `Status: baseline` — solid, code-grounded, but not
exhaustively scenario-covered, because OpenSpec's own guidance (and this repo's own
`INVESTMENT_ENGINE_DESIGN.md`) is that specs written for code nobody is touching go stale
fast. Promote a baseline spec to full depth naturally, the first time a real change
touches it — don't do it preemptively "to be thorough."

## Tooling

No CLI is installed in this repo — every file here is hand-authored to the format the
real `openspec` CLI (`npm install -g @fission-ai/openspec`) expects, so `openspec
validate`/`openspec view` would pass unmodified if it's ever run. **If `openspec` is
available on `PATH` in your environment, prefer it** for validating, listing, and viewing
specs/changes. Otherwise, follow the conventions in this file by hand — don't block on
the CLI being absent. We deliberately did not run `openspec init`, so the `/opsx:*`
slash-commands it would scaffold don't exist here; this file is the substitute.

## If a `CLAUDE.md` gets created later

Point it at this file rather than restating these instructions — one source of truth for
how to work in this repo, not two that can drift apart.
