"""Driving the research tools by hand, in a bounded loop.

For the case the automatic path cannot anticipate: a half-formed idea, a name someone
mentioned, a theme the concept list has never heard of. The weekly run reads what it can reach
and counts what it finds; this is how a person asks about something it has not got to yet.

**It drives the tools rather than replacing them.** Every claim it makes comes back with the
tool result that produced it, and the transcript is returned alongside the answer so a reader
can open what it read. A conversation that summarised tool output without exposing it would be
a model's account of the evidence rather than the evidence.

**Why the stance boundary is structural and not a word filter.** This surface may research and
may not advise. The temptation is a blocklist of phrasings like "should I buy", which fails
both ways: it refuses "should I buy more transformers than cables for this theme" and permits
"which of these is most attractive right now". So the boundary is built from what the code can
reach instead:

* it holds no strategy, no ledger and no verdict writer, so there is nothing here that *could*
  produce a stance, whatever anyone types
* the toolbelt is the declared registry and nothing else, and no tool in it returns a stance
* the system prompt states the boundary and names where verdicts actually come from, so a
  reader asking for one is pointed at the four strategies rather than stonewalled

The prompt is what makes the refusal *useful*; the missing capability is what makes it *true*.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.toolbelt import Toolbelt
from app.llm.types import LLMGateway, Message

log = logging.getLogger(__name__)

TASK = "research"

#: What the model is told it is, and is not. The second paragraph is the one that matters:
#: pointing a reader at the four strategies is more useful than declining, and it is also
#: true — a verdict exists, it is just not produced here.
SYSTEM = """You help an analyst research Indian listed equities by calling tools.

Call the tools that would answer the question, then answer from what they returned. Every \
figure you state must come from a tool result in this conversation. If the tools cannot answer, \
say so plainly rather than filling the gap from memory.

You do not give investment advice, and this is a capability boundary rather than a \
preference: nothing you can call produces a stance, a conviction, a target or a rating. If \
you are asked whether to buy, sell or hold something, or which of several names is best, say \
that this surface researches and does not decide, and that verdicts come from the platform's \
four strategies, each of which states its own stance separately and never blends them.

Research may look anywhere in the world. Only the companies you name as investable must be \
listed in India — a supply chain that runs through a Dutch toolmaker and a Taiwanese fab is \
worth describing, as long as it is clear which parts of it can be bought here."""


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """One tool call, kept so the reader can open what the answer was built from."""

    tool: str
    arguments: dict[str, Any]
    ok: bool
    result: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "ok": self.ok,
            "result": self.result,
            # Tool output, quoted. Never a measurement this conversation made.
            "measured_by_platform": False,
        }


@dataclass(frozen=True, slots=True)
class Answer:
    """What one question produced, and everything it was built from."""

    question: str
    answer: str
    calls: list[ToolCallRecord] = field(default_factory=list)
    rounds: int = 0
    #: True when the loop hit its bound with the model still wanting to call tools. The answer
    #: stands, and the reader is told it is working from a partial read.
    truncated: bool = False
    model: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "calls": [c.as_dict() for c in self.calls],
            "rounds": self.rounds,
            "truncated": self.truncated,
            "model": self.model,
            "reason": self.reason,
            # Nothing this surface returns is a stance, and nothing it returns may become
            # evidence. Carried so no caller has to infer it.
            "is_advice": False,
            "measured_by_platform": False,
        }


async def ask(
    question: str,
    toolbelt: Toolbelt,
    gateway: LLMGateway,
    max_rounds: int = 3,
    model: str | None = None,
) -> Answer:
    """Answer one research question, calling tools at most ``max_rounds`` times.

    Bounded rather than run-until-done. An unbounded loop on a local model is an afternoon,
    and a model that has misunderstood the question will keep calling tools about the wrong
    thing until something stops it.
    """
    question = " ".join((question or "").split())
    if not question:
        return Answer(question="", answer="", reason="no question was asked")

    tools = toolbelt.definitions()
    if not tools:
        return Answer(question=question, answer="", reason="no tools are available")

    messages = [
        Message(role="system", content=SYSTEM),
        Message(role="user", content=question),
    ]

    calls: list[ToolCallRecord] = []
    rounds = 0
    truncated = False
    final = ""

    for _ in range(max(1, max_rounds)):
        rounds += 1
        result = await gateway.complete(task=TASK, messages=messages, tools=tools)
        if result is None:
            return Answer(
                question=question,
                answer="",
                calls=calls,
                rounds=rounds,
                reason="no model answered",
            )

        requested = result.tool_calls or []
        if not requested:
            final = (result.text or "").strip()
            break

        for call in requested:
            ok, text = await toolbelt.invoke(call.name, call.arguments)
            calls.append(
                ToolCallRecord(
                    tool=call.name, arguments=dict(call.arguments or {}), ok=ok, result=text
                )
            )
            messages.append(Message(role="assistant", content=f"[called {call.name}]"))
            messages.append(Message(role="user", content=f"Result of {call.name}: {text}"))
    else:
        # The bound was reached with the model still calling tools. The answer below is
        # produced from what was gathered, and `truncated` says it is a partial read.
        truncated = True

    if not final:
        # One last pass with the tools withdrawn, so the model has to answer from what it
        # collected rather than asking for more.
        messages.append(
            Message(
                role="user",
                content=(
                    "Answer now from the tool results above. State only what they show, and "
                    "say plainly what they did not answer."
                ),
            )
        )
        closing = await gateway.complete(task=TASK, messages=messages)
        final = (closing.text or "").strip() if closing is not None else ""

    return Answer(
        question=question,
        answer=final,
        calls=calls,
        rounds=rounds,
        truncated=truncated,
        model=model,
        reason=None if final else "the model produced no answer",
    )
