"""Theme detection: the counted half.

Nothing here calls a model, and that is the point of the module under test. Breadth and
persistence are arithmetic over documents, so the same references produce the same themes
forever — which is what makes "fourteen companies across three sectors for three quarters" a
claim that can be checked rather than a fluent answer.

The load-bearing tests are the threshold ones and the reproducibility one. Everything else in
`theme-engine` is allowed to be a proposal; this part has to be a measurement.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.core.scheduler import Scheduler, is_reloader_supervisor
from app.data.protocols import UniverseSnapshot
from app.domain.instrument import Instrument
from app.domain.themes import (
    Candidate,
    Exposure,
    Reference,
    SourceKind,
    Theme,
    ThemeEvidence,
)
from app.themes.detect import Thresholds, assemble
from app.themes.exposure import grade, grade_many
from app.themes.extraction import ConceptStore
from app.themes.resolve import (
    match_description,
    resolve_chain,
    resolve_tier,
    terms,
)
from app.themes.runner import Gathered, ThemeRunner
from app.themes.sources import policy_references, read_documents
from app.themes.store import ThemeStore
from app.tools.registry import ToolRegistry
from app.tools.theme_chain.tool import handle
from app.tools.types import ToolContext


def _ref(
    symbol: str,
    concept: str = "data_centre",
    period: str = "Jun 2026",
    sector: str | None = "Infrastructure",
    kind: SourceKind = SourceKind.COMMENTARY,
) -> Reference:
    return Reference(
        symbol=symbol,
        concept=concept,
        period=period,
        kind=kind,
        source_ref=f"doc://{symbol}/{period}",
        sector=sector,
    )


class TestCounting:
    def test_breadth_counts_companies_not_mentions(self) -> None:
        """A voluble management team must not be able to manufacture a theme alone."""
        evidence = ThemeEvidence(
            references=(_ref("ABB"), _ref("ABB", period="Mar 2026"), _ref("SIEMENS"))
        )

        assert evidence.breadth == 2

    def test_persistence_counts_distinct_periods(self) -> None:
        evidence = ThemeEvidence(
            references=(_ref("ABB"), _ref("SIEMENS"), _ref("ABB", period="Mar 2026"))
        )

        assert evidence.persistence == 2

    def test_periods_are_ordered_oldest_first_by_parsed_end(self) -> None:
        evidence = ThemeEvidence(
            references=(
                Reference(
                    "A", "t", "Jun 2026", SourceKind.COMMENTARY, "s",
                    period_end=date(2026, 6, 30),
                ),
                Reference(
                    "B", "t", "Mar 2026", SourceKind.COMMENTARY, "s",
                    period_end=date(2026, 3, 31),
                ),
            )
        )

        assert evidence.periods == ("Mar 2026", "Jun 2026")

    def test_sectors_ignore_unknowns(self) -> None:
        evidence = ThemeEvidence(references=(_ref("A"), _ref("B", sector=None)))

        assert evidence.sectors == frozenset({"Infrastructure"})

    def test_source_kinds_are_reported(self) -> None:
        evidence = ThemeEvidence(
            references=(_ref("A"), _ref("B", kind=SourceKind.POLICY))
        )

        assert evidence.source_kinds == {SourceKind.COMMENTARY, SourceKind.POLICY}


class TestThresholds:
    def test_one_loud_company_is_not_a_theme(self) -> None:
        surfaced, short = assemble(
            [_ref("ABB"), _ref("ABB", period="Mar 2026"), _ref("ABB", period="Dec 2025")]
        )

        assert surfaced == []
        assert [t.key for t in short] == ["data_centre"]

    def test_one_loud_period_is_not_a_theme(self) -> None:
        """Every company commenting on one budget announcement is a news cycle."""
        surfaced, short = assemble([_ref("A"), _ref("B"), _ref("C"), _ref("D")])

        assert surfaced == []
        assert len(short) == 1

    def test_breadth_and_persistence_together_surface_a_theme(self) -> None:
        surfaced, _ = assemble(
            [
                _ref("A"),
                _ref("B"),
                _ref("C"),
                _ref("A", period="Mar 2026"),
            ]
        )

        assert [t.key for t in surfaced] == ["data_centre"]

    def test_thresholds_are_configurable(self) -> None:
        references = [_ref("A"), _ref("B"), _ref("A", period="Mar 2026")]

        surfaced, _ = assemble(references, thresholds=Thresholds(min_companies=2))

        assert len(surfaced) == 1

    def test_a_shortfall_says_what_is_missing(self) -> None:
        evidence = ThemeEvidence(references=(_ref("A"),))

        reason = Thresholds().shortfall(evidence)

        assert "1 companies, needs 3" in reason
        assert "1 period(s), needs 2" in reason

    def test_below_threshold_themes_are_returned_not_discarded(self) -> None:
        """Withdrawal decides from these. "Faded" and "never looked" are different facts."""
        _, short = assemble([_ref("A")])

        assert len(short) == 1
        assert short[0].evidence.breadth == 1


class TestReproducibility:
    def _references(self) -> list[Reference]:
        return [
            _ref("C"),
            _ref("A"),
            _ref("B", concept="railways", sector="Metal"),
            _ref("A", period="Mar 2026"),
            _ref("B"),
            _ref("A", concept="railways", period="Mar 2026", sector="Metal"),
            _ref("C", concept="railways", sector="Auto"),
        ]

    def test_the_same_references_produce_the_same_themes(self) -> None:
        first, _ = assemble(self._references())
        second, _ = assemble(self._references())

        assert [t.key for t in first] == [t.key for t in second]

    def test_input_order_does_not_change_output_order(self) -> None:
        forward, _ = assemble(self._references())
        backward, _ = assemble(list(reversed(self._references())))

        assert [t.key for t in forward] == [t.key for t in backward]

    def test_counts_are_identical_across_runs(self) -> None:
        first, _ = assemble(self._references())
        second, _ = assemble(self._references())

        assert [t.evidence.breadth for t in first] == [t.evidence.breadth for t in second]


class TestStoredExtraction:
    """Reading is a model call; counting is arithmetic over what it wrote down.

    That split is what lets an open vocabulary coexist with thresholds. A model answers
    differently every time it is asked, so counts recomputed from fresh readings would drift
    and a threshold over drifting numbers means nothing. The reading is persisted; the counting
    reads rows.
    """

    @pytest.fixture
    def store(self, session_factory) -> ConceptStore:
        return ConceptStore(session_factory)

    def _concept(self, symbol: str, label: str, period: str = "Jun 2026", **extra) -> dict:
        return {
            "symbol": symbol,
            "period": period,
            "label": label,
            "excerpt": f"{symbol} said something about {label}",
            "source_ref": extra.get("source_ref", f"doc://{symbol}/{period}"),
            "extracted_by": "ollama/test",
            # A theme crosses sectors, so the default thresholds require at least one known
            # sector. A reading with none is a real state, just not one that surfaces.
            "sector": extra.get("sector", "Capital Goods"),
            **{k: v for k, v in extra.items() if k != "source_ref"},
        }

    def test_a_reading_is_stored_and_read_back(self, store: ConceptStore) -> None:
        store.record([self._concept("ABB", "data centre demand")])

        [reference] = store.references()
        assert reference.symbol == "ABB"
        assert reference.concept == "data centre demand"

    def test_a_document_is_only_read_once(self, store: ConceptStore) -> None:
        """The check that keeps a weekly run affordable and the counts still."""
        assert store.has_read("doc://ABB/Jun 2026") is False

        store.record([self._concept("ABB", "data centre demand")])

        assert store.has_read("doc://ABB/Jun 2026") is True

    def test_re_recording_the_same_reading_does_not_double_breadth(
        self, store: ConceptStore
    ) -> None:
        store.record([self._concept("ABB", "data centre demand")])
        store.record([self._concept("ABB", "data centre demand")])

        assert len(store.references()) == 1

    def test_labels_are_free_form(self, store: ConceptStore) -> None:
        """No list anywhere. Whatever the company said is what is stored."""
        store.record(
            [
                self._concept("ABB", "pent-up technology backlog"),
                self._concept("TCS", "ai-led transformation"),
            ]
        )

        assert set(store.labels()) == {"pent-up technology backlog", "ai-led transformation"}

    def test_an_unplaced_concept_stands_as_its_own_theme(self, store: ConceptStore) -> None:
        """Dropping unplaced concepts would make a merge failure look like a quiet market."""
        store.record([self._concept("ABB", "hyperscaler capex")])

        [reference] = store.references()
        assert reference.concept == "hyperscaler capex"

    def test_a_placement_renames_the_concept_to_its_theme(self, store: ConceptStore) -> None:
        store.record([self._concept("ABB", "hyperscaler capex")])
        store.place(
            [
                {
                    "concept": "hyperscaler capex",
                    "theme": "data centre buildout",
                    "reasoning": "same underlying development",
                    "decided_by": "ollama/test",
                }
            ]
        )

        [reference] = store.references()
        assert reference.concept == "data centre buildout"

    def test_placing_two_wordings_on_one_theme_builds_breadth(
        self, store: ConceptStore
    ) -> None:
        """The crux. Unmerged, each wording has a breadth of one and nothing ever surfaces."""
        store.record(
            [
                self._concept("ABB", "hyperscaler capex"),
                self._concept("SIEMENS", "data centre demand"),
                self._concept(
                    "ABB", "ai infrastructure buildout", period="Mar 2026",
                    source_ref="doc://ABB/Mar 2026",
                ),
            ]
        )
        store.place(
            [
                {"concept": "hyperscaler capex", "theme": "data centre buildout"},
                {"concept": "data centre demand", "theme": "data centre buildout"},
                {"concept": "ai infrastructure buildout", "theme": "data centre buildout"},
            ]
        )

        surfaced, _ = assemble(store.references(), thresholds=Thresholds(min_companies=2))

        assert [t.key for t in surfaced] == ["data centre buildout"]
        assert surfaced[0].evidence.breadth == 2
        assert surfaced[0].evidence.persistence == 2

    def test_unmerged_wordings_surface_nothing(self) -> None:
        """Why merging is the crux rather than a tidying step.

        The same three readings, unplaced: three themes of one company each, and the
        thresholds correctly reject every one. Open-vocabulary extraction without merging is
        strictly worse than the fixed list it replaced.
        """
        references = [
            Reference("ABB", "hyperscaler capex", "Jun 2026", SourceKind.COMMENTARY, "d1"),
            Reference("SIEMENS", "data centre demand", "Jun 2026", SourceKind.COMMENTARY, "d2"),
            Reference("ABB", "ai infrastructure buildout", "Mar 2026", SourceKind.COMMENTARY, "d3"),
        ]

        surfaced, short = assemble(references, thresholds=Thresholds(min_companies=2))

        assert surfaced == []
        assert len(short) == 3

    def test_a_rejected_placement_is_not_reinstated(self, store: ConceptStore) -> None:
        store.record([self._concept("ABB", "hyperscaler capex")])
        store.place([{"concept": "hyperscaler capex", "theme": "data centre buildout"}])
        assert store.reject_placement("hyperscaler capex") is True

        written, skipped = store.place(
            [{"concept": "hyperscaler capex", "theme": "data centre buildout"}]
        )

        assert (written, skipped) == (0, 1)
        assert store.references()[0].concept == "hyperscaler capex"

    def test_rejecting_an_unknown_placement_is_false(self, store: ConceptStore) -> None:
        assert store.reject_placement("never heard of it") is False

    def test_counts_are_identical_across_reads(self, store: ConceptStore) -> None:
        """Stored readings mean the same corpus always yields the same numbers."""
        store.record(
            [
                self._concept("ABB", "data centre demand"),
                self._concept("SIEMENS", "data centre demand"),
                self._concept("ABB", "data centre demand", period="Mar 2026"),
            ]
        )

        first, _ = assemble(store.references(), thresholds=Thresholds(min_companies=2))
        second, _ = assemble(store.references(), thresholds=Thresholds(min_companies=2))

        assert [t.evidence.breadth for t in first] == [t.evidence.breadth for t in second]


class TestNoHardcodedVocabularyRemains:
    """The defect this replaced: deciding what a document is about from a list of phrases."""

    def test_detection_holds_no_concept_table(self) -> None:
        from tests.conftest import source_of

        source = source_of("themes")
        assert "CONCEPTS" not in source
        assert "_POLICY_MARKERS" not in source

    def test_detection_calls_no_model_either(self) -> None:
        """Reading moved to a tool. Counting stayed arithmetic, which is why it is checkable."""
        from tests.conftest import source_of

        detect = (
            __import__("pathlib").Path("app/themes/detect.py").read_text("utf-8")
        )
        assert "gateway" not in detect
        assert "prompt" not in detect.lower()
        assert source_of("themes")


class TestNothingHereRanksOrScores:
    """A theme may widen attention and may never narrow it."""

    def test_a_theme_carries_no_stance_or_conviction(self) -> None:
        fields = set(Theme.__dataclass_fields__)

        assert not fields & {"stance", "conviction", "score", "rank", "strength"}

    def test_exposure_is_a_category_not_a_number(self) -> None:
        for level in Exposure:
            assert isinstance(level.value, str)
            with pytest.raises((TypeError, ValueError)):
                float(level.value)

    def test_the_module_has_no_ranking_function(self) -> None:
        import re

        from tests.conftest import source_of

        source = source_of("themes")
        # Word boundaries, not substrings: `isinstance` contains "stance", and a test that
        # fails on it is a test nobody will trust the next time it goes red.
        for forbidden in ("rank", "score", "conviction", "stance", "rating"):
            assert not re.search(rf"{forbidden}", source), forbidden

    def test_ordering_never_decides_membership(self) -> None:
        """Order is presentation. Which themes surface must not depend on it at all.

        The real property behind "this is not a ranking": if ordering were meaningful, some
        consumer would eventually take the top N, and the sort would have quietly become a
        selection. Membership is decided by the thresholds and by nothing else.
        """
        references = [
            _ref("A"), _ref("B"), _ref("C"), _ref("A", period="Mar 2026"),
            _ref("D", concept="railways", sector="Metal"),
            _ref("E", concept="railways", sector="Auto"),
            _ref("F", concept="railways", sector="Metal"),
            _ref("D", concept="railways", period="Mar 2026", sector="Metal"),
        ]

        forward, _ = assemble(references)
        backward, _ = assemble(list(reversed(references)))

        assert {t.key for t in forward} == {t.key for t in backward}

    def test_a_theme_exposes_no_numeric_strength(self) -> None:
        surfaced, _ = assemble([_ref("A"), _ref("B"), _ref("C"), _ref("A", period="Mar 2026")])
        published = surfaced[0].as_dict()

        # Counts are published because the counts *are* the claim. Anything that reads as a
        # strength or a rating is not.
        forbidden = {"score", "strength", "rank", "rating", "conviction"}
        assert set(published) & forbidden == set()


class TestTheStore:
    """Runs, themes and the withdrawal rule.

    The rule was learned in `feed-freshness-and-run-control` and is more dangerous here. A
    stale insight is visibly stale; a theme withdrawn because a scrape failed simply
    disappears, and the reader cannot tell a quiet market from a broken downloader.
    """

    @pytest.fixture
    def store(self, session_factory) -> ThemeStore:
        return ThemeStore(session_factory)

    def _theme(self, key: str = "data_centre", companies: int = 3, periods: int = 2) -> Theme:
        references = []
        for company in range(companies):
            for period in range(periods):
                references.append(
                    _ref(f"CO{company}", concept=key, period=f"P{period}")
                )
        return Theme(key=key, label=key, evidence=ThemeEvidence(references=tuple(references)))

    # ── runs ──────────────────────────────────────────────────────────────────
    def test_a_run_is_recorded_and_finished(self, store: ThemeStore) -> None:
        run_id = store.start_run()
        store.finish_run(run_id, "complete", documents_read=12)

        [run] = store.runs()
        assert run["outcome"] == "complete"
        assert run["documents_read"] == 12
        assert run["finished_at"] is not None

    def test_a_running_run_is_visible_so_a_second_can_be_refused(
        self, store: ThemeStore
    ) -> None:
        run_id = store.start_run()

        assert store.running_run() == run_id

        store.finish_run(run_id, "complete")
        assert store.running_run() is None

    def test_unavailable_sources_are_recorded_on_the_run(self, store: ThemeStore) -> None:
        """A quiet failure must not look like a quiet market."""
        run_id = store.start_run()
        store.finish_run(run_id, "complete", sources_unavailable=("commentary",))

        assert store.runs()[0]["sources_unavailable"] == ["commentary"]

    def test_a_run_that_read_nothing_is_marked_as_such(self, store: ThemeStore) -> None:
        run_id = store.start_run()
        store.finish_run(run_id, "no_reading", sources_unavailable=("commentary", "policy"))

        assert store.runs()[0]["outcome"] == "no_reading"

    def test_runs_are_newest_first(self, store: ThemeStore) -> None:
        first = store.start_run()
        store.finish_run(first, "complete")
        second = store.start_run()
        store.finish_run(second, "complete")

        assert [r["id"] for r in store.runs()] == [second, first]

    # ── recording ─────────────────────────────────────────────────────────────
    def test_a_theme_is_written_with_its_counts(self, store: ThemeStore) -> None:
        new, refreshed = store.record([self._theme()])

        [theme] = store.standing()
        assert (new, refreshed) == (1, 0)
        assert theme["breadth"] == 3
        assert theme["persistence"] == 2

    def test_counts_are_stored_not_recomputed(self, store: ThemeStore) -> None:
        """The counts are the claim, so they must be the figures the run measured."""
        store.record([self._theme()])
        stored = store.standing()[0]

        assert stored["breadth"] == 3
        assert stored["source_kinds"] == ["commentary"]

    def test_re_recording_the_same_theme_does_not_duplicate_it(
        self, store: ThemeStore
    ) -> None:
        store.record([self._theme()])
        new, _ = store.record([self._theme()])

        assert new == 0
        assert len(store.standing()) == 1

    def test_moved_counts_refresh_in_place_and_keep_first_seen(
        self, store: ThemeStore
    ) -> None:
        store.record([self._theme(companies=3)])
        first_seen = store.standing()[0]["first_seen_at"]

        _, refreshed = store.record([self._theme(companies=5)])

        stored = store.standing()[0]
        assert refreshed == 1
        assert stored["breadth"] == 5
        assert stored["first_seen_at"] == first_seen

    def test_unchanged_counts_are_not_reported_as_refreshed(
        self, store: ThemeStore
    ) -> None:
        store.record([self._theme()])
        _, refreshed = store.record([self._theme()])

        assert refreshed == 0

    def test_references_are_stored_and_traceable(self, store: ThemeStore) -> None:
        store.record([self._theme()])

        references = store.references("data_centre")
        assert len(references) == 6
        assert all(r.source_ref for r in references)

    def test_the_same_reference_twice_is_stored_once(self, store: ThemeStore) -> None:
        """Re-reading a document must not inflate breadth."""
        store.record([self._theme()])
        store.record([self._theme()])

        assert len(store.references("data_centre")) == 6

    # ── withdrawal ────────────────────────────────────────────────────────────
    def test_a_faded_theme_is_withdrawn_with_its_reason(self, store: ThemeStore) -> None:
        store.record([self._theme()])
        thin = self._theme(companies=1, periods=1)

        withdrawn = store.withdraw_short([thin], Thresholds().shortfall)

        assert withdrawn == 1
        assert store.standing() == []
        [row] = store.standing(include_withdrawn=True)
        assert "needs 3" in row["withdrawal_reason"]

    def test_withdrawal_keeps_the_first_seen_date(self, store: ThemeStore) -> None:
        store.record([self._theme()])
        first_seen = store.standing()[0]["first_seen_at"]

        store.withdraw_short([self._theme(companies=1)], Thresholds().shortfall)

        assert store.standing(include_withdrawn=True)[0]["first_seen_at"] == first_seen

    def test_an_unassessed_theme_is_never_withdrawn(self, store: ThemeStore) -> None:
        """The rule that matters. A theme its sources could not reach is left standing."""
        store.record([self._theme("data_centre"), self._theme("railways")])

        # This run only assessed railways, and found it short.
        store.withdraw_short(
            [self._theme("railways", companies=1)], Thresholds().shortfall
        )

        assert [t["key"] for t in store.standing()] == ["data_centre"]

    def test_a_run_that_assessed_nothing_withdraws_nothing(self, store: ThemeStore) -> None:
        store.record([self._theme()])

        assert store.withdraw_short([], Thresholds().shortfall) == 0
        assert len(store.standing()) == 1

    def test_a_theme_that_returns_stands_again_keeping_its_history(
        self, store: ThemeStore
    ) -> None:
        store.record([self._theme()])
        first_seen = store.standing()[0]["first_seen_at"]
        store.withdraw_short([self._theme(companies=1)], Thresholds().shortfall)

        store.record([self._theme()])

        [row] = store.standing()
        assert row["withdrawn_at"] is None
        assert row["first_seen_at"] == first_seen

    def test_withdrawn_themes_are_excluded_by_default(self, store: ThemeStore) -> None:
        store.record([self._theme()])
        store.withdraw_short([self._theme(companies=1)], Thresholds().shortfall)

        assert store.standing() == []
        assert len(store.standing(include_withdrawn=True)) == 1

    def test_a_stored_theme_round_trips_with_its_references(self, store: ThemeStore) -> None:
        store.record([self._theme()])

        loaded = store.load("data_centre")

        assert loaded is not None
        assert loaded.evidence.breadth == 3
        assert loaded.evidence.persistence == 2

    def test_loading_an_unknown_theme_is_none(self, store: ThemeStore) -> None:
        assert store.load("nope") is None


class TestChainExpansion:
    """The one place a model influences what the platform looks at.

    Offline. The expander is injected, so no test here calls a model — what is under test is
    the contract around the model, which is the part that makes its output safe to act on:
    schema-validated, attributed, rejectable, and never a measurement.
    """

    def _expander(self, payload: str, model: str = "ollama/test"):
        def expand(prompt: str, task: str, schema=None):
            return payload, model

        return ToolContext(fetchers={"chain_expander": expand})

    def _good(self) -> str:
        return json.dumps(
            {
                "tiers": [
                    {
                        "label": "Data centre buildout",
                        "supplies": None,
                        "reasoning": "The activity itself.",
                        "supplier_descriptions": ["Colocation operators"],
                    },
                    {
                        "label": "Grid and power equipment",
                        "supplies": "Data centre buildout",
                        "reasoning": "Data centres draw continuous high load.",
                        "supplier_descriptions": [
                            "Transformer manufacturers",
                            "Switchgear manufacturers",
                            "Power cable manufacturers",
                        ],
                    },
                ]
            }
        )

    def test_tiers_are_returned_in_dependency_order(self) -> None:
        result = handle({"theme": "data centre"}, self._expander(self._good()))

        assert [i["tier"] for i in result["items"]] == [1, 2]
        assert result["items"][0]["supplies"] is None
        assert result["items"][1]["supplies"] == "Data centre buildout"

    def test_every_tier_carries_reasoning_and_its_model(self) -> None:
        result = handle({"theme": "data centre"}, self._expander(self._good()))

        for item in result["items"]:
            assert item["reasoning"]
            assert item["proposed_by"] == "ollama/test"

    def test_a_tier_without_reasoning_is_dropped(self) -> None:
        """A claim a reader cannot judge is a claim this platform will not show."""
        payload = json.dumps(
            {"tiers": [{"label": "Mystery tier", "supplies": None, "reasoning": ""}]}
        )

        result = handle({"theme": "x"}, self._expander(payload))

        assert result["items"] == []
        assert result["available"] is False

    def test_supplier_descriptions_are_categories(self) -> None:
        result = handle({"theme": "data centre"}, self._expander(self._good()))
        power = result["items"][1]

        assert "Transformer manufacturers" in power["supplier_descriptions"]

    def test_the_chain_is_bounded(self) -> None:
        payload = json.dumps(
            {
                "tiers": [
                    {"label": f"Tier {i}", "supplies": None, "reasoning": "because"}
                    for i in range(10)
                ]
            }
        )

        result = handle({"theme": "x", "max_tiers": 2}, self._expander(payload))

        assert len(result["items"]) == 2

    # ── failure is never a partial chain ──────────────────────────────────────
    def test_unparseable_output_produces_no_chain(self) -> None:
        """Half a chain looks complete and would omit the tier a reader most needed."""
        result = handle({"theme": "x"}, self._expander("I think probably transformers?"))

        assert result["items"] == []
        assert result["available"] is False
        assert "not a usable chain" in result["reason"]

    def test_a_fenced_json_block_is_still_read(self) -> None:
        result = handle({"theme": "x"}, self._expander(f"```json\n{self._good()}\n```"))

        assert result["available"] is True

    def test_a_failing_model_is_reported_not_raised(self) -> None:
        def boom(prompt: str, task: str, schema=None):
            raise RuntimeError("model unavailable")

        result = handle({"theme": "x"}, ToolContext(fetchers={"chain_expander": boom}))

        assert result["available"] is False
        assert "expansion failed" in result["reason"]

    def test_no_model_configured_is_an_ordinary_empty_result(self) -> None:
        result = handle({"theme": "x"}, ToolContext())

        assert result["available"] is False
        assert result["items"] == []

    def test_output_satisfies_the_declared_schema(self) -> None:
        registry = ToolRegistry.discover()

        result = registry.invoke(
            "theme_chain", {"theme": "data centre"}, self._expander(self._good())
        )

        assert result.ok, result.error
        assert len(result.items) == 2

    def test_the_tool_is_registered(self) -> None:
        assert ToolRegistry.discover().get("theme_chain") is not None


class TestExpansionIsAProposalNotAMeasurement:
    """A theme may widen attention and may never narrow it."""

    def _result(self):
        payload = json.dumps(
            {
                "tiers": [
                    {
                        "label": "Grid and power equipment",
                        "supplies": "Data centre buildout",
                        "reasoning": "Data centres draw continuous high load.",
                        "supplier_descriptions": ["Transformer manufacturers"],
                    }
                ]
            }
        )

        def expand(prompt: str, task: str, schema=None):
            return payload, "ollama/test"

        return handle({"theme": "data centre"}, ToolContext(fetchers={"chain_expander": expand}))

    def test_every_tier_declares_it_was_not_measured_here(self) -> None:
        assert self._result()["items"][0]["measured_by_platform"] is False

    def test_a_tier_is_traceable_to_the_model_that_proposed_it(self) -> None:
        assert self._result()["items"][0]["source_ref"].startswith("model://")

    def test_no_tier_carries_a_stance_or_a_score(self) -> None:
        item = self._result()["items"][0]

        assert not set(item) & {"stance", "conviction", "score", "rank", "rating"}

    def test_the_prompt_asks_for_categories_never_companies(self) -> None:
        from app.tools.theme_chain.tool import PROMPT

        assert "never named companies" in PROMPT
        assert "never stock tickers" in PROMPT

    def test_the_prompt_forbids_investment_judgement(self) -> None:
        """World knowledge is what this model call is for. Opinion is what it is not for."""
        from app.tools.theme_chain.tool import PROMPT

        assert "not making an investment recommendation" in PROMPT
        assert "whether anything is a good investment" in PROMPT

    def test_no_strategy_reads_a_chain(self) -> None:
        from tests.conftest import source_of

        strategies = source_of("strategies")
        assert "theme_chain" not in strategies
        assert "ChainLink" not in strategies


def _universe(*rows: tuple[str, str, str]) -> UniverseSnapshot:
    return UniverseSnapshot(
        instruments=tuple(
            Instrument(symbol=s, name=n, sector=sec) for s, n, sec in rows
        ),
        origin="live",
        index_name="TEST",
    )


def _profiles(**descriptions) -> dict:
    from app.data.profiles import CompanyProfile

    return {
        symbol: CompanyProfile(symbol=symbol, description=text, industry=industry, source="test")
        for symbol, (text, industry) in descriptions.items()
    }


#: What these companies do, in the prose a provider supplies. Deliberately never mentioning a
#: company's own name -- matching on a name is the defect this corpus exists to prove fixed.
PROFILES = _profiles(
    TARIL=(
        "designs and manufactures power transformers, rectifiers and traction "
        "transformers for utilities and industry",
        "Electrical Equipment & Parts",
    ),
    FINCABLES=(
        "manufactures electrical cables, wires and communication cables for "
        "industrial and household use",
        "Electrical Equipment & Parts",
    ),
    ACMESOLAR=(
        "develops and operates solar power generation projects and renewable energy assets",
        "Solar",
    ),
    ADANIPOWER=(
        "generates and supplies thermal electricity to distribution utilities",
        "Utilities - Independent Power Producers",
    ),
    NTPC=(
        "generates electricity from coal, gas, hydro and renewable sources for bulk supply",
        "Utilities - Independent Power Producers",
    ),
    TATAPOWER=(
        "generates, transmits and distributes electricity across India",
        "Utilities - Independent Power Producers",
    ),
    JSWENERGY=(
        "generates thermal and renewable electricity",
        "Utilities - Independent Power Producers",
    ),
    NHPC=(
        "develops and operates hydroelectric power generation stations",
        "Utilities - Renewable",
    ),
    SJVN=(
        "builds and operates hydroelectric and solar power projects",
        "Utilities - Renewable",
    ),
    TORNTPOWER=(
        "generates and distributes electricity to licensed areas",
        "Utilities - Independent Power Producers",
    ),
    CESC=(
        "generates and distributes electricity in metropolitan areas",
        "Utilities - Independent Power Producers",
    ),
    INFY=(
        "provides consulting, technology and outsourcing services including software "
        "engineering and digital transformation",
        "Information Technology Services",
    ),
)

INDIA = _universe(
    ("TARIL", "Transformers and Rectifiers India Ltd.", "Capital Goods"),
    ("FINCABLES", "Finolex Cables Ltd.", "Capital Goods"),
    ("ACMESOLAR", "ACME Solar Holdings Ltd.", "Power"),
    ("ADANIPOWER", "Adani Power Ltd.", "Power"),
    ("NTPC", "NTPC Ltd.", "Power"),
    ("TATAPOWER", "Tata Power Company Ltd.", "Power"),
    ("JSWENERGY", "JSW Energy Ltd.", "Power"),
    ("NHPC", "NHPC Ltd.", "Power"),
    ("SJVN", "SJVN Ltd.", "Power"),
    ("TORNTPOWER", "Torrent Power Ltd.", "Power"),
    ("CESC", "CESC Ltd.", "Power"),
    ("INFY", "Infosys Ltd.", "Information Technology"),
)


class TestMatching:
    """Matching reads what a company does, never what it is called."""

    def test_a_company_is_found_by_what_it_does(self) -> None:
        """TARIL's name says nothing to a term matcher; its business description does."""
        matches, _ = match_description(
            "Transformer and rectifier manufacturers", INDIA, PROFILES
        )

        assert "TARIL" in {symbol for symbol, _ in matches}

    def test_the_company_name_is_not_searched(self) -> None:
        """The defect this replaced. A name is branding, not a description of a business."""
        from app.data.profiles import CompanyProfile

        profile = CompanyProfile(
            symbol="TARIL", description="makes widgets", industry="Widgets"
        )

        assert "taril" not in profile.searchable

    def test_one_shared_word_is_not_a_match(self) -> None:
        """With hundreds of words of prose to search, one coincidence is not a subject."""
        matches, _ = match_description("Renewable aviation catering", INDIA, PROFILES)

        assert "ACMESOLAR" not in {symbol for symbol, _ in matches}

    def test_several_companies_can_match_one_description(self) -> None:
        matches, _ = match_description(
            "Electricity generation and distribution utilities", INDIA, PROFILES
        )

        assert len(matches) > 1

    def test_the_basis_names_the_terms_that_matched(self) -> None:
        matches, _ = match_description("Power transformer manufacturers", INDIA, PROFILES)
        why = next((w for symbol, w in matches if symbol == "TARIL"), "")

        assert "transformers" in why or "power" in why

    def test_stopwords_alone_match_nothing(self) -> None:
        matches, reason = match_description("Providers and suppliers", INDIA, PROFILES)

        assert matches == []
        assert reason == "no discriminating terms"

    def test_without_profiles_nothing_matches_and_it_says_why(self) -> None:
        """Better than falling back to names, which is exactly what this replaced."""
        matches, reason = match_description("Transformer manufacturers", INDIA, None)

        assert matches == []
        assert "profiles" in reason

    def test_an_unmatched_description_reports_no_special_reason(self) -> None:
        matches, reason = match_description("Lithography toolmakers", INDIA, PROFILES)

        assert matches == []
        assert reason is None

    def test_truncation_is_reported_rather_than_silent(self) -> None:
        """Thirteen defence companies once tied and a cap dropped four alphabetically."""
        from app.themes import resolve as resolve_module

        original = resolve_module.MAX_PER_DESCRIPTION
        resolve_module.MAX_PER_DESCRIPTION = 2
        try:
            matches, note = match_description(
                "Electricity generation utilities", INDIA, PROFILES
            )
        finally:
            resolve_module.MAX_PER_DESCRIPTION = original

        assert len(matches) == 2
        assert note is not None
        assert "of" in note

    def test_short_tokens_do_not_match_accidentally(self) -> None:
        assert terms("EV and IT gas") == []


class TestResolvingATier:
    def test_candidates_come_back_with_how_they_matched(self) -> None:
        found, missing = resolve_tier(
            "data_centre", 2, "Grid and power equipment",
            ["Transformer and rectifier manufacturers", "Electrical cable manufacturers"],
            INDIA, profiles=PROFILES,
        )

        assert missing is None
        assert {c.symbol for c in found} == {"TARIL", "FINCABLES"}
        assert all(c.exposure is Exposure.UNESTABLISHED for c in found)
        assert all("business description mentions" in c.exposure_basis for c in found)

    def test_a_company_that_discussed_the_theme_is_graded_claimed(self) -> None:
        """It said so itself. That is a stronger claim than an industry that looks right."""
        reference = Reference(
            symbol="TARIL", concept="data_centre", period="Jun 2026",
            kind=SourceKind.COMMENTARY, source_ref="doc://taril",
        )

        found, _ = resolve_tier(
            "data_centre", 1, "Data centre buildout", [], INDIA, references=[reference]
        )

        assert [c.symbol for c in found] == ["TARIL"]
        assert found[0].exposure is Exposure.CLAIMED
        assert "discussed the theme" in found[0].exposure_basis

    def test_a_reference_outside_the_universe_is_not_a_candidate(self) -> None:
        """The boundary. Research may be global; picks may not."""
        reference = Reference(
            symbol="NVDA", concept="data_centre", period="Jun 2026",
            kind=SourceKind.COMMENTARY, source_ref="doc://nvda",
        )

        found, _ = resolve_tier(
            "data_centre", 1, "Compute", [], INDIA, references=[reference]
        )

        assert found == []

    def test_references_only_apply_to_the_theme_s_own_tier(self) -> None:
        """A company talking about data centres is evidence about data centres, not cables."""
        reference = Reference(
            symbol="INFY", concept="data_centre", period="Jun 2026",
            kind=SourceKind.COMMENTARY, source_ref="doc://infy",
        )

        found, _ = resolve_tier(
            "data_centre", 3, "Raw materials", [], INDIA, references=[reference]
        )

        assert found == []

    def test_a_claimed_grade_is_not_overwritten_by_an_industry_match(self) -> None:
        reference = Reference(
            symbol="TARIL", concept="data_centre", period="Jun 2026",
            kind=SourceKind.COMMENTARY, source_ref="doc://taril",
        )

        found, _ = resolve_tier(
            "data_centre", 1, "Buildout", ["Transformer and rectifier manufacturers"],
            INDIA, references=[reference], profiles=PROFILES,
        )

        assert next(c for c in found if c.symbol == "TARIL").exposure is Exposure.CLAIMED


class TestTiersWithNoIndianExposure:
    def test_a_tier_with_no_match_says_so(self) -> None:
        found, missing = resolve_tier(
            "data_centre", 1, "Semiconductor fabrication",
            ["Advanced semiconductor foundries"], INDIA, profiles=PROFILES,
        )

        assert found == []
        assert missing is not None
        assert "business description matched" in missing.reason

    def test_foreign_names_explain_the_tier_without_being_offered(self) -> None:
        """Knowing where the value goes is worth knowing, even when it cannot be bought here."""
        _, missing = resolve_tier(
            "data_centre", 1, "Semiconductor fabrication",
            ["EUV lithography toolmakers"], INDIA, profiles=PROFILES,
            notable_examples=[{"name": "ASML", "investable": False}],
        )

        assert "ASML" in missing.reason
        assert "not listed in India" in missing.reason

    def test_unresolved_descriptions_are_recorded(self) -> None:
        _, missing = resolve_tier(
            "data_centre", 1, "Fabrication", ["Advanced semiconductor foundries"], INDIA,
            profiles=PROFILES,
        )

        assert "Advanced semiconductor foundries" in missing.unresolved_descriptions[0]

    def test_a_description_with_no_usable_terms_records_why(self) -> None:
        _, missing = resolve_tier(
            "t", 2, "Power", ["Providers and suppliers"], INDIA, profiles=PROFILES
        )

        assert "no discriminating terms" in missing.unresolved_descriptions[0]

    def test_no_substitute_is_ever_offered(self) -> None:
        """A tenuous domestic smallcap in place of a foreign supplier is the failure to avoid."""
        found, missing = resolve_tier(
            "data_centre", 1, "Lithography", ["EUV lithography toolmakers"], INDIA,
            profiles=PROFILES,
        )

        assert found == []
        assert missing is not None


class TestResolvingAChain:
    def _tiers(self) -> list[dict]:
        return [
            {
                "tier": 1,
                "label": "Semiconductor fabrication",
                "supplier_descriptions": ["Advanced semiconductor foundries"],
                "notable_examples": [{"name": "TSMC", "investable": False}],
            },
            {
                "tier": 2,
                "label": "Grid and power equipment",
                "supplier_descriptions": ["Transformer and rectifier manufacturers"],
            },
        ]

    def test_a_chain_yields_candidates_and_gaps_together(self) -> None:
        candidates, unresolved = resolve_chain(
            "data_centre", self._tiers(), INDIA, profiles=PROFILES
        )

        assert [c.symbol for c in candidates] == ["TARIL"]
        assert [u.tier for u in unresolved] == [1]

    def test_a_rejected_link_contributes_nothing(self) -> None:
        tiers = self._tiers()
        tiers[1]["rejected"] = True

        candidates, _ = resolve_chain("data_centre", tiers, INDIA, profiles=PROFILES)

        assert candidates == []

    def test_a_rejected_link_is_not_reported_as_a_gap_either(self) -> None:
        """Rejected means "I have judged this", not "this failed to resolve"."""
        tiers = self._tiers()
        tiers[0]["rejected"] = True

        _, unresolved = resolve_chain("data_centre", tiers, INDIA, profiles=PROFILES)

        assert unresolved == []


class TestOnlyIndianNamesAreEverOffered:
    def test_every_candidate_is_in_the_universe(self) -> None:
        references = [
            Reference("NVDA", "data_centre", "Jun 2026", SourceKind.COMMENTARY, "d"),
            Reference("TARIL", "data_centre", "Jun 2026", SourceKind.COMMENTARY, "d"),
        ]

        candidates, _ = resolve_chain(
            "data_centre",
            [{"tier": 1, "label": "x", "supplier_descriptions": []}],
            INDIA,
            references=references,
            profiles=PROFILES,
        )

        listed = {i.symbol for i in INDIA.instruments}
        assert all(c.symbol in listed for c in candidates)

    def test_notable_examples_never_become_candidates(self) -> None:
        candidates, _ = resolve_chain(
            "data_centre",
            [
                {
                    "tier": 1,
                    "label": "Compute",
                    "supplier_descriptions": ["GPU designers"],
                    "notable_examples": [{"name": "NVIDIA", "investable": False}],
                }
            ],
            INDIA,
            profiles=PROFILES,
        )

        assert all("NVIDIA" not in c.symbol for c in candidates)
        assert candidates == []


class TestTheRunner:
    """One pass end to end, and what happens when a step cannot run.

    Degradation is the design here, not an error path, so most of these are failure cases.
    """

    @pytest.fixture
    def store(self, session_factory) -> ThemeStore:
        return ThemeStore(session_factory)

    def _refs(self, companies: int = 3, periods: int = 2) -> list[Reference]:
        return [
            _ref(f"CO{c}", period=f"P{p}")
            for c in range(companies)
            for p in range(periods)
        ]

    def _gatherer(self, gathered: Gathered):
        return lambda: gathered

    def _universe(self):
        class Source:
            def snapshot(self):
                return INDIA

        return Source()

    def _expander(self, tiers: list[dict]):
        return lambda theme: tiers

    def _runner(self, store, gathered, expander=None, **kwargs) -> ThemeRunner:
        class Profiles:
            def all(self):
                return PROFILES

        return ThemeRunner(
            store=store,
            gatherer=self._gatherer(gathered),
            universe_source=self._universe(),
            expander=expander,
            profile_source=Profiles(),
            **kwargs,
        )

    # ── the happy path ────────────────────────────────────────────────────────
    def test_a_run_surfaces_records_and_completes(self, store: ThemeStore) -> None:
        runner = self._runner(store, Gathered(references=self._refs(), documents_read=6))

        result = runner.run()

        assert result.outcome == "complete"
        assert result.surfaced == 1
        assert result.documents_read == 6
        assert [t["key"] for t in store.standing()] == ["data_centre"]

    def test_a_chain_is_expanded_and_resolved(self, store: ThemeStore) -> None:
        tiers = [
            {
                "tier": 2,
                "label": "Grid and power equipment",
                "reasoning": "Data centres draw continuous high load.",
                "proposed_by": "ollama/test",
                "supplier_descriptions": ["Transformer and rectifier manufacturers"],
            }
        ]
        runner = self._runner(
            store, Gathered(references=self._refs(), documents_read=6), self._expander(tiers)
        )

        result = runner.run()

        assert result.chains_expanded == 1
        assert result.candidates >= 1
        assert "TARIL" in {c["symbol"] for c in store.candidates("data_centre")}

    def test_a_tier_without_indian_exposure_is_counted(self, store: ThemeStore) -> None:
        tiers = [
            {
                "tier": 1,
                "label": "Lithography",
                "reasoning": "Required to pattern wafers.",
                "proposed_by": "ollama/test",
                "supplier_descriptions": ["EUV lithography toolmakers"],
            }
        ]
        runner = self._runner(
            store, Gathered(references=self._refs(), documents_read=1), self._expander(tiers)
        )

        result = runner.run()

        assert result.tiers_without_indian_exposure == 1

    # ── degradation ───────────────────────────────────────────────────────────
    def test_a_run_that_read_nothing_says_so(self, store: ThemeStore) -> None:
        """Not "no themes found" — nothing was read, so nothing is known."""
        runner = self._runner(
            store, Gathered(unavailable=(SourceKind.COMMENTARY, SourceKind.POLICY))
        )

        result = runner.run()

        assert result.outcome == "no_reading"
        assert set(result.sources_unavailable) == {"commentary", "policy"}

    def test_a_run_that_read_nothing_withdraws_nothing(self, store: ThemeStore) -> None:
        """The rule that prevents a broken scraper from erasing a real theme."""
        self._runner(store, Gathered(references=self._refs(), documents_read=6)).run()
        assert len(store.standing()) == 1

        self._runner(store, Gathered(unavailable=(SourceKind.COMMENTARY,))).run()

        assert len(store.standing()) == 1

    def test_partial_sources_still_produce_themes_and_record_the_gap(
        self, store: ThemeStore
    ) -> None:
        runner = self._runner(
            store,
            Gathered(
                references=self._refs(),
                documents_read=2,
                unavailable=(SourceKind.COMMENTARY,),
            ),
        )

        result = runner.run()

        assert result.outcome == "complete"
        assert result.surfaced == 1
        assert result.sources_unavailable == ("commentary",)

    def test_a_failing_gatherer_fails_the_run_without_raising(
        self, store: ThemeStore
    ) -> None:
        def boom():
            raise RuntimeError("source layer down")

        runner = ThemeRunner(
            store=store, gatherer=boom, universe_source=self._universe()
        )

        result = runner.run()

        assert result.outcome == "failed"
        assert "source layer down" in result.reason

    def test_a_failing_expander_does_not_end_the_run(self, store: ThemeStore) -> None:
        """A theme is useful without a chain; losing the run over one would not be."""

        def boom(theme):
            raise RuntimeError("model unavailable")

        runner = self._runner(
            store, Gathered(references=self._refs(), documents_read=3), boom
        )

        result = runner.run()

        assert result.outcome == "complete"
        assert result.surfaced == 1
        assert result.chains_expanded == 0

    def test_no_expander_configured_still_surfaces_themes(self, store: ThemeStore) -> None:
        runner = self._runner(store, Gathered(references=self._refs(), documents_read=3))

        result = runner.run()

        assert result.surfaced == 1
        assert result.chains_expanded == 0

    # ── concurrency ───────────────────────────────────────────────────────────
    def test_a_second_concurrent_run_is_refused(self, store: ThemeStore) -> None:
        """Two runs writing the same counts would blend two passes into one figure."""
        first = store.start_run()

        result = self._runner(store, Gathered(references=self._refs())).run()

        assert result.outcome == "refused"
        assert result.run_id == first

    # ── rejection survives ────────────────────────────────────────────────────
    def test_a_rejected_link_is_not_reinstated_by_a_later_run(
        self, store: ThemeStore
    ) -> None:
        tiers = [
            {
                "tier": 2,
                "label": "Grid and power equipment",
                "reasoning": "Data centres draw continuous high load.",
                "proposed_by": "ollama/test",
                "supplier_descriptions": ["Transformer and rectifier manufacturers"],
            }
        ]
        gathered = Gathered(references=self._refs(), documents_read=3)
        self._runner(store, gathered, self._expander(tiers)).run()

        [link] = store.chain("data_centre")
        assert store.reject_link(link["id"], "wrong tier") is True

        self._runner(store, gathered, self._expander(tiers)).run()

        [after] = store.chain("data_centre")
        assert after["rejected"] is True
        assert after["rejected_reason"] == "wrong tier"

    def test_a_rejected_link_stops_contributing_candidates(
        self, store: ThemeStore
    ) -> None:
        tiers = [
            {
                "tier": 2,
                "label": "Grid and power equipment",
                "reasoning": "Data centres draw continuous high load.",
                "proposed_by": "ollama/test",
                "supplier_descriptions": ["Transformer and rectifier manufacturers"],
            }
        ]
        gathered = Gathered(references=self._refs(), documents_read=3)
        self._runner(store, gathered, self._expander(tiers)).run()
        [link] = store.chain("data_centre")
        store.reject_link(link["id"])

        result = self._runner(store, gathered, self._expander(tiers)).run()

        assert result.candidates == 0

    def test_rejecting_a_link_writes_no_trade(
        self, store: ThemeStore, session_factory
    ) -> None:
        from app.persistence.models import Trade as TradeRow

        tiers = [
            {
                "tier": 1,
                "label": "Buildout",
                "reasoning": "The activity itself.",
                "proposed_by": "ollama/test",
                "supplier_descriptions": [],
            }
        ]
        self._runner(
            store, Gathered(references=self._refs(), documents_read=1), self._expander(tiers)
        ).run()
        [link] = store.chain("data_centre")
        store.reject_link(link["id"])

        with session_factory() as session:
            assert session.query(TradeRow).count() == 0

    def test_rejecting_an_unknown_link_is_false_not_an_error(
        self, store: ThemeStore
    ) -> None:
        assert store.reject_link(99999) is False


class TestExposureGrading:
    """Three grades, ordered by what supports them. No number, ever."""

    def _financials(self):
        from app.data.indian_api import parse_stock

        payload = json.loads(
            (Path(__file__).parent / "fixtures" / "indianapi" / "stock.json").read_text("utf-8")
        )
        return parse_stock("TCS", payload)

    def _candidate(self, exposure: Exposure = Exposure.UNESTABLISHED) -> Candidate:
        return Candidate(
            symbol="TCS", theme_key="t", tier=2, exposure=exposure,
            exposure_basis="industry or name matches 'x'; nothing corroborates it",
        )

    def test_a_business_description_establishes_exposure(self) -> None:
        """The company said what it does, in its own filing prose."""
        graded = grade(self._candidate(), "information technology services",
                       financials=self._financials())

        assert graded.exposure is Exposure.ESTABLISHED
        assert "business description names" in graded.exposure_basis

    def test_the_basis_quotes_the_description(self) -> None:
        """A grade a reader cannot check is a grade they have to take on trust."""
        graded = grade(self._candidate(), "consulting", financials=self._financials())

        assert "consulting" in graded.exposure_basis
        assert "business solutions" in graded.exposure_basis

    def test_the_quotation_does_not_split_words(self) -> None:
        """An excerpt cut mid-word reads as broken rather than shortened."""
        graded = grade(self._candidate(), "consulting", financials=self._financials())
        quoted = graded.exposure_basis.split("“", 1)[-1].rstrip("”")

        # Every whole word in the quotation appears in the description it came from.
        description = self._financials().description
        for word in quoted.replace("…", " ").split():
            if word.isalpha():
                assert word in description

    def test_commentary_alone_is_claimed_not_established(self) -> None:
        reference = Reference("TCS", "t", "Jun 2026", SourceKind.COMMENTARY, "doc://x")

        graded = grade(self._candidate(), "green hydrogen", references=[reference])

        assert graded.exposure is Exposure.CLAIMED

    def test_neither_leaves_it_unestablished_and_still_listed(self) -> None:
        graded = grade(self._candidate(), "green hydrogen electrolysers",
                       financials=self._financials())

        assert graded.exposure is Exposure.UNESTABLISHED
        assert graded.symbol == "TCS"

    def test_a_grade_is_never_lowered(self) -> None:
        """A provider being unavailable is not evidence about the company."""
        already = self._candidate(Exposure.CLAIMED)

        graded = grade(already, "green hydrogen", financials=None)

        assert graded.exposure is Exposure.CLAIMED

    def test_grading_spends_at_most_the_limit(self) -> None:
        """The only part of the engine costing a metered request per company."""
        calls: list[str] = []

        class Source:
            def financials(self, instrument):
                calls.append(instrument.symbol)
                return None

        candidates = [
            Candidate(symbol=s, theme_key="t", tier=1, exposure=Exposure.UNESTABLISHED)
            for s in ("A", "B", "C", "D")
        ]

        grade_many(candidates, "theme", financials_source=Source(), limit=2)

        assert len(calls) == 2

    def test_a_failing_lookup_does_not_lose_the_candidate(self) -> None:
        class Source:
            def financials(self, instrument):
                raise RuntimeError("provider down")

        candidates = [Candidate(symbol="A", theme_key="t", tier=1,
                                exposure=Exposure.UNESTABLISHED)]

        graded = grade_many(candidates, "theme", financials_source=Source())

        assert [c.symbol for c in graded] == ["A"]

    def test_no_grade_is_a_number(self) -> None:
        for exposure in Exposure:
            with pytest.raises((TypeError, ValueError)):
                float(exposure.value)


class TestAgainstTheExchangesOwnTheme:
    """Measured against NIFTY INDIA DEFENCE, whose membership NSE publishes.

    This is the test that caught the engine classifying companies by **name**. Matching a
    supplier description against `company name + NSE industry` found three of nineteen
    constituents, with all nineteen present in the universe and available to be found — because
    seventeen of them file as "Capital Goods" and exactly one carries "Defence" in its name.

    Matching on what a company *does* — its business description and a granular industry —
    finds all nineteen. Hindustan Aeronautics never says "defence" in its name; its description
    says it designs and manufactures aircraft, helicopters and aero-engines.

    Both halves are asserted: that it works now, and that the specific companies which used to
    be missed are found. Name matching is not a coarse version of this, it is a different and
    wrong thing, and these numbers are the record of the difference.
    """

    FIXTURES = Path(__file__).parent / "fixtures" / "themes"

    def _members(self) -> list[dict]:
        return json.loads(
            (self.FIXTURES / "nifty_india_defence.json").read_text("utf-8")
        )["members"]

    def _universe(self) -> UniverseSnapshot:
        return UniverseSnapshot(
            instruments=tuple(
                Instrument(m["symbol"], m["name"], m["industry"]) for m in self._members()
            ),
            origin="live",
            index_name="NIFTY INDIA DEFENCE",
        )

    def _profiles(self) -> dict:
        from app.data.profiles import YFinanceProfileSource

        return YFinanceProfileSource(self.FIXTURES / "defence_profiles.json").all()

    def _chain(self) -> list[dict]:
        return json.loads((self.FIXTURES / "defence_chain.json").read_text("utf-8"))["tiers"]

    def _found(self) -> set[str]:
        found, _ = resolve_chain(
            "defence", self._chain(), self._universe(), profiles=self._profiles()
        )
        return {c.symbol for c in found}

    def test_the_fixture_is_the_exchanges_own_membership(self) -> None:
        members = self._members()

        assert len(members) > 10
        assert {"symbol", "name", "industry"} <= set(members[0])

    def test_the_nse_classification_is_why_names_failed(self) -> None:
        """Seventeen of nineteen defence companies file as "Capital Goods"."""
        industries = [m["industry"] for m in self._members()]

        assert industries.count("Capital Goods") > len(industries) * 0.8
        assert sum("defence" in m["name"].lower() for m in self._members()) <= 2

    def test_profiles_describe_the_business_where_names_do_not(self) -> None:
        profiles = self._profiles()

        assert len(profiles) >= len(self._members())
        assert all(p.description for p in profiles.values())

    def test_resolution_finds_effectively_the_whole_theme(self) -> None:
        """Three of nineteen by name; all nineteen by description."""
        members = {m["symbol"] for m in self._members()}
        hits = self._found() & members

        assert len(hits) >= len(members) * 0.9, sorted(members - hits)

    def test_the_names_name_matching_missed_are_now_found(self) -> None:
        """Not marginal names — the core of Indian defence manufacturing."""
        hits = self._found()

        for previously_missed in ("HAL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "ZENTEC"):
            assert previously_missed in hits, previously_missed

    def test_matching_does_not_depend_on_the_company_name(self) -> None:
        """The regression that matters. Blank every name; the result must not change."""
        members = self._members()
        anonymous = UniverseSnapshot(
            instruments=tuple(
                Instrument(m["symbol"], None, m["industry"]) for m in members
            ),
            origin="live",
            index_name="NIFTY INDIA DEFENCE",
        )

        found, _ = resolve_chain(
            "defence", self._chain(), anonymous, profiles=self._profiles()
        )

        assert {c.symbol for c in found} == self._found()


class TestThemesApi:
    """Read-heavy by design. One expensive POST, one rejection, everything else reads."""

    @pytest.fixture
    def client(self, migrated_url: str):
        from app.core.settings import Settings
        from app.main import create_app
        from tests.conftest import authed_client

        return authed_client(create_app(Settings(app_env="test", database_url=migrated_url)))

    @pytest.fixture
    def seeded(self, migrated_url: str) -> ThemeStore:
        from app.core.settings import Settings
        from app.persistence.session import make_engine, make_session_factory

        factory = make_session_factory(
            make_engine(Settings(app_env="test", database_url=migrated_url))
        )
        store = ThemeStore(factory)
        references = tuple(
            _ref(f"CO{c}", period=f"P{p}") for c in range(3) for p in range(2)
        )
        store.record([Theme(key="data_centre", label="Data centre buildout",
                            evidence=ThemeEvidence(references=references))])
        store.record_chain(
            "data_centre",
            [
                {
                    "tier": 2,
                    "label": "Grid and power equipment",
                    "supplies": "Data centre buildout",
                    "reasoning": "Data centres draw continuous high load.",
                    "proposed_by": "ollama/test",
                    "supplier_descriptions": ["Transformer manufacturers"],
                }
            ],
        )
        store.record_candidates(
            [
                Candidate(symbol="TARIL", theme_key="data_centre", tier=2,
                          exposure=Exposure.UNESTABLISHED,
                          exposure_basis="industry or name matches 'transformer'")
            ]
        )
        return store

    def test_themes_are_listed_with_their_counts(self, client, seeded) -> None:
        body = client.get("/themes").json()

        assert body["count"] == 1
        theme = body["themes"][0]
        assert theme["breadth"] == 3
        assert theme["persistence"] == 2

    def test_the_latest_run_travels_with_the_themes(self, client, seeded) -> None:
        """So "nothing found" and "nothing could be read" cannot be confused by a caller."""
        seeded.finish_run(seeded.start_run(), "no_reading",
                          sources_unavailable=("commentary",))

        body = client.get("/themes").json()

        assert body["latest_run"]["outcome"] == "no_reading"
        assert body["latest_run"]["sources_unavailable"] == ["commentary"]

    def test_withdrawn_themes_are_excluded_by_default(self, client, seeded) -> None:
        seeded.withdraw_short(
            [Theme(key="data_centre", label="x", evidence=ThemeEvidence(references=(_ref("A"),)))],
            Thresholds().shortfall,
        )

        assert client.get("/themes").json()["count"] == 0
        assert client.get("/themes?include_withdrawn=true").json()["count"] == 1

    def test_a_theme_returns_its_chain_candidates_and_references(
        self, client, seeded
    ) -> None:
        body = client.get("/themes/data_centre").json()

        assert body["label"] == "Data centre buildout"
        assert len(body["chain"]) == 1
        assert body["chain"][0]["proposed_by"] == "ollama/test"
        assert [c["symbol"] for c in body["candidates"]] == ["TARIL"]
        assert len(body["references"]) == 6

    def test_references_are_marked_as_quoted_not_measured(self, client, seeded) -> None:
        body = client.get("/themes/data_centre").json()

        assert all(r["measured_by_platform"] is False for r in body["references"])

    def test_chain_links_are_marked_as_proposals(self, client, seeded) -> None:
        body = client.get("/themes/data_centre").json()

        assert body["chain"][0]["measured_by_platform"] is False

    def test_an_unknown_theme_is_404(self, client, seeded) -> None:
        assert client.get("/themes/nope").status_code == 404

    def test_runs_are_listable(self, client, seeded) -> None:
        seeded.finish_run(seeded.start_run(), "complete", documents_read=4)

        body = client.get("/themes/runs").json()

        assert body["count"] >= 1
        assert body["runs"][0]["documents_read"] == 4

    def test_a_link_can_be_rejected(self, client, seeded) -> None:
        link_id = seeded.chain("data_centre")[0]["id"]

        response = client.post(
            f"/themes/links/{link_id}/reject", json={"reason": "wrong tier"}
        )

        assert response.status_code == 200
        assert seeded.chain("data_centre")[0]["rejected"] is True

    def test_rejecting_an_unknown_link_is_404(self, client, seeded) -> None:
        assert client.post("/themes/links/99999/reject", json={}).status_code == 404

    def test_rejecting_writes_no_trade(self, client, seeded, migrated_url: str) -> None:
        from sqlalchemy import create_engine, text

        link_id = seeded.chain("data_centre")[0]["id"]
        client.post(f"/themes/links/{link_id}/reject", json={})

        with create_engine(migrated_url).begin() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM book_trades")).scalar_one()
        assert count == 0

    def test_running_without_a_runner_configured_is_503(self, client) -> None:
        """The platform is fine; this one capability is not wired up."""
        response = client.post("/themes/run", json={})

        assert response.status_code == 503

    def test_no_endpoint_returns_a_stance_or_a_score(self, client, seeded) -> None:
        """A theme is a lens, not a verdict."""
        body = client.get("/themes/data_centre").json()
        serialised = json.dumps(body).lower()

        for forbidden in ('"stance"', '"conviction"', '"score"', '"rank"'):
            assert forbidden not in serialised


class TestSourceAdapters:
    """Reading documents with a model, and reporting honestly when a source cannot be read."""

    @pytest.fixture
    def store(self, session_factory) -> ConceptStore:
        return ConceptStore(session_factory)

    def _docs(self) -> dict:
        return {
            "ABB": [("Order inflow was strong on data centre demand.", "doc://abb/q1")],
            "SIEMENS": [("Substation demand from hyperscaler build-outs.", "doc://siemens/q1")],
        }

    def _extractor(self, labels: list[str]):
        def extract(symbol, period, text, source_ref):
            return [
                {
                    "symbol": symbol,
                    "period": period,
                    "label": label,
                    "excerpt": text[:80],
                    "source_ref": source_ref,
                    "extracted_by": "ollama/test",
                }
                for label in labels
            ]

        return extract

    def test_documents_are_read_and_stored(self, store: ConceptStore) -> None:
        docs = self._docs()

        result = read_documents(
            list(docs), lambda s: docs.get(s), self._extractor(["data centre demand"]),
            store, "Jun 2026",
        )

        assert result.documents_read == 2
        assert result.available is True
        assert {r.symbol for r in result.references} == {"ABB", "SIEMENS"}

    def test_a_document_already_read_is_skipped(self, store: ConceptStore) -> None:
        """Reading is minutes of local model time and a published document never changes."""
        docs = self._docs()
        calls: list[str] = []

        def counting(symbol, period, text, source_ref):
            calls.append(source_ref)
            return self._extractor(["x"])(symbol, period, text, source_ref)

        read_documents(list(docs), lambda s: docs.get(s), counting, store, "Jun 2026")
        read_documents(list(docs), lambda s: docs.get(s), counting, store, "Jun 2026")

        assert len(calls) == 2

    def test_a_run_with_nothing_new_still_reports_its_references(
        self, store: ConceptStore
    ) -> None:
        """A week with no new filings still has themes -- counts come from the store."""
        docs = self._docs()
        read_documents(
            list(docs), lambda s: docs.get(s), self._extractor(["data centre demand"]),
            store, "Jun 2026",
        )

        again = read_documents(
            list(docs), lambda s: docs.get(s), self._extractor(["x"]), store, "Jun 2026"
        )

        assert again.documents_read == 0
        assert again.available is True
        assert len(again.references) == 2

    def test_every_extraction_failing_marks_the_source_unavailable(
        self, store: ConceptStore
    ) -> None:
        docs = self._docs()

        result = read_documents(
            list(docs), lambda s: docs.get(s), lambda *a: [], store, "Jun 2026"
        )

        assert result.available is False

    def test_a_failing_reader_does_not_raise(self, store: ConceptStore) -> None:
        def boom(symbol):
            raise RuntimeError("scrape blocked")

        result = read_documents(["A"], boom, self._extractor(["x"]), store, "Jun 2026")

        assert result.references == []

    def test_the_document_limit_is_respected(self, store: ConceptStore) -> None:
        docs = self._docs()

        result = read_documents(
            list(docs), lambda s: docs.get(s), self._extractor(["x"]), store,
            "Jun 2026", limit=1,
        )

        assert result.documents_read == 1

    def test_filings_are_read_by_the_same_path_under_their_own_kind(
        self, store: ConceptStore
    ) -> None:
        filings = {"ABB": [("Board approved a new plant.", "nse://ann/1")]}

        result = read_documents(
            ["ABB"], lambda s: filings.get(s), self._extractor(["capacity expansion"]),
            store, "Jun 2026", kind=SourceKind.FILING,
        )

        assert result.documents_read == 1
        assert all(r.kind is SourceKind.FILING for r in result.references)


class TestPolicyClassification:
    """Twelve keywords replaced by a model that can read."""

    def _feed(self) -> list[tuple[str, str, str, str]]:
        return [
            ("Cabinet approves incentives for electronics assembly",
             "The government cleared support.", "https://x/1", "et"),
            ("Reliance Q1 profit rises on refining margins",
             "The company reported higher earnings.", "https://x/2", "et"),
        ]

    def _classifier(self, results: list[dict]):
        return lambda headlines: results

    def test_policy_items_become_references(self) -> None:
        result = policy_references(
            classifier=self._classifier(
                [{"index": 0, "subject": "electronics manufacturing", "headline": "Cabinet"}]
            ),
            fetcher=lambda hours: self._feed(),
            period="Jun 2026",
        )

        assert result.available is True
        assert [r.concept for r in result.references] == ["electronics manufacturing"]

    def test_the_subject_is_the_concept(self) -> None:
        """The policy's own description of what it touches, not a guessed keyword."""
        result = policy_references(
            classifier=self._classifier(
                [{"index": 0, "subject": "semiconductor fabrication", "headline": "h"}]
            ),
            fetcher=lambda hours: self._feed(),
        )

        assert result.references[0].concept == "semiconductor fabrication"

    def test_policy_references_carry_no_company(self) -> None:
        result = policy_references(
            classifier=self._classifier([{"index": 0, "subject": "x", "headline": "h"}]),
            fetcher=lambda hours: self._feed(),
        )

        assert all(r.symbol == "" for r in result.references)

    def test_policy_cannot_inflate_breadth(self) -> None:
        """The rule that stops one budget announcement manufacturing a theme."""
        result = policy_references(
            classifier=self._classifier([{"index": 0, "subject": "x", "headline": "h"}]),
            fetcher=lambda hours: self._feed(),
        )

        assert ThemeEvidence(references=tuple(result.references)).breadth == 0

    def test_an_index_nobody_offered_is_dropped(self) -> None:
        """A classification of a headline that was not sent is the model inventing one."""
        result = policy_references(
            classifier=self._classifier([{"index": 99, "subject": "x", "headline": "h"}]),
            fetcher=lambda hours: self._feed(),
        )

        assert result.references == []

    def test_a_failing_classifier_marks_the_source_unavailable(self) -> None:
        def boom(headlines):
            raise RuntimeError("model down")

        result = policy_references(classifier=boom, fetcher=lambda hours: self._feed())

        assert result.available is False
        assert result.references == []

    def test_unreachable_feeds_are_unavailable(self) -> None:
        def boom(hours):
            raise RuntimeError("feeds unreachable")

        result = policy_references(classifier=lambda h: [], fetcher=boom)

        assert result.available is False

    def test_feeds_that_answered_with_nothing_are_still_available(self) -> None:
        result = policy_references(classifier=lambda h: [], fetcher=lambda hours: [])

        assert result.available is True


class TestScheduler:
    """The reload guard, and failing safely."""

    def test_a_plain_process_schedules(self, monkeypatch) -> None:
        monkeypatch.delenv("UVICORN_RELOAD", raising=False)
        monkeypatch.delenv("RUN_MAIN", raising=False)

        assert is_reloader_supervisor() is False

    def test_the_reload_supervisor_does_not_schedule(self, monkeypatch) -> None:
        """Both uvicorn processes run the app factory; only the child may schedule.

        Without this every scheduled job fires twice under `--reload`, silently, and the
        symptom is a mysterious "run already in progress" rather than anything pointing here.
        """
        monkeypatch.setenv("UVICORN_RELOAD", "true")
        monkeypatch.delenv("RUN_MAIN", raising=False)

        assert is_reloader_supervisor() is True

    def test_the_reload_child_does_schedule(self, monkeypatch) -> None:
        monkeypatch.setenv("UVICORN_RELOAD", "true")
        monkeypatch.setenv("RUN_MAIN", "true")

        assert is_reloader_supervisor() is False

    def test_a_supervisor_scheduler_runs_nothing(self, monkeypatch) -> None:
        monkeypatch.setenv("UVICORN_RELOAD", "true")
        monkeypatch.delenv("RUN_MAIN", raising=False)

        scheduler = Scheduler()
        scheduler.every_week("themes", lambda: None, "sun", 8)

        assert scheduler.start() is False
        assert scheduler.active is False

    def test_disabled_schedules_nothing(self, monkeypatch) -> None:
        monkeypatch.delenv("UVICORN_RELOAD", raising=False)
        scheduler = Scheduler(enabled=False)
        scheduler.every_week("themes", lambda: None, "sun", 8)

        assert scheduler.start() is False

    def test_no_jobs_means_nothing_started(self, monkeypatch) -> None:
        monkeypatch.delenv("UVICORN_RELOAD", raising=False)

        assert Scheduler().start() is False

    def test_a_job_is_registered_and_started(self, monkeypatch) -> None:
        monkeypatch.delenv("UVICORN_RELOAD", raising=False)
        monkeypatch.delenv("RUN_MAIN", raising=False)

        scheduler = Scheduler()
        scheduler.every_week("themes", lambda: None, "sun", 8)
        started = scheduler.start()
        try:
            assert started is True
            assert scheduler.job_ids() == ["themes"]
        finally:
            scheduler.shutdown()

    def test_a_failing_job_never_reaches_the_scheduler(self) -> None:
        """A job that dies takes its run down. A scheduler that dies takes every future run."""
        from app.core.scheduler import _guarded

        def boom():
            raise RuntimeError("run failed")

        _guarded("themes", boom)()  # must not raise

    def test_scheduling_is_off_by_default(self) -> None:
        """A platform that starts doing things on a timer when installed is a surprise."""
        from app.core.settings import Settings

        assert Settings(_env_file=None).scheduler_enabled is False
