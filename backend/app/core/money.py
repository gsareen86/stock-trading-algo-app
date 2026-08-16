"""The one place dollars become rupees.

This platform reports in INR — every price, threshold and position in it already does. LLM
vendors bill in USD, and LiteLLM computes `response_cost` from a USD price table, so the LLM
ledger is the single place a foreign currency enters the system.

It is treated the same way yfinance's `.NS` suffix is treated in `app.domain.instrument`: a
provider artefact, translated at one seam, never leaked past it. Concretely, `llm_calls`
stores the dollar amount the provider will actually charge — a row that reconciles against an
invoice — and conversion happens when that ledger is *read* for reporting. Storing rupees
would mean storing a number multiplied by whatever rate was configured that day, with the rate
discarded, which reconciles against nothing and cannot be undone.

The rate is an operator-set constant rather than a live feed. A network dependency and a
staleness question are a poor trade to refine a figure whose input is already a rounded
estimate from a price table, and whose typical magnitude is a fraction of a rupee. The
consequence is stated rather than hidden: changing the rate recomputes historical rupee
figures too. That is the honest reading of "what would this have cost me", and every API
response carries the rate used, so any figure inverts back to the stored dollars.
"""

from __future__ import annotations

#: Rupees to the dollar when the operator sets none. Approximate by construction — see the
#: module docstring on why precision here would be false comfort.
DEFAULT_USD_INR_RATE = 88.0

#: A paisa. Amounts below this are real but not meaningfully renderable as a decimal.
PAISA = 0.01

RUPEE_SIGN = "₹"


def usd_to_inr(amount_usd: float | None, rate: float) -> float | None:
    """Convert for reporting. ``None`` — an unpriced local call — stays ``None``.

    Unpriced must never become ``0.0`` on the way out: the ledger's whole distinction is
    priced versus unpriced, and a free call is not a call that cost nothing to buy.
    """
    if amount_usd is None:
        return None
    return round_inr(amount_usd * rate)


def inr_to_usd(amount_inr: float | None, rate: float) -> float | None:
    """Convert an operator-supplied rupee figure into the ledger's currency.

    Used for the daily cap: the operator sets rupees, the budget compares dollars, because it
    sums a dollar column. Deliberately *not* rounded to paise — this feeds a comparison, not a
    display, and rounding a threshold moves it.
    """
    if amount_inr is None:
        return None
    return amount_inr / rate


def round_inr(amount: float) -> float:
    """Round to paise, the smallest unit that means anything."""
    return round(amount, 2)
