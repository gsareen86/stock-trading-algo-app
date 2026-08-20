"""Theme detection: the counted half.

Nothing here calls a model, and that is the point of the module under test. Breadth and
persistence are arithmetic over documents, so the same references produce the same themes
forever — which is what makes "fourteen companies across three sectors for three quarters" a
claim that can be checked rather than a fluent answer.

The load-bearing tests are the threshold ones and the reproducibility one. Everything else in
`theme-engine` is allowed to be a proposal; this part has to be a measurement.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.themes import Exposure, Reference, SourceKind, Theme, ThemeEvidence
from app.themes.detect import CONCEPTS, Thresholds, assemble, extract
from app.themes.store import ThemeStore


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
        from tests.conftest import source_of

        source = source_of("themes")
        for forbidden in ("def rank", "def score", "conviction", "stance"):
            assert forbidden not in source

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
