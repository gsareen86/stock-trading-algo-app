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

import pytest

from app.data.protocols import UniverseSnapshot
from app.domain.instrument import Instrument
from app.domain.themes import Exposure, Reference, SourceKind, Theme, ThemeEvidence
from app.themes.detect import CONCEPTS, Thresholds, assemble, extract
from app.themes.resolve import (
    match_description,
    resolve_chain,
    resolve_tier,
    terms,
)
from app.themes.runner import Gathered, ThemeRunner
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


class TestExtraction:
    def test_a_known_concept_is_found(self) -> None:
        found = extract(
            "ABB", "Jun 2026", "Data centre demand is driving orders.",
            SourceKind.COMMENTARY, "doc://x",
        )

        assert [r.concept for r in found] == ["data_centre"]

    def test_repeated_mentions_are_one_reference(self) -> None:
        text = "data centre " * 40
        found = extract("ABB", "Jun 2026", text, SourceKind.COMMENTARY, "doc://x")

        assert len(found) == 1

    def test_several_concepts_in_one_document(self) -> None:
        found = extract(
            "ABB",
            "Jun 2026",
            "Data centre demand drives transformer and switchgear orders.",
            SourceKind.COMMENTARY,
            "doc://x",
        )

        assert {r.concept for r in found} == {"data_centre", "power_transmission"}

    def test_an_excerpt_is_carried_for_a_reader_to_judge(self) -> None:
        found = extract(
            "ABB", "Jun 2026", "We expect data centre demand to double.",
            SourceKind.COMMENTARY, "doc://x",
        )

        assert "data centre" in found[0].excerpt.lower()

    def test_every_reference_is_traceable(self) -> None:
        found = extract(
            "ABB", "Jun 2026", "Data centre demand.", SourceKind.COMMENTARY, "doc://abb/q1"
        )

        assert found[0].source_ref == "doc://abb/q1"
        assert found[0].symbol == "ABB"
        assert found[0].period == "Jun 2026"

    def test_no_text_is_no_references(self) -> None:
        assert extract("ABB", "Jun 2026", "", SourceKind.COMMENTARY, "d") == []

    def test_an_unlisted_concept_is_simply_not_found(self) -> None:
        """A gap, and an honest one — the alternative is a model that is not reproducible."""
        found = extract(
            "ABB", "Jun 2026", "We are investing in artisanal cheese.",
            SourceKind.COMMENTARY, "doc://x",
        )

        assert found == []

    def test_concept_phrases_are_lowercase(self) -> None:
        """Matching is done on lowered text; an upper-case phrase would never match."""
        for phrases in CONCEPTS.values():
            assert all(p == p.lower() for p in phrases)


class TestTheWorkedExample:
    """The case this change exists for: a theme found, and its supply chain one step behind."""

    def _corpus(self) -> list[Reference]:
        rows = [
            ("ABB", "Infrastructure", "Jun 2026", "Data centre demand drives transformer orders."),
            ("SIEMENS", "Infrastructure", "Jun 2026",
             "Substation demand from hyperscaler build-outs."),
            ("POLYCAB", "Metal", "Jun 2026", "Data center cabling demand rose sharply."),
            ("ABB", "Infrastructure", "Mar 2026", "Data centre orders continued to build."),
        ]
        found: list[Reference] = []
        for symbol, sector, period, text in rows:
            found += extract(
                symbol, period, text, SourceKind.COMMENTARY, f"doc://{symbol}/{period}",
                sector=sector,
            )
        return found

    def test_the_theme_surfaces_from_the_supply_chain_not_the_headline(self) -> None:
        surfaced, _ = assemble(self._corpus())

        keys = [t.key for t in surfaced]
        assert "data_centre" in keys

    def test_it_crosses_sectors(self) -> None:
        surfaced, _ = assemble(self._corpus())
        theme = next(t for t in surfaced if t.key == "data_centre")

        assert len(theme.evidence.sectors) > 1


class TestNothingHereRanksOrScores:
    """A theme may widen attention and may never narrow it."""

    def test_a_theme_carries_no_stance_or_conviction(self) -> None:
        fields = set(Theme.__dataclass_fields__)

        assert not fields & {"stance", "conviction", "score", "rank", "strength"}

    def test_exposure_is_a_category_not_a_number(self) -> None:
        for grade in Exposure:
            assert isinstance(grade.value, str)
            with pytest.raises((TypeError, ValueError)):
                float(grade.value)

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
        def expand(prompt: str, task: str):
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
        def boom(prompt: str, task: str):
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

        def expand(prompt: str, task: str):
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
    def test_the_rarest_term_wins(self) -> None:
        """"Transformer manufacturers" must not resolve on the word "power"."""
        matches, _ = match_description("Transformer manufacturers", INDIA)

        assert [symbol for symbol, _ in matches] == ["TARIL"]
        assert matches[0][1] == "transformer"

    def test_a_description_too_broad_to_narrow_says_so(self) -> None:
        """An arbitrary eight of twenty is worse than an honest "this narrowed to nothing"."""
        matches, reason = match_description("Power companies", INDIA)

        assert matches == []
        assert "too broad" in reason

    def test_stopwords_alone_match_nothing(self) -> None:
        matches, reason = match_description("Providers and suppliers", INDIA)

        assert matches == []
        assert reason == "no discriminating terms"

    def test_an_unmatched_description_is_not_too_broad(self) -> None:
        """Nothing matched and everything matched are different problems."""
        matches, reason = match_description("Lithography toolmakers", INDIA)

        assert matches == []
        assert reason is None

    def test_short_tokens_do_not_match_accidentally(self) -> None:
        assert terms("EV and IT gas") == []

    def test_industry_is_searched_as_well_as_name(self) -> None:
        matches, _ = match_description("Information technology", INDIA)

        assert [symbol for symbol, _ in matches] == ["INFY"]


class TestResolvingATier:
    def test_candidates_come_back_with_how_they_matched(self) -> None:
        found, missing = resolve_tier(
            "data_centre", 2, "Grid and power equipment",
            ["Transformer manufacturers", "Power cable manufacturers"], INDIA,
        )

        assert missing is None
        assert {c.symbol for c in found} == {"TARIL", "FINCABLES"}
        assert all(c.exposure is Exposure.UNESTABLISHED for c in found)
        assert all("nothing corroborates it" in c.exposure_basis for c in found)

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
            "data_centre", 1, "Buildout", ["Transformer manufacturers"], INDIA,
            references=[reference],
        )

        assert next(c for c in found if c.symbol == "TARIL").exposure is Exposure.CLAIMED


class TestTiersWithNoIndianExposure:
    def test_a_tier_with_no_match_says_so(self) -> None:
        found, missing = resolve_tier(
            "data_centre", 1, "Semiconductor fabrication",
            ["Advanced semiconductor foundries"], INDIA,
        )

        assert found == []
        assert missing is not None
        # States what it knows -- that name matching failed -- not that the market has no
        # exposure. Kaynes and CG Power both do this and neither matches on name or industry.
        assert "name or industry" in missing.reason
        assert "may still have Indian exposure" in missing.reason

    def test_foreign_names_explain_the_tier_without_being_offered(self) -> None:
        """Knowing where the value goes is worth knowing, even when it cannot be bought here."""
        _, missing = resolve_tier(
            "data_centre", 1, "Semiconductor fabrication",
            ["EUV lithography toolmakers"], INDIA,
            notable_examples=[{"name": "ASML", "investable": False}],
        )

        assert "ASML" in missing.reason
        assert "not listed in India" in missing.reason

    def test_unresolved_descriptions_are_recorded(self) -> None:
        _, missing = resolve_tier(
            "data_centre", 1, "Fabrication", ["Advanced semiconductor foundries"], INDIA
        )

        assert "Advanced semiconductor foundries" in missing.unresolved_descriptions[0]

    def test_a_too_broad_description_records_why(self) -> None:
        _, missing = resolve_tier("t", 2, "Power", ["Power companies"], INDIA)

        assert "too broad" in missing.unresolved_descriptions[0]

    def test_no_substitute_is_ever_offered(self) -> None:
        """A tenuous domestic smallcap in place of a foreign supplier is the failure to avoid."""
        found, missing = resolve_tier(
            "data_centre", 1, "Lithography", ["EUV lithography toolmakers"], INDIA
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
                "supplier_descriptions": ["Transformer manufacturers"],
            },
        ]

    def test_a_chain_yields_candidates_and_gaps_together(self) -> None:
        candidates, unresolved = resolve_chain("data_centre", self._tiers(), INDIA)

        assert [c.symbol for c in candidates] == ["TARIL"]
        assert [u.tier for u in unresolved] == [1]

    def test_a_rejected_link_contributes_nothing(self) -> None:
        tiers = self._tiers()
        tiers[1]["rejected"] = True

        candidates, _ = resolve_chain("data_centre", tiers, INDIA)

        assert candidates == []

    def test_a_rejected_link_is_not_reported_as_a_gap_either(self) -> None:
        """Rejected means "I have judged this", not "this failed to resolve"."""
        tiers = self._tiers()
        tiers[0]["rejected"] = True

        _, unresolved = resolve_chain("data_centre", tiers, INDIA)

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
        return ThemeRunner(
            store=store,
            gatherer=self._gatherer(gathered),
            universe_source=self._universe(),
            expander=expander,
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
                "supplier_descriptions": ["Transformer manufacturers"],
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
                "supplier_descriptions": ["Transformer manufacturers"],
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
                "supplier_descriptions": ["Transformer manufacturers"],
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
