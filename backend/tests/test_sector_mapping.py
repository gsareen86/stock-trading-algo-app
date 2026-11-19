"""Every listed company resolves to the sector index that describes its business.

The map is a data file, so these tests pin the decisions in it: which NSE industries go where,
which companies are overridden and why, and that short terms never match inside longer words.
"""

from __future__ import annotations

import json

import pytest

from app.data import sectors
from app.data.universe import TOTAL_MARKET_FALLBACK_FILE
from app.domain.instrument import Instrument


def _key(symbol: str, industry: str | None) -> str | None:
    found = sectors.for_instrument(Instrument(symbol, sector=industry))
    return found.key if found else None


class TestNseIndustries:
    @pytest.mark.parametrize(
        ("industry", "expected"),
        [
            ("Chemicals", "Commodities"),
            ("Fertilizers & Agrochemicals", "Commodities"),
            ("Forest Materials", "Commodities"),
            ("Telecommunication", "Infrastructure"),
            ("Services", "Infrastructure"),
            ("Financial Services", "FinancialServices"),
            ("Consumer Services", "Consumption"),
            ("IT Services", "IT"),
        ],
    )
    def test_industry_maps_to_its_index(self, industry: str, expected: str) -> None:
        assert _key("ANYCO", industry) == expected

    def test_a_short_term_never_matches_inside_a_longer_word(self) -> None:
        """"it" sits inside "utilities"; power utilities belong with energy, not IT."""
        assert _key("ANYCO", "Utilities") == "Energy"

    def test_a_conglomerate_maps_to_nothing(self) -> None:
        assert _key("GODREJIND", "Diversified") is None


class TestSymbolOverrides:
    @pytest.mark.parametrize(
        ("symbol", "industry", "expected"),
        [
            ("FSL", "Services", "IT"),
            ("ECLERX", "Services", "IT"),
            ("ROUTE", "Telecommunication", "IT"),
            ("CMSINFO", "Services", "FinancialServices"),
            ("WEWORK", "Services", "Realty"),
            ("ADANIPORTS", "Services", "Infrastructure"),  # not overridden: transport
            ("BHARTIARTL", "Telecommunication", "Infrastructure"),
        ],
    )
    def test_override_or_industry(self, symbol: str, industry: str, expected: str) -> None:
        assert _key(symbol, industry) == expected

    def test_every_override_names_a_real_index_and_a_reason(self) -> None:
        indices = {s.key for s in sectors.all_sector_indices()}
        for symbol, (key, reason) in sectors.symbol_overrides().items():
            assert key in indices, symbol
            assert reason.strip(), symbol


class TestCoverage:
    def test_every_bundled_company_but_the_conglomerate_has_a_sector(self) -> None:
        rows = json.loads(TOTAL_MARKET_FALLBACK_FILE.read_text("utf-8"))["instruments"]
        unmapped = [r["symbol"] for r in rows if _key(r["symbol"], r.get("industry")) is None]
        assert unmapped == ["GODREJIND"]

    def test_every_index_has_an_nse_name(self) -> None:
        names = sectors.nse_names()
        assert {s.key for s in sectors.all_sector_indices()} <= set(names)


class TestVerification:
    def test_an_index_without_history_fails_the_check(self) -> None:
        from app.data.fake import FakePriceSource
        from app.data.verify_sector_indices import MIN_BARS, verify

        known = {s.ticker for s in sectors.all_sector_indices()} - {"^CNXCMDT"}
        rows = verify(FakePriceSource(bars=400, known=known))
        by_key = {key: (bars, usable) for key, _, bars, usable in rows}
        assert by_key["Commodities"] == (0, False)
        assert all(usable for key, (bars, usable) in by_key.items() if key != "Commodities")
        assert MIN_BARS > 0
