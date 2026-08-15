# Design: skills-registry

## 1. A skill is a manifest plus a handler

```python
SkillManifest:
    name:          str          # stable id, e.g. "news_research"
    version:       str
    summary:       str          # one line — this is what an LLM reads when choosing
    description:   str          # longer prose, for the agent card
    input_schema:  dict         # JSON Schema
    output_schema: dict         # JSON Schema
    handler:       Callable[[dict, SkillContext], dict]
    tags:          tuple[str, ...]
```

`summary` and `description` are separate on purpose. The summary is the sentence a model sees
when deciding *whether* to call a skill, and it competes for attention with every other tool
in the prompt; the description is documentation for a human or an external agent reading the
card. Collapsing them means one of the two audiences gets the wrong length of text.

Handlers take a `SkillContext` carrying the platform's collaborators — price source, calendar,
clock — rather than importing them. That keeps a skill testable with a fake source and stops
skills from quietly acquiring their own database connections.

## 2. Discovery is by convention

`app/skills/<name>/skill.py` exporting a module-level `SKILL: SkillManifest`. The registry
imports each subpackage and collects them.

The alternative — an explicit list — is one more place to forget. The cost is that a skill with
an import error disappears silently, so discovery **records load failures** rather than
swallowing them, and `GET /skills` reports them. A capability that vanished because of a typo
should not look like a capability that was never written.

## 3. Validation is the contract, in both directions

Input is validated before the handler runs; output before it is returned.

Input validation is obvious — an agent will eventually pass something wrong. Output validation
is the less obvious one and matters more here. These skills read RSS feeds and exchange
announcements, which change shape without warning, and whatever they return may end up inside
a prompt. Validating on the way out means a source that started returning something unexpected
fails at the skill boundary, loudly, instead of becoming a strangely-worded narrative that
nobody can trace.

`jsonschema` is already an installed transitive dependency, so this costs nothing new.

## 4. Everything a skill returns is evidence-shaped

Every item in a skill's output carries:

- `source_ref` — a URL or exchange identifier that a human can open
- `observed_at` — when the platform saw it

This is not decoration. `verdict-narratives` will reject any narrative containing a number
that does not trace to an `Evidence` row, and `Evidence.source_ref` has to come from
somewhere. Requiring it at the skill boundary means the traceability chain cannot be broken
later by a skill that simply forgot.

The output schemas enforce it, so "I forgot the source" is a validation failure rather than a
convention nobody checks.

## 5. Skills gather; they do not decide

The same rule the LLM gateway follows. `news_research` returns articles, not sentiment.
`peer_compare` returns relative performance numbers, not a ranking verdict. `filings_scan`
returns announcements, not a materiality judgement.

The predecessor blurred this — its news pipeline scored sentiment inline and stored the score,
which meant the score was untraceable and unversioned, and re-running it against a better
model would have silently changed history. Here, interpretation happens in a strategy or in a
narrative, both of which are explicitly traceable.

## 6. Failure is a result, not an exception

`registry.invoke()` returns a `SkillResult` with `ok=False` and a reason. A skill is called
from an agent loop, and one RSS feed being down must not end a cycle — the same reasoning that
makes the LLM gateway return `None`.

Failure reasons are typed (`unknown_skill`, `invalid_input`, `invalid_output`, `handler_error`,
`timeout`) because they have different fixes: invalid input is an agent problem, invalid output
is a source problem, and a handler error is ours.

## 7. Two bindings, no dependency

`to_tool_definition()` renders the OpenAI-style function schema an LLM consumes.
`to_a2a_skill()` renders the entry an A2A agent card advertises.

Both are plain dicts built from the manifest. Nothing imports LangGraph or `a2a-sdk` — those
land in `agent-graph-and-a2a`, and pulling them in now would mean guessing at decisions that
change has not made. What this change guarantees is that when they arrive, there is exactly one
source of truth for what a skill is.

## 8. Why `peer_compare` is price-based

Fundamentals were deferred to `screening-universe-and-gates`, so a fundamentals-backed
comparison cannot be built honestly yet. Price-based relative strength is genuinely useful —
Brahma-Vishnu-Mahesh ranks sectors on exactly this — and it is buildable now on the
`PriceSource` seam.

It also earns its place as the offline proof: with three seed skills needing hosts this
environment blocks, `peer_compare` is the one that demonstrates the whole registry path end to
end here, against `FakePriceSource`.
