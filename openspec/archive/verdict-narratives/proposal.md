# verdict-narratives

## Intent

Turn a verdict's evidence rows into plain English, without letting the model add a single
number the verdict did not measure.

## Why

A `Verdict` today is a stance, a conviction and a list of `Evidence` rows. That is complete
and reproducible, and almost unreadable — "RS_63D 12.4 >= 0.0 passed" is an argument only if
you already know the strategy. The narrative is what makes the platform usable by a person
rather than by its own author.

It is also the single most dangerous thing in the system. An LLM writing about a stock will
reach for numbers, and a plausible invented figure inside otherwise-correct prose is worse
than no narrative at all: it reads exactly like the traceable parts. `project.md` already
committed to the answer — *"a post-generation validator rejects any narrative containing a
number absent from the evidence set"* — and `Verdict.numeric_values` was built in
`verdict-model-and-minervini` specifically to be that set. This change makes it real.

## In scope

- **`app/narratives/`** — prompt construction, validation, generation
- **Per-strategy guidance** as versioned markdown: what a VCP contraction means, what a weekly
  regime read implies, so the prose uses each strategy's own vocabulary
- **The numeric guard** — every number in generated prose must trace to the evidence, or the
  whole narrative is discarded
- **Citation checking** — cited evidence ids must exist on the verdict
- **`Verdict.with_narrative()`** — the frozen type gains a copy-with, not a setter
- **`POST /verdicts/evaluate?narrate=true`** — off by default
- Offline tests, plus live verification against a local model

## Out of scope

- **Narratives for the portfolio/insights layer.** Different input, different audience, and
  `insights-feed` has not been designed yet.
- **Prompt versioning in Langfuse.** Worth doing once there is a prompt with a history worth
  comparing; today there is one, a week old.
- **Streaming.** Nothing renders a narrative token by token.
- **Repairing a rejected narrative.** See `design.md` §3 — a repaired narrative is one nobody
  wrote, and the failure it hides is the one worth seeing.

## Risks

- **The guard is only as good as its number extraction.** Prose says "12.4%", "₹1,234.50",
  "2.5x", "a third". Missing a form means an invented number passes. Mitigated by extracting
  aggressively and failing closed, and by an explicit test per numeric form.
- **Over-rejection makes the feature useless.** A narrative correctly saying "the 200-day
  moving average" must not be rejected because 200 is not an evidence *value*. Handled by
  deriving allowed numbers from evidence labels too, rather than hardcoding an allowlist —
  see `design.md` §2.
- **A local model may simply be bad at this.** Acceptable: the narrative is optional, its
  absence is a supported state, and the verdict is unchanged either way.
