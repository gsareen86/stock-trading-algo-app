"""The cycle graph, its isolation guarantee, and the toolbelt.

The property under test that justifies the LangGraph dependency at all: four strategy nodes
run concurrently and none of them can observe another's verdict. Everything else here is the
usual contract — nothing raises, and the LLM being absent changes nothing a verdict says.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents import nodes
from app.agents.graph import build_graph, run_cycle
from app.agents.mcp_client import McpServerStatus, McpTool
from app.agents.state import RegimeRead
from app.agents.toolbelt import Toolbelt
from app.data.fake import FakePriceSource
from app.data.fundamentals import StaticFundamentalsSource
from app.domain.instrument import Instrument
from app.domain.verdict import Evidence, Stance, Verdict
from app.llm.types import LLMResult, ToolCall
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext
from tests.conftest import authed_client

AS_OF = datetime(2026, 8, 17, tzinfo=UTC)
RELIANCE = Instrument("RELIANCE")


class SilentGateway:
    """No model available — the supported state, not a failure."""

    async def complete(self, *, task, messages, schema=None, tools=None):
        return None


class ToolCallingGateway:
    """Calls one named tool on the first round, then stops."""

    def __init__(self, tool_name: str, arguments: dict | None = None) -> None:
        self.tool_name = tool_name
        self.arguments = arguments or {"symbol": "RELIANCE"}
        self.rounds = 0

    async def complete(self, *, task, messages, schema=None, tools=None):
        self.rounds += 1
        if self.rounds == 1:
            return LLMResult(
                text="",
                model="m",
                provider="p",
                tool_calls=(ToolCall(id="1", name=self.tool_name, arguments=self.arguments),),
            )
        return LLMResult(text="done", model="m", provider="p")


class RelentlessGateway:
    """Never stops asking for tools — the loop must stop it."""

    def __init__(self) -> None:
        self.rounds = 0

    async def complete(self, *, task, messages, schema=None, tools=None):
        self.rounds += 1
        return LLMResult(
            text="",
            model="m",
            provider="p",
            tool_calls=(ToolCall(id="x", name="news_research", arguments={"symbol": "RELIANCE"}),),
        )


@pytest.fixture
def strategy_context() -> StrategyContext:
    return StrategyContext(
        price_source=FakePriceSource(bars=400),
        fundamentals_source=StaticFundamentalsSource({}),
    )


@pytest.fixture
def graph(strategy_context: StrategyContext):
    return build_graph(
        registry=StrategyRegistry.discover(),
        strategy_context=strategy_context,
        price_source=FakePriceSource(bars=400),
        toolbelt=Toolbelt(registry=ToolRegistry.discover()),
        gateway=SilentGateway(),
        max_tool_rounds=0,
    )


def _initial(**overrides) -> dict:
    base = {
        "cycle_id": "test",
        "as_of": AS_OF,
        "instruments": [RELIANCE],
        "narrate": False,
        "verdicts": [],
        "notes": [],
    }
    return {**base, **overrides}


class TestStrategyIsolation:
    """The property the graph dependency exists for."""

    async def test_no_strategy_node_can_see_another_verdict(
        self, strategy_context: StrategyContext
    ) -> None:
        """The additive reducer is the guarantee; assert it rather than trusting the topology.

        Each node records what `verdicts` looked like in the state it was handed. If any node
        saw another's output, isolation is a convention rather than a structure — and that is
        exactly how the predecessor's confluence scorecard began.
        """
        registry = StrategyRegistry.discover()
        observed: dict[str, int] = {}

        real_factory = nodes.make_strategy_node

        def spying_factory(strategy_id, reg, ctx):
            inner = real_factory(strategy_id, reg, ctx)

            async def node(state):
                observed[strategy_id] = len(state.get("verdicts") or [])
                return await inner(state)

            return node

        nodes.make_strategy_node = spying_factory
        try:
            compiled = build_graph(
                registry=registry,
                strategy_context=strategy_context,
                price_source=FakePriceSource(bars=400),
                toolbelt=Toolbelt(registry=ToolRegistry.discover()),
                gateway=SilentGateway(),
                max_tool_rounds=0,
            )
            await run_cycle(compiled, _initial())
        finally:
            nodes.make_strategy_node = real_factory

        assert observed, "no strategy node ran"
        assert set(observed) == set(registry.ids())
        assert all(count == 0 for count in observed.values()), observed

    async def test_every_strategy_still_contributes(self, graph) -> None:
        result = await run_cycle(graph, _initial())

        produced = {v.strategy_id for v in result["verdicts"]}

        assert produced == set(StrategyRegistry.discover().ids())


class TestCycleWithoutAModel:
    """Verdicts are deterministic and reproducible with the LLM off."""

    async def test_all_verdicts_produced_when_no_model_answers(self, graph) -> None:
        result = await run_cycle(graph, _initial())

        assert len(result["verdicts"]) == 4
        assert all(isinstance(v, Verdict) for v in result["verdicts"])

    async def test_narration_absent_leaves_verdicts_intact(self, graph) -> None:
        result = await run_cycle(graph, _initial(narrate=True))

        assert all(v.narrative is None for v in result["verdicts"])

    async def test_cycle_reports_regime_and_notes(self, graph) -> None:
        result = await run_cycle(graph, _initial())

        assert result["regime"] is not None
        assert result["notes"]


class TestResearchIsContextNotEvidence:
    async def test_research_findings_never_enter_evidence(self, graph) -> None:
        result = await run_cycle(graph, _initial())

        for verdict in result["verdicts"]:
            for row in verdict.evidence:
                assert not row.source_ref.startswith("tool://")

    async def test_tool_loop_is_bounded(self) -> None:
        """An agent that calls tools until it feels finished occasionally never finishes."""
        gateway = RelentlessGateway()
        toolbelt = Toolbelt(
            registry=ToolRegistry.discover(),
            context=ToolContext(price_source=FakePriceSource(bars=400)),
        )
        node = nodes.make_research_node(toolbelt, gateway, max_rounds=2)

        await node({"instruments": [RELIANCE]})

        assert gateway.rounds == 2

    async def test_findings_are_recorded_with_their_tool(self) -> None:
        gateway = ToolCallingGateway("peer_compare", {"symbol": "RELIANCE", "peers": ["TCS"]})
        toolbelt = Toolbelt(
            registry=ToolRegistry.discover(),
            context=ToolContext(price_source=FakePriceSource(bars=400)),
        )
        node = nodes.make_research_node(toolbelt, gateway, max_rounds=2)

        update = await node({"instruments": [RELIANCE]})

        findings = update["research"]["RELIANCE"]
        assert findings and findings[0].tool == "peer_compare"
        assert findings[0].source_ref.startswith("tool://")


class TestToolbelt:
    def test_local_tools_are_offered(self) -> None:
        belt = Toolbelt(registry=ToolRegistry.discover())

        assert "news_research" in belt.names()

    async def test_invalid_arguments_refused_by_the_schema(self) -> None:
        """The registry validates before the handler runs, so a bad call fails near its cause."""
        belt = Toolbelt(registry=ToolRegistry.discover())

        ok, text = await belt.invoke("news_research", {"not_a_field": 1})

        assert not ok
        assert "invalid_input" in text

    async def test_unknown_tool_is_a_failure_not_an_exception(self) -> None:
        belt = Toolbelt(registry=ToolRegistry.discover())

        ok, text = await belt.invoke("nope", {})

        assert not ok
        assert "unknown_tool" in text

    async def test_unreachable_mcp_server_degrades_to_local_tools(self) -> None:
        """A broker's server being down must not cost four strategies their run."""
        belt = Toolbelt(
            registry=ToolRegistry.discover(),
            mcp_servers={"kite": "http://127.0.0.1:9/mcp"},
        )

        await belt.connect()

        assert belt.unreachable_servers == ["kite"]
        assert "news_research" in belt.names()

    def test_mcp_tools_are_namespaced(self) -> None:
        """A trace must never leave the origin of a tool ambiguous."""
        tool = McpTool(server="kite", name="get_ltp", description="d", input_schema={})

        assert tool.qualified_name == "kite:get_ltp"
        assert tool.to_tool_definition()["function"]["name"] == "kite:get_ltp"

    def test_mcp_tools_are_not_registered_locally(self) -> None:
        """The registry promises an output schema; someone else's server does not."""
        registry = ToolRegistry.discover()
        belt = Toolbelt(registry=registry, mcp_servers={"kite": "http://127.0.0.1:9/mcp"})
        belt._mcp_tools["kite:get_ltp"] = McpTool("kite", "get_ltp", "d", {})

        assert "kite:get_ltp" in belt.names()
        assert registry.get("kite:get_ltp") is None
        assert "kite:get_ltp" not in registry.names()

    def test_status_is_reported_not_raised(self) -> None:
        status = McpServerStatus(name="kite", url="u", reachable=False, error="boom")

        assert status.as_dict()["reachable"] is False


class TestRegimeNode:
    async def test_regime_is_shared_context_not_a_gate(self, graph) -> None:
        """A hostile regime lowers conviction inside strategies that care; it vetoes nothing."""
        result = await run_cycle(graph, _initial())

        assert isinstance(result["regime"], dict)
        # No verdict was forced to AVOID by the regime alone: gates are per strategy.
        assert any(v.gates_passed for v in result["verdicts"])

    async def test_missing_benchmark_is_unknown_not_an_error(self) -> None:
        class EmptySource:
            def history(self, instrument, *, interval="1d", lookback_days=400):
                from app.domain.prices import empty_series

                return empty_series(instrument, interval)

        node = nodes.make_regime_node(EmptySource())

        update = await node({})

        regime: RegimeRead = update["regime"]
        assert regime.label == "unknown"
        assert regime.trending is False


class TestVerdictShapeUnchanged:
    async def test_cycle_verdicts_match_the_direct_path(self, graph, strategy_context) -> None:
        """A cycle is not a different way to decide — only a different way to run."""
        registry = StrategyRegistry.discover()
        direct = registry.get("minervini").strategy.evaluate(RELIANCE, strategy_context)

        result = await run_cycle(graph, _initial())
        from_cycle = next(v for v in result["verdicts"] if v.strategy_id == "minervini")

        assert from_cycle.stance is direct.stance
        assert from_cycle.conviction == direct.conviction
        assert [e.id for e in from_cycle.evidence] == [e.id for e in direct.evidence]

    def test_no_blending_function_exists_in_the_agents_package(self) -> None:
        """The rule this rebuild exists for, asserted where a cycle could most easily break it."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app" / "agents"
        pattern = re.compile(r"def\s+(combine|aggregate|merge|blend)_?\w*verdict", re.I)
        offenders = [p.name for p in root.rglob("*.py") if pattern.search(p.read_text("utf-8"))]

        assert offenders == []


class TestEvidenceStillTraceable:
    async def test_every_evidence_row_keeps_a_source_ref(self, graph) -> None:
        result = await run_cycle(graph, _initial())

        for verdict in result["verdicts"]:
            assert all(row.source_ref for row in verdict.evidence)

    async def test_stance_still_forced_by_a_failed_gate(self, graph) -> None:
        result = await run_cycle(graph, _initial())

        for verdict in result["verdicts"]:
            if not verdict.gates_passed:
                assert verdict.stance is Stance.AVOID


def test_evidence_type_unchanged_by_this_increment() -> None:
    """Guard: the cycle must not have needed a new evidence shape to work."""
    row = Evidence(id="e", label="l", value=1.0, source_ref="s")

    assert row.source_ref == "s"


class TestCycleApi:
    """The orchestrated path over HTTP, and the agent card."""

    @staticmethod
    def _client(settings):

        from app.main import create_app

        app = create_app(settings)
        app.state.price_source = FakePriceSource(bars=400)
        app.state.fundamentals_source = StaticFundamentalsSource({})
        app.state.gateway = SilentGateway()
        return authed_client(app)

    def test_cycle_returns_one_verdict_per_strategy(self, settings) -> None:
        body = self._client(settings).post(
            "/cycles/run", json={"symbols": ["RELIANCE"], "research": False}
        ).json()

        assert body["count"] == 4
        assert len({v["strategy_id"] for v in body["verdicts"]}) == 4

    def test_cycle_response_carries_no_combined_stance(self, settings) -> None:
        """The rule the rebuild exists for, checked at the surface a reader actually sees."""
        body = self._client(settings).post(
            "/cycles/run", json={"symbols": ["RELIANCE"], "research": False}
        ).json()

        for key in ("stance", "score", "combined", "consensus", "overall"):
            assert key not in body

    def test_cycle_reports_regime_research_and_notes(self, settings) -> None:
        body = self._client(settings).post(
            "/cycles/run", json={"symbols": ["RELIANCE"], "research": False}
        ).json()

        assert "regime" in body
        assert "research" in body
        assert isinstance(body["notes"], list)

    def test_unreachable_mcp_is_reported_not_fatal(self, settings) -> None:
        from app.core.settings import Settings

        configured = Settings(
            app_env="test",
            database_url=settings.database_url,
            mcp_server={"kite": "http://127.0.0.1:9/mcp"},
            _env_file=None,
        )
        response = self._client(configured).post(
            "/cycles/run", json={"symbols": ["RELIANCE"], "research": True}
        )
        body = response.json()

        assert response.status_code == 200
        assert body["count"] == 4
        assert body["mcp"][0]["reachable"] is False

    def test_agent_card_lists_every_registered_tool(self, settings) -> None:
        body = self._client(settings).get("/.well-known/agent-card.json").json()

        names = {s["id"] for s in body["skills"]}
        assert names == set(ToolRegistry.discover().names())

    def test_agent_card_is_honest_about_capabilities(self, settings) -> None:
        """Nothing streams and no task protocol is served; the card must not claim otherwise."""
        body = self._client(settings).get("/.well-known/agent-card.json").json()

        assert body["capabilities"]["streaming"] is False
        assert body["capabilities"]["pushNotifications"] is False


class TestMutatingToolsAreRefused:
    """Principle 7: paper-only, with one explicit execution boundary.

    A research step is not that boundary. Zerodha's hosted server really does advertise
    order placement; that those calls currently fail without a login is an accident of
    authentication, not a design to lean on.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "place_order",
            "cancel_order",
            "modify_order",
            "place_gtt_order",
            "delete_gtt_order",
            "modify_gtt_order",
            "exit_position",
            "convert_position",
        ],
    )
    def test_mutating_tools_are_not_read_only(self, name: str) -> None:
        from app.agents.mcp_client import is_read_only

        assert is_read_only(name) is False

    @pytest.mark.parametrize(
        "name",
        [
            "get_quotes",
            "get_ltp",
            "get_ohlc",
            "get_historical_data",
            "search_instruments",
            "get_holdings",
            "get_positions",
            "get_orders",
            "get_margins",
            "get_profile",
            "get_gtts",
        ],
    )
    def test_read_only_tools_are_allowed(self, name: str) -> None:
        from app.agents.mcp_client import is_read_only

        assert is_read_only(name) is True

    def test_refused_tools_are_reported_not_hidden(self) -> None:
        """A silently shorter tool list looks like a server problem rather than a decision."""
        status = McpServerStatus(
            name="kite", url="u", reachable=True, tool_count=3, refused=("place_order",)
        )

        assert status.as_dict()["refused"] == ["place_order"]


class TestSurfacesDoNotBlendVerdicts:
    """The UI is the layer where a combined score would look most reasonable.

    Fourteen increments kept blending out of the domain. A template computing "3 of 4 agree" or
    an average conviction would reintroduce it where nobody would think to look for it, so the
    surface components are checked directly.
    """

    @staticmethod
    def _strip_comments(source: str) -> str:
        """Remove comments and JSX comment blocks.

        These modules explain at length *why* they do not blend verdicts, using the very words
        a naive grep looks for. Checking code rather than prose is the difference between a
        guard and a tripwire on its own documentation.
        """
        import re

        source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
        return re.sub(r"^\s*//.*$", " ", source, flags=re.MULTILINE)

    @classmethod
    def _web_sources(cls) -> dict[str, str]:
        from pathlib import Path

        web = Path(__file__).resolve().parents[2] / "web"
        if not web.exists():  # pragma: no cover - backend-only checkouts
            return {}
        return {
            p.relative_to(web).as_posix(): cls._strip_comments(p.read_text("utf-8"))
            for p in [*web.glob("app/**/*.tsx"), *web.glob("components/**/*.tsx")]
        }

    def test_no_surface_aggregates_over_verdicts(self) -> None:
        import re

        banned = re.compile(
            r"verdicts\s*\.\s*(reduce|filter\s*\([^)]*BUY[^)]*\)\s*\.\s*length)"
            r"|consensus|averageConviction|agreementScore",
            re.I,
        )
        offenders = [name for name, src in self._web_sources().items() if banned.search(src)]

        assert offenders == [], f"surfaces aggregate across verdicts: {offenders}"

    def test_the_verdict_card_receives_one_verdict(self) -> None:
        """A component handed the whole array is one refactor from a consensus badge."""
        sources = self._web_sources()
        card = sources.get("components/verdict.tsx")
        if card is None:  # pragma: no cover - backend-only checkouts
            pytest.skip("web sources not present")

        # The card's own signature, not everything after it — `VerdictRow` legitimately
        # takes the array in order to lay the cards out.
        signature = card.split("export function VerdictCard")[1].split(")")[0]
        assert "verdict: Verdict" in signature
        assert "Verdict[]" not in signature

    def test_no_surface_sorts_names_by_agreement(self) -> None:
        for name, src in self._web_sources().items():
            assert "sort" not in src or "localeCompare" in src or "cost_basis" in src, name
