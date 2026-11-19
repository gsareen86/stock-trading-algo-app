"""Loader for procedural agent research skills under ``app/agents/skills/``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

SKILLS_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def load_research_skills() -> dict[str, str]:
    """Read all markdown skill files sorted by filename."""
    out: dict[str, str] = {}
    for path in sorted(SKILLS_DIR.glob("*.md")):
        out[path.stem] = path.read_text("utf-8").strip()
    return out


def combined_skill_prompt() -> str:
    """Compact procedural instructions ready to append to an agent's system prompt."""
    skills = load_research_skills()
    if not skills:
        return ""
    blocks = [body for body in skills.values() if body]
    return "\n\n---\n\n".join(blocks)
