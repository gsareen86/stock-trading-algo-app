# Design: tool-registry

## 1. Three things, three names

After this change the repo uses each term for exactly one thing:

| Term | What it is | Where it lives |
|---|---|---|
| **Tool** | schema-validated capability the *application* executes | `app/tools/<name>/tool.py` |
| **Agent Skill** | procedural knowledge the *model* reads | `SKILL.md`, arriving with `verdict-narratives` |
| **MCP tool** | a tool defined by an *external* server | Kite MCP, arriving with `agent-graph-and-a2a` |

The distinction that matters is not the file format, it is **who executes it**. A tool is
called by code and returns validated data; an Agent Skill is read by a model and returns
nothing. Those failure modes have nothing in common — a tool breaks with a schema violation
you can assert on, a Skill breaks by being ignored — so they should not share a word.

`to_a2a_skill` is the deliberate exception. The A2A agent-card format calls its entries
`skills`, and a renderer's job is to speak the target's vocabulary; renaming it would make the
function lie about the format it emits.

## 2. Descriptions are the selection signal

`summary` is what a model sees when choosing among tools. Today every summary answers *what*
and none answers *when*:

```
"List upcoming earnings and dividend events for a stock within a horizon."
```

Nothing in that sentence fires on "is Reliance reporting soon", "any events before I buy",
"why did this gap". With four local tools that is survivable. With four plus roughly twenty
Kite MCP tools, all plausibly about Indian equities, selection stops being obvious and the
description is the only thing the model has to go on.

So each summary gains an explicit trigger clause, in third person, following the form the
Anthropic guidance uses:

```
"List upcoming earnings and dividend events for a stock. Use when checking what is scheduled
 before entering a position, or when explaining a move that may be event-driven."
```

`description` — the long form for the A2A card and human readers — is left alone. It has a
different audience and a different length budget, which is why the two fields were split in
the first place.

## 3. What this change deliberately does not do

It does not add an MCP client. Kite MCP has no consumer until the agent graph exists, and
building a client against a protocol with nothing to call it would be the same speculative
generality that left `to_a2a_skill` untested against a real agent for three increments.

The lesson is worth stating in a design doc rather than a commit message: **`to_tool_definition`
and `to_a2a_skill` have never been called outside their own package.** One renders a format
that is now about to be exercised; the other guesses at a card shape no external agent has
read. Renaming is a good moment to notice which of the two earned its place.
