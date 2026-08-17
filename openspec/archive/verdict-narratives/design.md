# Design: verdict-narratives

## 1. The model never sees a price

The prompt carries the evidence rows and nothing else — no price series, no raw frames, no
fundamentals. That is not a token optimisation; it is the reason the guard can work at all.
A model given the close price can compute a percentage and state it, and that percentage
would be *arithmetically correct and completely untraceable*. Withholding the inputs means
there is nothing to derive from, so every number in the output either came from an evidence
row or was invented — and invention is exactly what the guard detects.

The verdict itself is decided before the prompt is built. The model receives the stance as a
fact to explain, never as a question. `AVOID` because a gate failed is explained as such; the
model cannot argue it up to `WATCH`, because nothing it returns is read as a stance.

## 2. What counts as a traceable number

`Verdict.numeric_values` gives evidence values and thresholds. That set alone is too strict:
a narrative saying "price is above its 200-day moving average" is correct, cites a real row,
and would be rejected because `200` is in the row's *label*, not its value.

So the allowed set is derived from four places, all of them things the verdict already
asserts:

| Source | Why |
|---|---|
| Evidence `value` | the measurement itself |
| Evidence `threshold` | what it was tested against |
| Numbers inside evidence `label` / `id` | `200`-day, `52`-week — the metric's own name |
| `conviction` | the one verdict-level number worth stating |

Deriving from labels rather than keeping an allowlist of "idiomatic" numbers matters: an
allowlist would be a guess about which constants are legitimate, would need editing every time
a strategy adds a lookback, and would silently permit `50` in a narrative about a strategy that
never mentions 50. Derivation permits exactly the numbers *this verdict* puts on the page.

**Matching is by rounding, not equality.** Evidence carries `12.437`; a readable narrative says
`12.4`. A number in prose is accepted when it is a correct rounding of some allowed value at
the precision the prose used — `12.4` matches `12.437`, `12` matches `12.437`, and `12.5` does
not. Requiring exact equality would reject every well-written narrative; allowing a fixed
epsilon would accept `12.9` on a slow day.

## 3. Rejection is whole-narrative, never repair

When a number fails to trace, the narrative is discarded and `narrative` stays `None`.

The tempting alternative — strip the offending sentence, or ask the model to fix it — is
wrong on both counts. A narrative with a sentence removed is a text no author wrote and no
reviewer approved, and its remaining sentences may depend on the excised one. A retry loop
hides the signal: if a model invents numbers on this prompt, that is a fact about the prompt
or the model that should surface as an absent narrative and a logged rejection, not be ground
down by resampling until something passes.

An absent narrative is already a first-class state. The verdict is complete without one.

## 4. Guidance is a prompt, not an Agent Skill

Each strategy gets a markdown file of explanation guidance — Minervini's prose should say
"contraction" and "pivot", BVM's should say "regime" and "sector leadership" — loaded by
`strategy_id` at prompt-build time.

These are deliberately **not** Agent Skills, despite being exactly the kind of procedural
knowledge `SKILL.md` exists for. An Agent Skill is read *by a model* with filesystem access,
progressively, as it decides what it needs. Narrative generation is one server-side
`gateway.complete` call with no filesystem and no agent loop, so there is nothing to disclose
progressively and no reader to do the disclosing. The app selects the one relevant file and
injects it.

Markdown on disk rather than string constants because this is content a human edits and
reviews, and because when `agent-graph-and-a2a` gives the research agent a real loop, this
content is already in the shape a Skill wants.

## 5. Truth is enforced; style is requested

The guard checks claims, not prose quality. Format guidance — three paragraphs, no markdown,
120–180 words — is instruction, and a narrative that ignores it is still published.

That line is deliberate and was drawn after watching a local 12B model. It followed every
numeric rule while ignoring the format entirely: 226 words, markdown headings, bullet lists.
Rejecting it would have discarded an accurate, useful explanation over presentation, and
*repairing* the formatting would be editing text nobody wrote — the same objection as §3.

The two failure modes are not comparable. An invented number is a false claim that reads
exactly like a true one; a stray heading is visible to anyone looking at it. Enforce the first
mechanically, request the second, and let a better model — or the rendering layer — handle
presentation.

One consequence for later: a narrative may contain markdown, so whatever renders it should
treat it as markdown rather than as plain text. That belongs to `gui-surfaces`.

## 6. Failure is silent, and the verdict is untouched

Every failure path — gateway returns `None`, prose fails the guard, a cited id does not exist —
produces a verdict with `narrative=None`. No exception reaches the caller and no field other
than `narrative` and `trace_id` is ever written.

That is what keeps design principle 5 (*the LLM explains; it never decides*) structurally true
rather than aspirational: `with_narrative` can only set those two fields, so there is no code
path by which generating prose alters a stance, a conviction, a gate or an evidence row.
Turning the LLM off changes what a verdict *reads* like and nothing about what it *says*.
