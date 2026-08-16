# Tasks: tool-registry

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] `specs/skills-registry/` → `specs/tool-registry/`, terminology updated throughout
- [x] Delta: platform-api (MODIFIED — endpoint renamed)
- [x] `project.md` glossary gains Tool / Agent Skill / MCP tool, drawing the line once

## Code
- [x] `app/skills/` → `app/tools/`, each `skill.py` → `tool.py`, `SKILL` → `TOOL`
- [x] `SkillManifest` / `SkillRegistry` / `SkillResult` / `SkillContext` / `SkillHandler` /
      `SkillLoadFailure` → `Tool*`
- [x] `SKILLS_PACKAGE` → `TOOLS_PACKAGE`; `_NOT_SKILLS` → `_NOT_TOOLS`
- [x] `app/api/skills.py` → `app/api/tools.py`; `GET /skills` → `GET /tools`
- [x] `app.state.skills` → `app.state.tools`
- [x] `to_a2a_skill` keeps its name — the A2A card format calls them skills

## Selection metadata
- [x] Each manifest's `summary` gains a "Use when …" clause, third person
- [x] `summary` stays one line; `description` unchanged

## Tests
- [x] `tests/test_skills.py` → `tests/test_tools.py`; `test_skills_api.py` → `test_tools_api.py`
- [x] No behavioural assertion edited — the suite must pass on renamed symbols alone
- [x] A test asserting every manifest's summary states when to use it
