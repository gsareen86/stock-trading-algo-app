"""Read-only Zerodha integration.

Two properties carry it: **real holdings never enter the paper ledger**, and **nothing here can
place an order**. The first keeps the ledger able to answer "how would following these
strategies have gone"; the second keeps principle 7 true now that a real broker is reachable.
"""

from __future__ import annotations

import json

import pytest

from app.broker.holdings import BrokerHolding, parse_holdings, summarise
from app.broker.session import BrokerUnavailable, KiteSession

KITE_HOLDINGS = json.dumps(
    [
        {
            "tradingsymbol": "RELIANCE",
            "exchange": "NSE",
            "quantity": 10,
            "average_price": 1400.0,
            "last_price": 1316.0,
            "pnl": -840.0,
        },
        {
            "tradingsymbol": "TCS",
            "exchange": "NSE",
            "quantity": 5,
            "average_price": 3100.0,
            "last_price": 3200.0,
            "pnl": 500.0,
        },
    ]
)


class TestParsing:
    def test_holdings_are_read(self) -> None:
        held = parse_holdings(KITE_HOLDINGS)

        assert [h.symbol for h in held] == ["RELIANCE", "TCS"]
        assert held[0].quantity == 10
        assert held[0].average_price == pytest.approx(1400.0)

    def test_alternate_field_spellings_are_accepted(self) -> None:
        """A remote schema is not ours to depend on."""
        payload = json.dumps([{"symbol": "INFY", "qty": 3, "avg_price": 1500.0, "ltp": 1600.0}])

        held = parse_holdings(payload)

        assert held[0].symbol == "INFY"
        assert held[0].quantity == 3
        assert held[0].last_price == pytest.approx(1600.0)

    def test_a_wrapped_list_is_found(self) -> None:
        payload = json.dumps({"holdings": json.loads(KITE_HOLDINGS)})

        assert len(parse_holdings(payload)) == 2

    def test_non_json_yields_nothing_rather_than_raising(self) -> None:
        assert parse_holdings("Please log in first using the login tool") == []
        assert parse_holdings("") == []

    def test_zero_quantity_rows_are_dropped(self) -> None:
        payload = json.dumps([{"tradingsymbol": "X", "quantity": 0, "average_price": 10.0}])

        assert parse_holdings(payload) == []

    def test_a_missing_price_leaves_value_unknown(self) -> None:
        holding = BrokerHolding("X", "NSE", 10, 100.0, None, None)

        assert holding.value is None


class TestSummary:
    def test_totals_are_reported(self) -> None:
        body = summarise(parse_holdings(KITE_HOLDINGS))

        assert body["count"] == 2
        assert body["invested"] == pytest.approx(10 * 1400.0 + 5 * 3100.0)

    def test_a_missing_price_withholds_the_total(self) -> None:
        """A partial total is a misleading one — the same rule the paper book follows."""
        held = [
            BrokerHolding("A", "NSE", 1, 10.0, 12.0, None),
            BrokerHolding("B", "NSE", 1, 10.0, None, None),
        ]

        assert summarise(held)["market_value"] is None

    def test_broker_pnl_is_labelled_as_theirs(self) -> None:
        """This platform's P&L is gross and computed differently; one label would invite
        comparing two numbers that are not comparable."""
        body = summarise(parse_holdings(KITE_HOLDINGS))

        assert "pnl_reported_by_broker" in body["holdings"][0]
        assert body["source"] == "zerodha"

    def test_the_summary_says_these_are_not_paper_positions(self) -> None:
        body = summarise(parse_holdings(KITE_HOLDINGS))

        assert "never mixed into the paper books" in body["note"]


class TestReadOnly:
    async def test_a_mutating_tool_is_refused_before_any_call(self) -> None:
        """Discovery already filters these; this refuses again, because this module must not
        become the way an order reaches a broker."""
        session = KiteSession()

        for tool in ("place_order", "cancel_order", "modify_order", "place_gtt_order"):
            with pytest.raises(BrokerUnavailable, match="read-only"):
                await session.call(tool)

    async def test_calling_without_a_session_is_refused(self) -> None:
        with pytest.raises(BrokerUnavailable, match="not connected"):
            await KiteSession().call("get_holdings")

    def test_status_reports_read_only(self) -> None:
        assert KiteSession().status()["read_only"] is True

    def test_connected_and_authorised_are_distinct(self) -> None:
        """Connected-but-unauthorised is the normal state while a browser login is pending."""
        status = KiteSession().status()

        assert status["connected"] is False
        assert status["authorised"] is False


class TestHoldingsNeverEnterTheLedger:
    def test_the_broker_package_never_writes_a_trade(self) -> None:
        """The paper ledger answers "how would following these strategies have gone".
        Recording holdings you acquired elsewhere as fills destroys that question."""
        from tests.conftest import source_of

        source = source_of("broker")

        assert "Ledger" not in source
        assert ".fill(" not in source
        assert "TradeRow" not in source

    def test_broker_holdings_are_not_positions(self) -> None:
        """Different types on purpose: one is derived from trades we recorded, the other is a
        snapshot someone else computed."""
        from app.domain.position import Position

        assert BrokerHolding is not Position
        assert not issubclass(BrokerHolding, Position)


class TestBrokerApi:
    def test_status_is_readable_without_a_connection(self, client) -> None:
        body = client.get("/broker/status").json()

        assert body["connected"] is False
        assert body["read_only"] is True

    def test_holdings_without_a_session_is_a_conflict(self, client) -> None:
        """A lapsed session is an ordinary daily occurrence, not a fault."""
        response = client.get("/broker/holdings")

        assert response.status_code == 409
        assert "login" in response.json()["detail"].lower()

    def test_the_broker_requires_authentication(self, settings) -> None:
        from fastapi.testclient import TestClient

        from app.main import create_app

        anonymous = TestClient(create_app(settings))

        assert anonymous.get("/broker/holdings").status_code == 401
        assert anonymous.post("/broker/connect").status_code == 401

    def test_no_order_endpoint_exists(self, client) -> None:
        """The API surface must not offer one either."""
        paths = client.get("/openapi.json").json()["paths"]

        for path in paths:
            assert "order" not in path.lower()


class TestHostedMcpLimitationIsDeclared:
    """Verified empirically: the hosted server mints a new session per connection.

    A backend cannot rejoin a browser login there, so the platform says so rather than
    leaving "always unauthorised" to look like a configuration mistake.
    """

    def test_status_explains_why_it_is_unauthorised(self, client) -> None:
        body = client.get("/broker/status").json()

        assert body["authorised"] is False
        assert "known_limitation" in body
        assert "session per connection" in body["known_limitation"]

    def test_the_limitation_names_the_paths_that_do_work(self, client) -> None:
        detail = client.get("/broker/status").json()["known_limitation"]

        assert "self-hosted" in detail
        assert "Kite Connect REST" in detail
