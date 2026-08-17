"""Building the narrative prompt.

The model is given the verdict's **evidence rows and nothing else** — no price series, no raw
frames, no fundamentals. That is not a token optimisation, it is what makes the guard possible:
a model handed the close price can compute a percentage and state it, and that percentage
would be arithmetically correct and completely untraceable. With no inputs to derive from,
every number in the output either came from an evidence row or was invented.

The stance arrives as a fact to explain, never as a question. Nothing the model returns is
read as a decision.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.domain.verdict import Verdict
from app.llm.types import Message

GUIDANCE_DIR = Path(__file__).parent / "guidance"
BASE_GUIDANCE = "_base"


@lru_cache(maxsize=16)
def guidance_for(strategy_id: str) -> str:
    """Shared rules plus this strategy's own vocabulary.

    A missing per-strategy file is not an error: the base rules alone still produce a correct,
    if more generic, narrative. Failing here would mean a new strategy could not be explained
    until someone wrote its prose guide.
    """
    base = (GUIDANCE_DIR / f"{BASE_GUIDANCE}.md").read_text(encoding="utf-8").strip()
    specific = GUIDANCE_DIR / f"{strategy_id}.md"
    if not specific.exists():
        return base
    return f"{base}\n\n{specific.read_text(encoding='utf-8').strip()}"


def _render_evidence(verdict: Verdict) -> str:
    lines = []
    for row in verdict.evidence:
        unit = f" {row.unit}" if row.unit else ""
        if row.threshold is not None and row.operator.value != "info":
            test = f" (tested {row.operator.value} {row.threshold}{unit})"
            outcome = " — passed" if row.passed else " — failed"
        else:
            test, outcome = "", ""
        lines.append(f"- [{row.id}] {row.label}: {row.value}{unit}{test}{outcome}")
    return "\n".join(lines)


def _render_gates(verdict: Verdict) -> str:
    if not verdict.gates:
        return "None recorded."
    return "\n".join(
        f"- {gate.label}: {'passed' if gate.passed else 'FAILED'} — {gate.reason}"
        for gate in verdict.gates
    )


def build_messages(verdict: Verdict) -> list[Message]:
    """The full prompt for one verdict."""
    system = guidance_for(verdict.strategy_id)

    user = f"""\
Stock: {verdict.ticker}
Strategy: {verdict.strategy_id}
Stance (already decided — explain it, do not revisit it): {verdict.stance.value}
Conviction within this strategy: {verdict.conviction} out of 100

Gates:
{_render_gates(verdict)}

Evidence — these are the only numbers you may state:
{_render_evidence(verdict)}

Write the explanation."""

    return [Message(role="system", content=system), Message(role="user", content=user)]
