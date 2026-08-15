# skills-registry

## Intent

Package the platform's research capabilities as declared, schema-validated skills, so an agent
can discover and call them — and so everything they return is already shaped like evidence.

## Why

The agent cycle in `agent-graph-and-a2a` needs capabilities to call, and the narrative layer in
`verdict-narratives` needs every fact it explains to carry a source. Those two requirements
meet here: a skill is the thing that turns an external source into a row an `Evidence` entry
can point at.

Doing it as a registry rather than as functions an agent imports directly buys three things
that matter later:

- **One definition, two bindings.** The same manifest renders as a tool an LLM can call and as
  a skill advertised in an A2A agent card. Maintaining those separately would guarantee they
  drift, and the drift would be invisible until an external agent called something that no
  longer exists.
- **The contract is enforced, not documented.** Input and output are validated against JSON
  Schema at the boundary. An agent passing a malformed argument gets a typed refusal instead of
  a stack trace, and a source that changes shape is caught where it changed.
- **Adding a capability is one directory.** No orchestration change, no registration list to
  forget to update.

## In scope

- `app/skills/` — `SkillManifest`, `SkillResult`, and an auto-discovering `SkillRegistry`
- Input/output validation against each skill's declared JSON Schema
- **Evidence-grade output**: every returned item carries a `source_ref` and `observed_at`
- Bindings — one manifest rendered as an OpenAI-style tool definition *and* as an A2A card
  skill entry, without depending on either library yet
- Four seed skills:
  - **`news_research`** — RSS across seven Indian financial feeds, ticker matching via the
    80-name alias map ported from the predecessor
  - **`event_calendar`** — upcoming earnings and corporate events for an instrument
  - **`filings_scan`** — recent exchange announcements for an instrument
  - **`peer_compare`** — relative price performance against named peers, built on the
    `PriceSource` from `market-data-foundation`
- `GET /skills` listing the registered manifests

## Out of scope

- **LangGraph and A2A wiring.** The bindings produce the right shapes; binding them to a real
  graph or serving an agent card is `agent-graph-and-a2a`. Depending on those libraries now
  would couple this change to decisions that increment has not made.
- **Sentiment scoring on news.** Reading a headline and deciding it is bullish is a *decision*,
  and decisions are deterministic Python in this platform — `news_research` returns articles,
  not opinions.
- **Persisting skill output.** Skills are called within a cycle; what survives is the
  `Evidence` a strategy derives. A skill-output table would be a cache nobody asked for.
- Fundamentals-backed peer comparison — still waiting on `screening-universe-and-gates`, so
  `peer_compare` compares price performance, which the platform already has.

## Risks

- **Three of the four seed skills need the open internet**, and this environment's proxy
  denies the relevant hosts. They are built with injectable fetchers and tested against
  recorded fixtures; `peer_compare` runs fully offline and is what proves the registry
  end-to-end here.
- **A skill is an LLM-callable surface.** Anything it returns may end up in a prompt, so
  output validation is a safety boundary, not just a correctness one.
