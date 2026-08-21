"""The ad-hoc research conversation.

The tests that matter here are the ones about what this surface *cannot* do. It is the most
open-ended thing in the platform — a person types a question and a model calls tools — so the
boundary has to hold structurally rather than by the model behaving.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.agents import conversation
from app.agents.conversation import Answer, ask
from app.agents.toolbelt import Toolbelt
from app.llm.types import LLMResult, ToolCall
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext
from tests.conftest import code_only


class _Gateway:
    """A gateway that replays a scripted sequence of model turns."""

    def __init__(self, *turns: LLMResult) -> None:
        self._turns = list(turns)
        self.calls = 0
        self.tools_offered: list[int] = []

    async def complete(self, task, messages, tools=None, schema=None, **kwargs):
        self.calls += 1
        self.tools_offered.append(len(tools or []))
        if not self._turns:
            return LLMResult(text="done", model="stub", provider="stub")
        return self._turns.pop(0)


def _text(body: str) -> LLMResult:
    return LLMResult(text=body, model="stub", provider="stub")


def _wants(name: str, **arguments) -> LLMResult:
    return LLMResult(
        text="", model="stub", provider="stub",
        tool_calls=[ToolCall(id="call-1", name=name, arguments=arguments)],
    )


def _toolbelt() -> Toolbelt:
    return Toolbelt(registry=ToolRegistry.discover(), context=ToolContext())


def _ask(question: str, gateway, rounds: int = 3) -> Answer:
    return asyncio.run(ask(question, toolbelt=_toolbelt(), gateway=gateway, max_rounds=rounds))


class TestTheLoopIsBounded:
    def test_a_model_that_keeps_calling_tools_is_stopped(self) -> None:
        """An unbounded loop against a local model is an afternoon."""
        gateway = _Gateway(*[_wants("web_search", query="again") for _ in range(20)])

        answer = _ask("what is happening in semiconductors", gateway, rounds=2)

        assert answer.rounds == 2
        assert answer.truncated

    def test_a_truncated_answer_says_so(self) -> None:
        gateway = _Gateway(*[_wants("web_search", query="x") for _ in range(9)])

        answer = _ask("anything", gateway, rounds=3)

        assert answer.as_dict()["truncated"] is True

    def test_an_answer_that_needed_no_tools_stops_immediately(self) -> None:
        gateway = _Gateway(_text("Nothing to look up."))

        answer = _ask("anything", gateway)

        assert answer.rounds == 1
        assert not answer.truncated

    def test_the_closing_pass_withdraws_the_tools(self) -> None:
        """Otherwise a model at its bound asks for another tool instead of answering."""
        gateway = _Gateway(_wants("web_search", query="x"), _wants("web_search", query="y"))

        _ask("anything", gateway, rounds=2)

        # The last call is the closing one, and it was offered nothing to call.
        assert gateway.tools_offered[-1] == 0


class TestEveryClaimIsTraceable:
    def test_the_tool_results_come_back_with_the_answer(self) -> None:
        gateway = _Gateway(_wants("web_search", query="osat india"), _text("Two companies."))

        answer = _ask("who does OSAT in India", gateway)

        assert [c.tool for c in answer.calls] == ["web_search"]
        assert answer.calls[0].arguments == {"query": "osat india"}

    def test_a_failed_tool_call_is_reported_not_hidden(self) -> None:
        gateway = _Gateway(_wants("web_search", query=""), _text("Could not look it up."))

        answer = _ask("anything", gateway)

        assert answer.calls[0].ok is False

    def test_nothing_it_returns_claims_to_be_measured(self) -> None:
        gateway = _Gateway(_wants("web_search", query="x"), _text("An answer."))

        payload = _ask("anything", gateway).as_dict()

        assert payload["measured_by_platform"] is False
        assert all(c["measured_by_platform"] is False for c in payload["calls"])


class TestThisSurfaceCannotAdvise:
    """The boundary is what the code can reach, not a list of phrasings it refuses.

    A blocklist fails both ways. It would refuse "should I buy more transformers than cables
    for this theme", which is a research question, and permit "which of these looks most
    attractive", which is not.
    """

    def test_no_answer_carries_a_stance_or_a_conviction(self) -> None:
        gateway = _Gateway(_text("Kaynes and CG Power both have OSAT plants."))

        payload = _ask("should I buy Kaynes", gateway).as_dict()

        assert payload["is_advice"] is False
        for forbidden in ("stance", "conviction", "verdict", "target", "rating", "score"):
            assert forbidden not in payload

    def test_the_module_cannot_reach_a_verdict_a_ledger_or_a_strategy(self) -> None:
        """Structural. There is nothing here that could produce a stance, whatever is typed."""
        from pathlib import Path

        for module in ("app/agents/conversation.py", "app/api/research.py"):
            source = code_only(Path(module).read_text("utf-8"))
            for forbidden in ("Ledger", "StrategyRegistry", "Verdict", "fill("):
                assert forbidden not in source, f"{module} reaches {forbidden}"

    def test_the_prompt_points_at_the_four_strategies(self) -> None:
        """Declining is less useful than saying where a verdict actually comes from."""
        assert "four strategies" in conversation.SYSTEM
        assert "does not decide" in conversation.SYSTEM

    def test_no_tool_it_can_call_returns_a_stance(self) -> None:
        registry = ToolRegistry.discover()

        for manifest in registry.manifests():
            properties = (manifest.output_schema or {}).get("properties", {})
            assert "stance" not in properties, manifest.name
            assert "conviction" not in properties, manifest.name


class TestTheEndpoint:
    def test_it_answers_and_returns_its_working(self, client: TestClient) -> None:
        client.app.state.gateway = _Gateway(
            _wants("web_search", query="osat"), _text("Two listed companies.")
        )

        body = client.post("/research/ask", json={"question": "who does OSAT in India"}).json()

        assert body["answer"] == "Two listed companies."
        assert body["calls"][0]["tool"] == "web_search"

    def test_an_empty_question_is_refused_by_the_contract(self, client: TestClient) -> None:
        assert client.post("/research/ask", json={"question": ""}).status_code == 422

    def test_it_offers_no_broker_tools(self, client: TestClient) -> None:
        """The toolbelt is the declared registry. MCP servers can place orders."""
        client.app.state.gateway = _Gateway(_text("ok"))

        client.post("/research/ask", json={"question": "anything"})

        from app.tools.registry import ToolRegistry as R

        names = set(R.discover().names())
        assert not any(n.startswith("kite") or "order" in n for n in names)

    def test_a_conversation_writes_no_trade(self, client: TestClient, session_factory) -> None:
        from sqlalchemy import func, select

        from app.persistence.models import Trade

        client.app.state.gateway = _Gateway(
            _wants("web_search", query="x"), _text("Kaynes builds an OSAT plant.")
        )

        with session_factory() as session:
            before = session.execute(select(func.count(Trade.id))).scalar_one()
        client.post("/research/ask", json={"question": "should I buy Kaynes"})
        with session_factory() as session:
            after = session.execute(select(func.count(Trade.id))).scalar_one()

        assert before == after == 0

    def test_no_gateway_is_a_503_not_a_silent_empty_answer(self, client: TestClient) -> None:
        client.app.state.gateway = None

        response = client.post("/research/ask", json={"question": "anything"})

        assert response.status_code == 503


class TestDegradation:
    def test_no_tools_at_all_is_reported_not_answered_anyway(self) -> None:
        gateway = _Gateway(_text("I would have answered."))

        answer = asyncio.run(
            ask("anything", toolbelt=Toolbelt(registry=ToolRegistry()), gateway=gateway, max_rounds=3)
        )

        assert answer.answer == ""
        assert "no tools" in answer.reason

    def test_no_model_is_reported_rather_than_guessed_at(self) -> None:
        class Silent:
            async def complete(self, *a, **k):
                return None

        answer = _ask("anything", Silent())

        assert answer.answer == ""
        assert answer.reason == "no model answered"

    @pytest.mark.parametrize("question", ["", "   "])
    def test_an_empty_question_produces_no_model_call(self, question: str) -> None:
        gateway = _Gateway(_text("should not happen"))

        answer = _ask(question, gateway)

        assert gateway.calls == 0
        assert answer.reason == "no question was asked"
