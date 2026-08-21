"""Decomposing tiers, searching what stays empty, and refusing what the universe cannot confirm.

Every test here runs offline. The search client and every model call are injected, because no
test in this repository may spend a request from a metered allowance — and because a test whose
result depends on what the web said today is not a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.data.profiles import YFinanceProfileSource
from app.data.protocols import UniverseSnapshot
from app.data.search import SearchOutcome, SearchResults, TavilySearchSource
from app.domain.instrument import Instrument
from app.domain.themes import Exposure, Reference, SourceKind
from app.themes.propose import (
    Proposal,
    ProposalOutcome,
    identifying,
    normalise,
    to_candidates,
    validate,
)
from app.themes.research import TierResearcher, search_query
from app.themes.resolve import focused_excerpt, resolve_tier, terms

FIXTURES = Path(__file__).parent / "fixtures" / "themes"


def _universe(*rows: tuple[str, str]) -> UniverseSnapshot:
    return UniverseSnapshot(
        instruments=tuple(Instrument(symbol=s, name=n, sector="x") for s, n in rows),
        origin="live",
        index_name="TEST",
    )


INDIA = _universe(
    ("KAYNES", "Kaynes Technology India Ltd."),
    ("CGPOWER", "CG Power and Industrial Solutions Ltd."),
    ("BEL", "Bharat Electronics Ltd."),
    ("BDL", "Bharat Dynamics Ltd."),
    ("TATAPOWER", "Tata Power Company Ltd."),
    ("TATAELXSI", "Tata Elxsi Ltd."),
)


def _cited(company: str, sub_category: str = "OSAT") -> Proposal:
    return Proposal(
        company=company,
        sub_category=sub_category,
        rationale="builds an assembly and test plant",
        sources=("https://example-news.in/x",),
        proposed_by="test-model",
    )


class TestNormalisingACompanyName:
    def test_corporate_furniture_is_stripped(self) -> None:
        assert normalise("Kaynes Technology India Limited") == "kaynes technology india"
        assert normalise("CG Power and Industrial Solutions Ltd.") == (
            "cg power and industrial solutions"
        )

    def test_a_group_name_does_not_identify_a_company(self) -> None:
        """"Tata" is a family of separately listed companies, not one of them."""
        assert not identifying("Tata")
        assert not identifying("Bharat")
        assert identifying("Tata Elxsi")
        assert identifying("Bharat Dynamics")


class TestValidatingAProposal:
    def test_a_name_matching_one_instrument_resolves(self) -> None:
        [result] = validate([_cited("Kaynes Technology")], INDIA)

        assert result.outcome is ProposalOutcome.RESOLVED
        assert result.symbol == "KAYNES"

    def test_the_listed_suffix_does_not_have_to_match(self) -> None:
        [result] = validate([_cited("Kaynes Technology India Limited")], INDIA)

        assert result.symbol == "KAYNES"

    def test_a_shorter_proposal_resolves_by_containment(self) -> None:
        [result] = validate([_cited("CG Power")], INDIA)

        assert result.symbol == "CGPOWER"

    def test_a_proposal_matching_nothing_is_recorded_but_never_offered(self) -> None:
        """Amkor is real, is the largest OSAT company in the world, and is not listed here."""
        [result] = validate([_cited("Amkor Technology")], INDIA)

        assert result.outcome is ProposalOutcome.NOT_FOUND
        assert not result.is_candidate
        assert "matched no instrument" in result.reason

    def test_a_company_listed_elsewhere_is_never_a_candidate(self) -> None:
        """Structural rather than a rule: the universe is Indian, so a foreign name cannot hit."""
        foreign = ["ASE Technology Holding", "Amkor Technology", "Taiwan Semiconductor"]

        results = validate([_cited(name) for name in foreign], INDIA)

        assert not any(r.is_candidate for r in results)

    def test_an_ambiguous_group_name_produces_no_candidate(self) -> None:
        [result] = validate([_cited("Tata")], INDIA)

        assert result.outcome is ProposalOutcome.AMBIGUOUS
        assert result.symbol is None

    def test_two_similar_companies_are_not_confused(self) -> None:
        """Bharat Electronics and Bharat Dynamics are different companies."""
        bel, bdl = validate([_cited("Bharat Electronics"), _cited("Bharat Dynamics")], INDIA)

        assert bel.symbol == "BEL"
        assert bdl.symbol == "BDL"

    def test_a_prefix_touching_two_instruments_resolves_to_neither(self) -> None:
        universe = _universe(("A", "Sterling Tools Ltd."), ("B", "Sterling Wilson Ltd."))

        [result] = validate([_cited("Sterling")], universe)

        assert result.outcome is ProposalOutcome.AMBIGUOUS
        assert set(result.matched) == {"A", "B"}
        assert "will not pick one" in result.reason

    def test_an_uncited_proposal_is_never_a_candidate(self) -> None:
        uncited = Proposal(company="Kaynes Technology", sub_category="OSAT", sources=())

        [result] = validate([uncited], INDIA)

        assert not result.is_candidate


class TestGradingASearchDerivedCandidate:
    def test_search_alone_is_unestablished_and_says_why(self) -> None:
        validated = validate([_cited("Kaynes Technology")], INDIA)

        [candidate] = to_candidates(validated, "semi", tier=2)

        assert candidate.exposure is Exposure.UNESTABLISHED
        assert "proposed by search" in candidate.exposure_basis
        assert "https://example-news.in/x" in candidate.exposure_basis

    def test_the_companys_own_commentary_can_raise_the_grade(self) -> None:
        validated = validate([_cited("Kaynes Technology")], INDIA)
        spoke = [
            Reference(
                symbol="KAYNES",
                concept="semiconductor assembly",
                period="Jun 2026",
                kind=SourceKind.COMMENTARY,
                source_ref="https://example.com/call",
            )
        ]

        [candidate] = to_candidates(validated, "semi", tier=2, references=spoke)

        assert candidate.exposure is Exposure.CLAIMED
        # The commentary is what establishes it; search is only how the name was found.
        assert "discussed the theme" in candidate.exposure_basis

    def test_nothing_the_universe_refused_becomes_a_candidate(self) -> None:
        validated = validate(
            [_cited("Kaynes Technology"), _cited("Amkor Technology"), _cited("Tata")], INDIA
        )

        candidates = to_candidates(validated, "semi", tier=2)

        assert [c.symbol for c in candidates] == ["KAYNES"]


class TestTheSearchClient:
    """Three empties that mean different things, and a client that never raises."""

    def test_no_key_is_unconfigured_not_empty(self) -> None:
        result = TavilySearchSource(api_key=None).search("anything")

        assert result.outcome is SearchOutcome.UNCONFIGURED
        assert not result.available

    def test_a_spent_allowance_is_exhausted(self) -> None:
        class Spent:
            def allow(self, detail: str = "") -> bool:
                return False

        result = TavilySearchSource(api_key="k", client=lambda q, n: {}, budget=Spent()).search(
            "anything"
        )

        assert result.outcome is SearchOutcome.EXHAUSTED
        assert "allowance" in result.reason

    def test_a_provider_that_fails_is_unavailable(self) -> None:
        def broken(query, limit):
            raise ConnectionError("no route to host")

        result = TavilySearchSource(api_key="k", client=broken).search("anything")

        assert result.outcome is SearchOutcome.UNAVAILABLE
        assert not result.available

    def test_the_three_empties_are_distinguishable(self) -> None:
        """The point of the enum. A single empty list would say none of this."""
        outcomes = {
            TavilySearchSource(api_key=None).search("q").outcome,
            TavilySearchSource(
                api_key="k", client=lambda q, n: {}, budget=type("B", (), {"allow": lambda s, d="": False})()
            )
            .search("q")
            .outcome,
            TavilySearchSource(
                api_key="k", client=lambda q, n: (_ for _ in ()).throw(OSError("down"))
            )
            .search("q")
            .outcome,
        }

        assert len(outcomes) == 3

    def test_a_hit_with_no_url_is_dropped(self) -> None:
        """An unfollowable citation is not a citation."""
        payload = {"results": [{"title": "x", "content": "y"}, {"url": "https://a", "title": "z"}]}

        result = TavilySearchSource(api_key="k", client=lambda q, n: payload).search("q")

        assert [h.url for h in result.hits] == ["https://a"]

    def test_the_same_query_is_not_paid_for_twice(self) -> None:
        calls = []

        def client(query, limit):
            calls.append(query)
            return {"results": [{"url": "https://a"}]}

        source = TavilySearchSource(api_key="k", client=client)
        source.search("one question")
        source.search("one question")

        assert len(calls) == 1


class TestTheSearchQuery:
    def test_it_names_the_exchanges_not_just_the_country(self) -> None:
        query = search_query("OSAT assembly and test", "Semiconductor packaging")

        assert "NSE" in query and "BSE" in query

    def test_it_does_not_repeat_the_tier_inside_the_sub_category(self) -> None:
        query = search_query("Semiconductor packaging lines", "Semiconductor packaging lines")

        assert query.lower().count("semiconductor packaging lines") == 1


class _Store:
    """A theme store that records what it was told, without a database."""

    def __init__(self) -> None:
        self.subs: list[dict] = []
        self.proposals: list = []
        self.searched: list[tuple[int, str]] = []
        self._next = 1

    def record_sub_categories(self, theme_key, tier, tier_label, sub_categories) -> int:
        written = 0
        for entry in sub_categories:
            self.subs.append(
                {
                    "id": self._next,
                    "theme_key": theme_key,
                    "tier": tier,
                    "tier_label": tier_label,
                    "label": entry.get("label"),
                    "supplier_descriptions": entry.get("supplier_descriptions") or [],
                    "searched": False,
                    "search_outcome": None,
                }
            )
            self._next += 1
            written += 1
        return written

    def sub_categories(self, theme_key) -> list[dict]:
        return [dict(s) for s in self.subs if s["theme_key"] == theme_key]

    def mark_searched(self, sub_category_id, outcome) -> bool:
        self.searched.append((sub_category_id, outcome))
        for sub in self.subs:
            if sub["id"] == sub_category_id:
                sub["searched"] = True
                sub["search_outcome"] = outcome
        return True

    def record_proposals(self, theme_key, tier, validated) -> int:
        self.proposals.extend(validated)
        return len(validated)


SEMI_PROFILES = YFinanceProfileSource(FIXTURES / "semiconductor_profiles.json").all()
SEMI_UNIVERSE = UniverseSnapshot(
    instruments=tuple(
        Instrument(m["symbol"], m["name"], m["industry"])
        for m in json.loads(
            (FIXTURES / "semiconductor_universe.json").read_text("utf-8")
        )["members"]
    ),
    origin="live",
    index_name="SEMI",
)

#: The chain tier the whole change exists for, in the shape the store returns.
BACK_END_TIER = {
    "tier": 2,
    "label": "Semiconductor assembly, packaging and test",
    "reasoning": "Fabricated wafers must be packaged and tested before they can be sold.",
    "supplier_descriptions": ["semiconductor back-end assembly and test services"],
    "rejected": False,
}

OSAT = "outsourced semiconductor assembly and test of packaged devices, performing die attach, wire bonding and final electrical test for fabless customers"
LITHO = "extreme ultraviolet lithography scanners and photolithography projection systems for wafer patterning"


def _decomposer(*subs: dict):
    def decompose(tier, reasoning, descriptions):
        return list(subs)

    return decompose


def _sub(label: str, description: str) -> dict:
    return {
        "label": label,
        "reasoning": "part of the tier",
        "supplier_descriptions": [description],
        "notable_examples": [],
        "proposed_by": "test-model",
    }


class TestDecompositionIsAugmentationNotRescue:
    """It runs against every tier, including the ones that already resolved."""

    def test_a_tier_that_already_resolved_is_still_decomposed(self) -> None:
        store = _Store()
        researcher = TierResearcher(
            store=store,
            decomposer=_decomposer(_sub("OSAT", OSAT)),
            profiles=SEMI_PROFILES,
        )

        result = researcher.research(
            "semi", [BACK_END_TIER], SEMI_UNIVERSE, already={"CGPOWER"}
        )

        assert result.sub_categories == 1

    def test_research_only_ever_adds_names_not_already_offered(self) -> None:
        store = _Store()
        researcher = TierResearcher(
            store=store, decomposer=_decomposer(_sub("OSAT", OSAT)), profiles=SEMI_PROFILES
        )

        result = researcher.research(
            "semi", [BACK_END_TIER], SEMI_UNIVERSE, already={"CGPOWER", "BEL"}
        )

        # Nothing it returns is a removal; the caller's set is untouched and every candidate
        # it adds is new.
        assert {"CGPOWER", "BEL"}.isdisjoint({c.symbol for c in result.candidates})

    def test_a_company_already_offered_is_not_offered_twice(self) -> None:
        store = _Store()
        researcher = TierResearcher(
            store=store,
            decomposer=_decomposer(_sub("OSAT", OSAT), _sub("Packaging", OSAT)),
            profiles=SEMI_PROFILES,
        )

        result = researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)

        symbols = [c.symbol for c in result.candidates]
        assert len(symbols) == len(set(symbols))

    def test_a_rejected_tier_is_not_decomposed(self) -> None:
        """Decomposing a rejected link would reinstate it under six new names."""
        store = _Store()
        researcher = TierResearcher(
            store=store, decomposer=_decomposer(_sub("OSAT", OSAT)), profiles=SEMI_PROFILES
        )

        result = researcher.research(
            "semi", [{**BACK_END_TIER, "rejected": True}], SEMI_UNIVERSE
        )

        assert result.sub_categories == 0

    def test_a_tier_that_cannot_be_decomposed_is_recorded_as_such(self) -> None:
        def broken(tier, reasoning, descriptions):
            raise RuntimeError("model unreachable")

        researcher = TierResearcher(store=_Store(), decomposer=broken, profiles=SEMI_PROFILES)

        result = researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)

        assert result.undecomposed == (BACK_END_TIER["label"],)
        assert result.candidates == []

    def test_no_decomposer_means_no_research_at_all(self) -> None:
        result = TierResearcher(store=_Store()).research("semi", [BACK_END_TIER], SEMI_UNIVERSE)

        assert result.sub_categories == 0
        assert result.searched == 0


class TestSearchRunsOnlyWhereDescriptionMatchingFailed:
    def _researcher(self, store, *subs, search=None, propose=None):
        return TierResearcher(
            store=store,
            decomposer=_decomposer(*subs),
            searcher=search,
            proposer=propose,
            profiles=SEMI_PROFILES,
        )

    def test_a_sub_category_with_matches_is_not_searched(self) -> None:
        store = _Store()
        searched = []

        researcher = self._researcher(
            store,
            _sub("OSAT", OSAT),
            search=lambda q: searched.append(q) or SearchResults(query=q),
            propose=lambda *a: [],
        )
        researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)

        assert searched == []

    def test_a_sub_category_with_no_match_is_searched(self) -> None:
        store = _Store()
        searched = []

        researcher = self._researcher(
            store,
            _sub("EUV lithography", LITHO),
            search=lambda q: searched.append(q) or SearchResults(query=q),
            propose=lambda *a: [],
        )
        researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)

        assert len(searched) == 1
        assert "lithography" in searched[0].lower()

    def test_never_searched_and_searched_empty_are_distinguishable(self) -> None:
        store = _Store()
        researcher = self._researcher(
            store,
            _sub("OSAT", OSAT),
            _sub("EUV lithography", LITHO),
            search=lambda q: SearchResults(query=q),
            propose=lambda *a: [],
        )
        researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)

        by_label = {s["label"]: s for s in store.subs}
        assert by_label["OSAT"]["searched"] is False
        assert by_label["EUV lithography"]["searched"] is True
        assert by_label["EUV lithography"]["search_outcome"] == "ok"

    @pytest.mark.parametrize(
        "outcome",
        [SearchOutcome.UNCONFIGURED, SearchOutcome.EXHAUSTED, SearchOutcome.UNAVAILABLE],
    )
    def test_each_unavailable_search_is_recorded_as_itself(self, outcome) -> None:
        store = _Store()
        researcher = self._researcher(
            store,
            _sub("EUV lithography", LITHO),
            search=lambda q: SearchResults(query=q, outcome=outcome, reason="because"),
            propose=lambda *a: [],
        )

        result = researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)

        assert store.searched == [(1, outcome.value)]
        # It did not run, so it is not counted as a search that found nothing.
        assert result.searched == 0

    def test_no_search_provider_leaves_the_tier_unsearched(self) -> None:
        store = _Store()
        researcher = self._researcher(store, _sub("EUV lithography", LITHO))

        result = researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)

        assert result.searched == 0
        assert store.searched == []


class TestTheCaseThatMotivatedThisChange:
    """CG Power by decomposition, Kaynes by search, EUV lithography by neither.

    Measured against thirty real business descriptions from the price provider. Both halves are
    load-bearing and neither subsumes the other:

    * **CG Power** is reachable by description alone — it says "outsourced semiconductor
      assembly and testing" outright — but only once the tier is decomposed. The coarse tier
      tied it on one word with Infosys, Shree Cement and Voltas.
    * **Kaynes** is unreachable by description at any granularity. Its published description
      says "integrated electronics manufacturer" and its assembly plant post-dates it.
    * **EUV lithography** is reachable by nothing, correctly.
    """

    def test_the_coarse_tier_matches_cg_power_no_better_than_a_cement_maker(self) -> None:
        from app.themes.resolve import match_description

        matches, _ = match_description(
            "semiconductor fabrication plants and foundries", SEMI_UNIVERSE, SEMI_PROFILES
        )
        scores = dict((symbol, why) for symbol, why in matches)

        assert "CGPOWER" in scores
        # One shared word, and so is everyone else's.
        assert scores["CGPOWER"] == "semiconductor"

    def test_decomposition_makes_cg_power_the_strongest_match(self) -> None:
        from app.themes.resolve import match_description

        matches, _ = match_description(OSAT, SEMI_UNIVERSE, SEMI_PROFILES)

        assert matches[0][0] == "CGPOWER"

    def test_the_matcher_can_see_the_sentence_that_decides_it(self) -> None:
        """The regression that mattered: this sentence begins at character 938."""
        excerpt = focused_excerpt(SEMI_PROFILES["CGPOWER"].searchable, set(terms(OSAT)))

        assert "outsourced semiconductor assembly and testing" in excerpt

    def test_kaynes_is_unreachable_by_description_at_any_granularity(self) -> None:
        """Not a prompt problem and not a model problem. The fact is not in the data."""
        from app.themes.resolve import match_description

        for description in (
            "semiconductor fabrication plants and foundries",
            OSAT,
            "semiconductor packaging and assembly plants",
        ):
            matches, _ = match_description(description, SEMI_UNIVERSE, SEMI_PROFILES)
            top = [symbol for symbol, _ in matches[:3]]
            assert "KAYNES" not in top, description

    def test_search_finds_kaynes_and_the_universe_confirms_it(self) -> None:
        recorded = json.loads((FIXTURES / "osat_search.json").read_text("utf-8"))
        source = TavilySearchSource(api_key="k", client=lambda q, n: recorded)

        results = source.search(search_query("OSAT assembly and test", ""))
        # What a model would propose from these excerpts, names only.
        proposals = [
            _cited("Kaynes Technology"),
            _cited("CG Power"),
            _cited("Amkor Technology"),
            _cited("Tata"),
        ]

        validated = validate(proposals, SEMI_UNIVERSE)
        candidates = to_candidates(validated, "semi", tier=2)

        assert results.available
        assert "KAYNES" in {c.symbol for c in candidates}
        # And the decoys are each refused, for their own reason.
        outcomes = {v.proposal.company: v.outcome for v in validated}
        assert outcomes["Amkor Technology"] is ProposalOutcome.NOT_FOUND
        assert outcomes["Tata"] is ProposalOutcome.AMBIGUOUS

    def test_a_lithography_sub_category_surfaces_nobody(self) -> None:
        """The precise negative, worth as much as the names."""
        found, missing = resolve_tier(
            "semi", 2, "EUV lithography", [LITHO], SEMI_UNIVERSE, profiles=SEMI_PROFILES
        )

        assert found == []
        assert missing is not None

    def test_end_to_end_the_tier_yields_cg_power_and_kaynes_and_no_one_else(self) -> None:
        """The whole change in one test, both halves, offline."""
        store = _Store()
        recorded = json.loads((FIXTURES / "osat_search.json").read_text("utf-8"))
        source = TavilySearchSource(api_key="k", client=lambda q, n: recorded)

        def propose(sub_category, reasoning, excerpts):
            # What the model reads out of those excerpts: two real names and two decoys.
            return [
                {
                    "company": name,
                    "rationale": "named in the results",
                    "sources": [excerpts[0]["url"]],
                    "proposed_by": "test-model",
                }
                for name in ("Kaynes Technology", "Amkor Technology", "Tata")
            ]

        researcher = TierResearcher(
            store=store,
            decomposer=_decomposer(_sub("OSAT", OSAT), _sub("EUV lithography", LITHO)),
            searcher=source.search,
            proposer=propose,
            profiles=SEMI_PROFILES,
        )

        result = researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)
        symbols = {c.symbol for c in result.candidates}

        assert "CGPOWER" in symbols, "found by decomposition, from its own description"
        assert "KAYNES" in symbols, "found by search, unreachable any other way"
        # The refusals are recorded, and none of them became anything.
        refused = {p.proposal.company for p in store.proposals if not p.is_candidate}
        assert refused == {"Amkor Technology", "Tata"}

    def test_the_search_derived_candidate_is_graded_weakest_and_the_other_is_not(self) -> None:
        store = _Store()
        recorded = json.loads((FIXTURES / "osat_search.json").read_text("utf-8"))

        researcher = TierResearcher(
            store=store,
            decomposer=_decomposer(_sub("OSAT", OSAT), _sub("EUV lithography", LITHO)),
            searcher=TavilySearchSource(api_key="k", client=lambda q, n: recorded).search,
            proposer=lambda s, r, e: [
                {
                    "company": "Kaynes Technology",
                    "rationale": "named",
                    "sources": [e[0]["url"]],
                    "proposed_by": "m",
                }
            ],
            profiles=SEMI_PROFILES,
        )

        result = researcher.research("semi", [BACK_END_TIER], SEMI_UNIVERSE)
        grades = {c.symbol: c for c in result.candidates}

        assert grades["KAYNES"].exposure is Exposure.UNESTABLISHED
        assert "proposed by search" in grades["KAYNES"].exposure_basis


class TestNothingHereDecidesAnything:
    def test_no_candidate_carries_a_stance_or_a_score(self) -> None:
        validated = validate([_cited("Kaynes Technology")], INDIA)

        [candidate] = to_candidates(validated, "semi", tier=2)

        for forbidden in ("stance", "conviction", "score", "target", "rating"):
            assert not hasattr(candidate, forbidden)

    def test_exposure_is_a_named_grade_and_never_a_number(self) -> None:
        """A number would be sortable, and sorting candidates by exposure is a ranking."""
        validated = validate([_cited("Kaynes Technology")], INDIA)

        [candidate] = to_candidates(validated, "semi", tier=2)

        assert isinstance(candidate.exposure, Exposure)
        with pytest.raises(ValueError):
            float(candidate.exposure)

    def test_a_search_hit_is_never_a_platform_measurement(self) -> None:
        from app.tools.registry import ToolRegistry
        from app.tools.types import ToolContext

        registry = ToolRegistry.discover()
        result = registry.invoke(
            "web_search",
            {"query": "anything"},
            ToolContext(
                fetchers={
                    "web_search": lambda q: SearchResults(
                        query=q,
                        hits=(
                            type(
                                "H",
                                (),
                                {
                                    "as_dict": lambda self: {
                                        "title": "t",
                                        "url": "https://a",
                                        "excerpt": "e",
                                    }
                                },
                            )(),
                        ),
                    )
                }
            ),
        )

        assert result.ok
        assert all(item["measured_by_platform"] is False for item in result.items)
