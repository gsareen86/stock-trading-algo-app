# Instructions for AI agents working in this repo

This project uses **OpenSpec** for spec-driven development. `openspec/specs/` is the
source of truth for current system behavior; `openspec/changes/` is how behavior changes.
Read `openspec/project.md` first — it's the system map (architecture, stack, config
inventory).

This is a **rebuild**. The root-level `analytics/ dashboard/ data/ db/ engine/ llm/
longterm/ nlp/ positional/ scheduler/ scoring/ strategies/` packages are the **legacy
app**, kept read-only while data-acquisition plumbing is ported out of them, and deleted
at a tracked milestone. Never add features there. All new code lives in `backend/` and
`web/`.

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
     `## MODIFIED Requirements` / `## REMOVED Requirements` sections
3. Implement against the delta. Keep the change scoped to the one intent in the proposal.
4. **Archive when done**: merge the delta into `openspec/specs/<capability>/spec.md`, then
   move the change folder into `openspec/archive/`.

## The one rule that matters most

**A spec that isn't updated when its code changes is worse than no spec** — it becomes a
second thing to distrust, on top of the code. The previous incarnation of this app is the
cautionary example: `docs/INVESTMENT_ENGINE_DESIGN.md` was headed "Status: proposal" long
after every phase in its own roadmap table had shipped. This rebuild exists partly because
of that drift. Don't recreate it.

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

- Every Requirement needs **at least one Scenario**. No exceptions.
- Cover edge cases and gated/off states, not just the happy path. A Scenario for gated
  behavior **must** state the flag as a GIVEN, never assume it's on.
- Use RFC 2119 keywords deliberately: `MUST`/`SHALL` = non-negotiable, `SHOULD` = strong
  default with known exceptions, `MAY` = optional/conditional.
- When behavior depends on data that might be missing, write that as its own Scenario
  rather than a footnote.

## Rules specific to this rebuild

These encode the failures that caused the rewrite. Treat them as spec-level invariants.

1. **Verdicts are never blended.** Each strategy emits its own `Verdict`. Do not add a
   composite/confluence score across strategies — that is precisely what this rebuild
   removed. Cross-strategy agreement may be *displayed*, never *computed into a decision*.
2. **The LLM explains; it never decides.** Every `Verdict.stance` and `conviction` is
   produced by deterministic Python and must be reproducible with the LLM switched off.
   LLM output is confined to `Verdict.narrative`.
3. **Every narrative number must trace to an `Evidence` row.** Narrative generation
   receives only the evidence list, and generated text is validated against it.
4. **Gates are not scores.** A failed hard gate cannot be outweighed by a high score.
   Gates are evaluated and recorded separately from conviction.
5. **One config source of truth** — typed `pydantic-settings`, one precedence chain. No
   code-vs-env-vs-DB ambiguity, and no flag that isn't referenced by a spec.
6. **One ledger abstraction parameterized by book** — never a copy per book.
7. **Tests are part of done.** A change is not archivable without tests that would fail if
   the behavior regressed.

## Tooling

No CLI is installed in this repo — every file here is hand-authored to the format the real
`openspec` CLI (`npm install -g @fission-ai/openspec`) expects, so `openspec validate` /
`openspec view` would pass unmodified if it's ever run. **If `openspec` is available on
`PATH` in your environment, prefer it.** Otherwise follow the conventions here by hand —
don't block on the CLI being absent.

## If a `CLAUDE.md` gets created later

Point it at this file rather than restating these instructions — one source of truth for
how to work in this repo, not two that can drift apart.
