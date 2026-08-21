"""The tool registry, its contracts and the seed tools.

Every test runs offline. `peer_compare` exercises the full registry path against
`FakePriceSource`; the other three are driven through injected fetchers replaying recorded
shapes, because their real sources are unreachable from this environment.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.data.fake import FakePriceSource
from app.tools.bindings import to_a2a_skill, to_public_dict, to_tool_definition
from app.tools.evidence import item_schema, items_output_schema
from app.tools.registry import ToolRegistry
from app.tools.types import FailureReason, ToolContext, ToolManifest

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _echo_manifest(**overrides) -> ToolManifest:
    base = {
        "name": "echo",
        "version": "1.0.0",
        "summary": "Echo a value back.",
        "description": "Test tool.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["symbol"],
        },
        "output_schema": items_output_schema(
            item_schema({"value": {"type": "string"}}, required=["value"])
        ),
        "handler": lambda args, ctx: {
            "items": [
                {
                    "source_ref": "test://echo",
                    "observed_at": NOW.isoformat(),
                    "value": args["symbol"],
                }
            ]
        },
    }
    return ToolManifest(**{**base, **overrides})


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry.discover()


class TestManifest:
    def test_declares_its_contract(self) -> None:
        manifest = _echo_manifest()

        assert manifest.name and manifest.version and manifest.summary
        assert manifest.input_schema["type"] == "object"
        assert manifest.output_schema["type"] == "object"

    def test_summary_is_required(self) -> None:
        with pytest.raises(ValueError, match="summary"):
            _echo_manifest(summary="")

    def test_invalid_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="alphanumeric"):
            _echo_manifest(name="not a name!")

    def test_duplicate_registration_rejected(self) -> None:
        """A silent overwrite would make one capability unreachable with no error."""
        reg = ToolRegistry()
        reg.register(_echo_manifest())

        with pytest.raises(ValueError, match="duplicate"):
            reg.register(_echo_manifest())


class TestDiscovery:
    def test_declared_tools_all_load(self, registry: ToolRegistry) -> None:
        """Named explicitly so a tool that vanishes to a typo fails here rather than quietly.

        `commentary` joined the seed four with `research-data-sources`, which is also why this
        is a list and not a count: a count tells you something changed, a list tells you what.
        """
        assert registry.names() == [
            "commentary",
            "concept_extract",
            "event_calendar",
            "filings_scan",
            "news_research",
            "peer_compare",
            "policy_classify",
            "theme_chain",
            "theme_merge",
        ]

    def test_every_summary_says_when_to_use_it(self, registry: ToolRegistry) -> None:
        """The summary is the only signal a model has when choosing among tools.

        Stating what a tool does without stating when to reach for it is the documented way to
        make a tool unselectable. It costs nothing today — nothing picks these yet — and it
        costs a wrong tool call once the agent graph puts these beside ~20 Kite MCP tools that
        are also all about Indian equities.
        """
        for manifest in registry.manifests():
            assert "use when" in manifest.summary.lower(), (
                f"{manifest.name} summary states what it does but not when to use it"
            )

    def test_summaries_are_written_in_third_person(self, registry: ToolRegistry) -> None:
        """Mixed point-of-view in text injected into a prompt causes selection problems."""
        for manifest in registry.manifests():
            opening = manifest.summary.split()[0].lower()
            assert not opening.startswith(("i ", "you", "we")), (
                f"{manifest.name} summary opens in first/second person: {opening!r}"
            )
        assert registry.load_failures == []

    def test_registry_machinery_is_not_registered_as_a_tool(self, registry: ToolRegistry) -> None:
        assert not ({"types", "registry", "bindings", "evidence"} & set(registry.names()))

    def test_import_failure_is_recorded_not_swallowed(self, monkeypatch) -> None:
        """A capability that vanished from a typo must not look like one never written."""
        import importlib

        real = importlib.import_module

        def explode(name, *args, **kwargs):
            if name.endswith("peer_compare.tool"):
                raise ImportError("simulated breakage")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", explode)
        reg = ToolRegistry.discover()

        assert "peer_compare" not in reg.names()
        assert any("peer_compare" in f.module for f in reg.load_failures)
        assert "news_research" in reg.names()  # the rest still load


class TestInputValidation:
    def test_missing_required_argument_blocks_the_handler(self) -> None:
        called = []
        manifest = _echo_manifest(handler=lambda a, c: called.append(1) or {"items": []})
        reg = ToolRegistry({"echo": manifest})

        result = reg.invoke("echo", {})

        assert result.ok is False
        assert result.reason is FailureReason.INVALID_INPUT
        assert called == []

    def test_wrong_type_rejected(self) -> None:
        reg = ToolRegistry({"echo": _echo_manifest()})

        result = reg.invoke("echo", {"symbol": "TCS", "limit": "not-an-int"})

        assert result.reason is FailureReason.INVALID_INPUT

    def test_valid_input_reaches_the_handler(self) -> None:
        reg = ToolRegistry({"echo": _echo_manifest()})

        result = reg.invoke("echo", {"symbol": "TCS"})

        assert result.ok is True
        assert result.items[0]["value"] == "TCS"

    def test_error_message_names_the_offending_field(self) -> None:
        reg = ToolRegistry({"echo": _echo_manifest()})

        result = reg.invoke("echo", {})

        assert "symbol" in (result.error or "")


class TestOutputValidation:
    def test_malformed_output_fails_and_is_not_returned(self) -> None:
        manifest = _echo_manifest(handler=lambda a, c: {"items": [{"value": "x"}]})
        reg = ToolRegistry({"echo": manifest})

        result = reg.invoke("echo", {"symbol": "TCS"})

        assert result.reason is FailureReason.INVALID_OUTPUT
        assert result.data is None

    def test_missing_source_ref_rejected(self) -> None:
        """Traceability cannot be broken later by a tool that simply forgot."""
        manifest = _echo_manifest(
            handler=lambda a, c: {"items": [{"observed_at": NOW.isoformat(), "value": "x"}]}
        )
        reg = ToolRegistry({"echo": manifest})

        result = reg.invoke("echo", {"symbol": "TCS"})

        assert result.reason is FailureReason.INVALID_OUTPUT
        assert "source_ref" in (result.error or "")

    def test_missing_observed_at_rejected(self) -> None:
        manifest = _echo_manifest(
            handler=lambda a, c: {"items": [{"source_ref": "x://y", "value": "x"}]}
        )
        reg = ToolRegistry({"echo": manifest})

        assert reg.invoke("echo", {"symbol": "TCS"}).reason is FailureReason.INVALID_OUTPUT


class TestFailuresNeverRaise:
    def test_handler_exception_becomes_a_result(self) -> None:
        def boom(args, ctx):
            raise RuntimeError("feed exploded")

        reg = ToolRegistry({"echo": _echo_manifest(handler=boom)})

        result = reg.invoke("echo", {"symbol": "TCS"})

        assert result.ok is False
        assert result.reason is FailureReason.HANDLER_ERROR
        assert "feed exploded" in (result.error or "")

    def test_unknown_tool(self) -> None:
        assert ToolRegistry().invoke("nope").reason is FailureReason.UNKNOWN_TOOL

    def test_reasons_are_distinguishable(self) -> None:
        reg = ToolRegistry({"echo": _echo_manifest()})

        reasons = {
            reg.invoke("nope").reason,
            reg.invoke("echo", {}).reason,
            ToolRegistry(
                {"echo": _echo_manifest(handler=lambda a, c: {"items": [{"value": "x"}]})}
            )
            .invoke("echo", {"symbol": "T"})
            .reason,
        }

        assert reasons == {
            FailureReason.UNKNOWN_TOOL,
            FailureReason.INVALID_INPUT,
            FailureReason.INVALID_OUTPUT,
        }

    def test_failed_result_has_no_items(self) -> None:
        assert ToolRegistry().invoke("nope").items == []


class TestBindings:
    def test_tool_definition_uses_the_summary(self, registry: ToolRegistry) -> None:
        manifest = registry.get("peer_compare")
        tool = to_tool_definition(manifest)

        assert tool["function"]["name"] == "peer_compare"
        assert tool["function"]["description"] == manifest.summary
        assert tool["function"]["parameters"] == manifest.input_schema

    def test_a2a_entry_uses_the_description(self, registry: ToolRegistry) -> None:
        manifest = registry.get("peer_compare")
        entry = to_a2a_skill(manifest)

        assert entry["id"] == "peer_compare"
        assert entry["description"] == manifest.description
        assert entry["tags"] == list(manifest.tags)

    def test_bindings_need_no_agent_framework(self) -> None:
        """Both bindings render as plain dicts, independent of any agent framework.

        This asserted the *absence* of langgraph and a2a until `agent-graph-and-a2a`
        installed one, which is a proxy that expires the moment it matters. What was always
        meant is that the renderers do not depend on a framework, so it is now checked where
        that lives — the source — the same way `app/llm` isolation is checked.
        """
        import re
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "tools" / "bindings.py").read_text(
            encoding="utf-8"
        )
        forbidden = re.compile(r"^\s*(import|from)\s+(langgraph|langchain|a2a|mcp)\b", re.MULTILINE)

        assert not forbidden.search(source)
        manifest = _echo_manifest()

        assert to_tool_definition(manifest)["type"] == "function"
        assert to_a2a_skill(manifest)["id"] == "echo"

    def test_public_dict_hides_the_handler(self) -> None:
        public = to_public_dict(_echo_manifest())

        assert "handler" not in public
        assert set(public) == {
            "name",
            "version",
            "summary",
            "description",
            "tags",
            "input_schema",
            "output_schema",
        }


class TestPeerCompare:
    def test_computes_relative_performance_offline(self, registry: ToolRegistry) -> None:
        context = ToolContext(price_source=FakePriceSource(bars=200))

        result = registry.invoke(
            "peer_compare",
            {"symbol": "RELIANCE", "peers": ["TCS", "INFY"], "lookback_days": 60},
            context,
        )

        assert result.ok is True
        assert result.data["subject"] == "RELIANCE"
        assert {i["symbol"] for i in result.items} == {"TCS", "INFY"}
        assert all(i["available"] for i in result.items)
        assert all(i["relative_to_subject_pct"] is not None for i in result.items)

    def test_unavailable_peer_reported_not_dropped(self, registry: ToolRegistry) -> None:
        """A peer silently missing would quietly change what the comparison means."""
        context = ToolContext(price_source=FakePriceSource(known={"RELIANCE", "TCS"}))

        result = registry.invoke(
            "peer_compare", {"symbol": "RELIANCE", "peers": ["TCS", "GONE"]}, context
        )

        by_symbol = {i["symbol"]: i for i in result.items}
        assert by_symbol["GONE"]["available"] is False
        assert by_symbol["GONE"]["return_pct"] is None
        assert by_symbol["TCS"]["available"] is True

    def test_every_item_carries_a_traceable_reference(self, registry: ToolRegistry) -> None:
        result = registry.invoke(
            "peer_compare",
            {"symbol": "RELIANCE", "peers": ["TCS"]},
            ToolContext(price_source=FakePriceSource()),
        )

        assert all(i["source_ref"].startswith("price://") for i in result.items)
        assert all(i["observed_at"] for i in result.items)

    def test_empty_peer_list_rejected_by_schema(self, registry: ToolRegistry) -> None:
        result = registry.invoke("peer_compare", {"symbol": "RELIANCE", "peers": []})

        assert result.reason is FailureReason.INVALID_INPUT

    def test_declares_no_verdict_field(self, registry: ToolRegistry) -> None:
        """Skills measure; strategies decide."""
        schema = str(registry.get("peer_compare").output_schema)

        for banned in ("verdict", "rank", "winner", "score", "rating"):
            assert banned not in schema


class FakeEntry:
    def __init__(self, title, link, summary="", published=None):
        self.title = title
        self.link = link
        self.summary = summary
        if published:
            self.published_parsed = published.timetuple()


class FakeFeed:
    def __init__(self, entries):
        self.entries = entries


class TestNewsResearch:
    def _parser(self, entries, fail_for: set[str] | None = None):
        def parse(url: str):
            if fail_for and any(f in url for f in fail_for):
                raise RuntimeError("feed down")
            return FakeFeed(entries)

        return parse

    def test_matches_on_a_company_name_alias(self, registry: ToolRegistry) -> None:
        """Headlines say 'Infosys', never 'INFY' — the alias map is what makes this work."""
        entries = [
            FakeEntry("Infosys wins large deal in Europe", "https://x.test/1", published=NOW)
        ]
        context = ToolContext(now=lambda: NOW, fetchers={"feed_parser": self._parser(entries)})

        result = registry.invoke("news_research", {"symbol": "INFY"}, context)

        assert result.ok is True
        assert result.items
        assert result.items[0]["matched_on"] == "INFOSYS"
        assert result.items[0]["source_ref"] == "https://x.test/1"

    def test_unrelated_article_not_matched(self, registry: ToolRegistry) -> None:
        entries = [FakeEntry("Steel prices rise", "https://x.test/2", published=NOW)]
        context = ToolContext(now=lambda: NOW, fetchers={"feed_parser": self._parser(entries)})

        result = registry.invoke("news_research", {"symbol": "INFY"}, context)

        assert result.items == []

    def test_articles_older_than_the_window_excluded(self, registry: ToolRegistry) -> None:
        old = NOW - timedelta(days=30)
        entries = [FakeEntry("Infosys results", "https://x.test/3", published=old)]
        context = ToolContext(now=lambda: NOW, fetchers={"feed_parser": self._parser(entries)})

        result = registry.invoke("news_research", {"symbol": "INFY", "hours": 24}, context)

        assert result.items == []

    def test_a_failing_feed_degrades_coverage_not_the_call(self, registry: ToolRegistry) -> None:
        entries = [FakeEntry("Infosys deal", "https://x.test/4", published=NOW)]
        context = ToolContext(
            now=lambda: NOW,
            fetchers={"feed_parser": self._parser(entries, fail_for={"moneycontrol"})},
        )

        result = registry.invoke("news_research", {"symbol": "INFY"}, context)

        assert result.ok is True
        assert result.data["feeds_failed"]
        assert result.data["feeds_read"] > 0

    def test_limit_respected(self, registry: ToolRegistry) -> None:
        entries = [
            FakeEntry(f"Infosys item {i}", f"https://x.test/{i}", published=NOW) for i in range(10)
        ]
        context = ToolContext(now=lambda: NOW, fetchers={"feed_parser": self._parser(entries)})

        result = registry.invoke("news_research", {"symbol": "INFY", "limit": 3}, context)

        assert len(result.items) == 3

    def test_longer_alias_wins_over_a_shorter_one(self) -> None:
        """'HDFC BANK' must beat 'HDFC', or bank stories land on the wrong instrument."""
        from app.tools.news_research.tool import match_terms

        terms = match_terms("HDFCBANK")

        assert terms == tuple(sorted(terms, key=len, reverse=True))

    def test_declares_no_sentiment_field(self, registry: ToolRegistry) -> None:
        schema = str(registry.get("news_research").output_schema)

        for banned in ("sentiment", "score", "rating", "bullish"):
            assert banned not in schema


class TestEventCalendarAndFilings:
    def test_event_calendar_reports_unreachable_source(self, registry: ToolRegistry) -> None:
        """'No events scheduled' must be distinguishable from 'could not ask'."""

        def explode(ticker: str):
            raise RuntimeError("blocked")

        context = ToolContext(now=lambda: NOW, fetchers={"calendar_lookup": explode})

        result = registry.invoke("event_calendar", {"symbol": "RELIANCE"}, context)

        assert result.ok is True
        assert result.data["source_available"] is False
        assert result.items == []

    def test_event_calendar_returns_events_within_horizon(self, registry: ToolRegistry) -> None:
        soon = (NOW + timedelta(days=10)).date()
        far = (NOW + timedelta(days=200)).date()
        context = ToolContext(
            now=lambda: NOW,
            fetchers={"calendar_lookup": lambda t: {"Earnings Date": [soon, far]}},
        )

        result = registry.invoke(
            "event_calendar", {"symbol": "RELIANCE", "horizon_days": 45}, context
        )

        assert len(result.items) == 1
        assert result.items[0]["event_type"] == "earnings"
        assert result.items[0]["days_away"] == 10

    def test_filings_scan_prefers_the_attachment_as_source(self, registry: ToolRegistry) -> None:
        """A filing is the thing itself; a news summary is somebody's account of it."""
        rows = [
            {
                "desc": "Board Meeting Intimation",
                "an_dt": "14-Aug-2026 10:00:00",
                "attchmntFile": "https://nse.test/filing.pdf",
            }
        ]
        context = ToolContext(now=lambda: NOW, fetchers={"announcements_fetcher": lambda s: rows})

        result = registry.invoke("filings_scan", {"symbol": "RELIANCE"}, context)

        assert result.ok is True
        assert result.items[0]["source_ref"] == "https://nse.test/filing.pdf"
        assert result.items[0]["subject"] == "Board Meeting Intimation"

    def test_filings_scan_reports_unreachable_source(self, registry: ToolRegistry) -> None:
        def explode(symbol: str):
            raise RuntimeError("403")

        context = ToolContext(now=lambda: NOW, fetchers={"announcements_fetcher": explode})

        result = registry.invoke("filings_scan", {"symbol": "RELIANCE"}, context)

        assert result.ok is True
        assert result.data["source_available"] is False


class TestOfflineImports:
    def test_no_tool_imports_a_network_client_at_module_scope(self) -> None:
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app" / "tools"
        offenders = []
        for path in root.rglob("*.py"):
            for node in ast.parse(path.read_text()).body:
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                if {"yfinance", "requests", "feedparser"} & set(names):
                    offenders.append(f"{path.parent.name}/{path.name}")

        assert offenders == []

    def test_discovery_is_fast_enough_to_do_at_startup(self) -> None:
        started = time.monotonic()
        ToolRegistry.discover()

        assert time.monotonic() - started < 2.0
