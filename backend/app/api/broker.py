"""Zerodha, read-only.

Connecting is a **browser login you complete each day** — Kite authorises a session rather
than issuing a credential, and the exchange requires a fresh login daily. That is a property of
Zerodha, not a limitation this could design away, so the endpoints report session state plainly
rather than pretending a connection is durable.

Nothing here can place, modify or cancel an order. The platform stays paper-only; real holdings
are read so the strategies can be asked what they think of them.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_settings
from app.broker.holdings import parse_holdings, summarise
from app.broker.session import BrokerUnavailable, KiteSession
from app.core.settings import Settings

router = APIRouter(prefix="/broker", tags=["broker"])


def get_session(request: Request) -> KiteSession:
    return request.app.state.broker


#: What to do about an unauthorised session, said in the response rather than a document —
#: "why is this not authorised" is the first question anyone will have.
NEXT_STEP = (
    "Call POST /broker/connect and open the returned link to sign in to Zerodha. Sessions "
    "expire daily, as the exchange requires, so this is a morning step rather than one-time "
    "setup."
)


@router.get("/status")
async def status(session: Annotated[KiteSession, Depends(get_session)]) -> dict[str, Any]:
    body = session.status()
    if not body["authorised"]:
        body["next_step"] = NEXT_STEP
    return body


@router.post("/refresh")
async def refresh(session: Annotated[KiteSession, Depends(get_session)]) -> dict[str, Any]:
    """Drop cached answers so the next read hits Zerodha.

    Holdings are otherwise served from a cache for `refresh_minutes`, which keeps a page load
    from costing a round trip. This is the end-of-day (or on-demand) override.
    """
    session.invalidate()
    return {"refreshed": True, "status": session.status()}


@router.post("/connect")
async def connect(
    session: Annotated[KiteSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Start a session and return the Zerodha login link to open in a browser."""
    try:
        login_url = await session.begin_login()
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "login_url": login_url,
        "instructions": (
            "Open this link now and sign in to Zerodha. It expires within minutes — a link "
            "left sitting returns 'invalid authorize session', which reads as a broken "
            "integration rather than a stale link. Once signed in, the session lasts until "
            "Zerodha expires it, which it does daily as the exchange requires."
        ),
        # Said in the response because the failure it prevents is indistinguishable from a
        # bug when you meet it an hour later.
        "expires": "within minutes — generate it when you are ready to use it",
        "read_only": True,
        "status": session.status(),
    }


@router.post("/disconnect")
async def disconnect(session: Annotated[KiteSession, Depends(get_session)]) -> dict[str, Any]:
    await session.disconnect()
    return {"status": session.status()}


@router.get("/holdings")
async def holdings(session: Annotated[KiteSession, Depends(get_session)]) -> dict[str, Any]:
    """Long-term holdings as Zerodha reports them.

    A 409 here means the session lapsed, which is an ordinary daily occurrence rather than a
    fault — the client turns it into "reconnect", not "something broke".
    """
    try:
        payload = await session.call("get_holdings")
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return summarise(parse_holdings(payload))


@router.get("/positions")
async def positions(session: Annotated[KiteSession, Depends(get_session)]) -> dict[str, Any]:
    try:
        payload = await session.call("get_positions")
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return summarise(parse_holdings(payload))


@router.get("/verdicts")
async def verdicts_on_holdings(
    request: Request,
    session: Annotated[KiteSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """What every strategy now thinks of what you actually hold.

    This is what reading the broker is *for*. It needs no merging: real holdings supply the
    list of symbols, the strategies answer independently, and the paper ledger is untouched.
    """
    from app.api.verdicts import _fundamentals_source, _price_source, _serialise
    from app.domain.instrument import Instrument
    from app.strategies.protocols import StrategyContext

    try:
        payload = await session.call("get_holdings")
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    held = parse_holdings(payload)
    if not held:
        return {"holdings": 0, "verdicts": [], "note": "no holdings reported"}

    registry = request.app.state.strategies
    context = StrategyContext(
        price_source=_price_source(request, settings),
        fundamentals_source=_fundamentals_source(request),
    )

    produced = []
    for holding in held[:25]:
        instrument = Instrument(holding.symbol)
        for strategy_id in registry.ids():
            definition = registry.get(strategy_id)
            try:
                produced.append(_serialise(definition.strategy.evaluate(instrument, context)))
            except Exception:  # pragma: no cover - one name must not fail the request
                continue

    return {
        "holdings": len(held),
        # One entry per strategy per holding. No combined view, exactly as everywhere else.
        "verdicts": produced,
        "count": len(produced),
        "note": "Verdicts on real holdings. Nothing was written to the paper books.",
    }
