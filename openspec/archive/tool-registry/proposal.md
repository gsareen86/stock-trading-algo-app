# tool-registry

## Intent

Rename `skills-registry` to `tool-registry`, and give each tool a description a model can
actually select on. The registry is a tool-use layer; calling it "skills" collides with a
different, specific thing that this platform is about to also want.

## Why

Anthropic's [Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
are a defined artefact: a `SKILL.md` file with YAML frontmatter, holding *procedural knowledge*,
loaded from the filesystem by the model through progressive disclosure — metadata always
resident, body read on trigger, bundled files read on demand. No schema, no handler; the model
executes the instructions.

What `app/skills/` holds is the opposite in every one of those respects: a Python manifest and
a handler, executed **by the application**, with JSON Schema enforced in both directions and
nothing loaded into a context window. That is *tool use*, which Anthropic documents separately
and which `to_tool_definition` already renders correctly.

Two forces make this worth fixing now rather than later:

- **A third meaning arrives with MCP.** Kite MCP brings ~22 externally-defined tools into the
  agent graph. At that point "skill" means three things in one repo — this registry, an
  Agent Skill, and an MCP tool — and the cost of the collision stops being theoretical.
- **`verdict-narratives` wants real Agent Skills.** Explaining what a VCP contraction signals
  is procedural knowledge, exactly what `SKILL.md` is for. That name should be free when it
  gets here, and it must not be confusable with the deterministic gate code it explains.

Separately, the manifests fail the selection test the same docs are emphatic about: a
description must say **what it does and when to use it**, because it is the only signal a
model has when choosing among tools. `"List upcoming earnings and dividend events for a stock
within a horizon."` says what, and offers no trigger.

## In scope

- `app/skills/` → `app/tools/`; `skill.py` → `tool.py`; `SKILL` → `TOOL`
- `SkillManifest`/`SkillRegistry`/`SkillResult`/`SkillContext` → `Tool*`
- `GET /skills` → `GET /tools`
- Capability spec `skills-registry` → `tool-registry`
- Every manifest gains a `when_to_use` clause folded into its summary

## Out of scope

- **The archive.** `openspec/archive/skills-registry/` keeps its name and its wording. It is a
  record of what was decided in the past, not a description of current truth, and rewriting
  history to match the present is exactly what an archive must not do.
- **Behaviour.** Schemas, handlers, validation and failure semantics are untouched. If this
  change alters a single evidence row, it has gone wrong.
- **`to_a2a_skill`.** Keeps its name deliberately: the A2A card format genuinely calls these
  entries "skills". Translating to a foreign vocabulary is the function's whole job.
- **Writing actual Agent Skills.** Belongs to `verdict-narratives`, which has a prompt worth
  teaching against. Adding a `SKILL.md` here with no consumer repeats the mistake this change
  is partly cleaning up.

## Risks

- **A rename is a large diff with no tests to fail if it is done wrong.** Mitigated by the
  suite: 416 tests must pass unchanged, and no behavioural assertion may be edited.
- **Grep-driven renames catch substrings.** `skill` appears inside `to_a2a_skill`, which must
  survive. Verified explicitly rather than trusted to the pattern.
