"""NSE surveillance measures.

ASM (Additional Surveillance Measure) and GSM (Graded Surveillance Measure) name stocks the
exchange has flagged, typically for volatility or governance concerns. A stock under
surveillance is one this platform should not be forming a view on at all — an eligibility
question, decided before any strategy runs, rather than an opinion about the setup.

Bundled rather than fetched: NSE serves these reports behind a browser-shaped session and
blocks anything else. That makes the list's **age** the thing to watch, so it is reported
rather than assumed — the same treatment the holiday calendar gets, and for the same reason a
holiday file that ran out in December is not discovered until a Tuesday in January.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

RESOURCES = Path(__file__).parent / "resources"
SURVEILLANCE_FILE = RESOURCES / "surveillance.json"

#: Beyond this, the list is old enough that its silence means nothing. NSE revises these
#: monthly, so a quarter without an update is a list nobody is maintaining.
STALE_AFTER_DAYS = 90


@dataclass(frozen=True, slots=True)
class SurveillanceList:
    """Flagged symbols, and how old the knowledge is."""

    asm: frozenset[str]
    gsm: frozenset[str]
    as_of: date | None
    source: str

    @property
    def symbols(self) -> frozenset[str]:
        return self.asm | self.gsm

    def measure_for(self, symbol: str) -> str | None:
        """Which measure a symbol is under, if any."""
        upper = symbol.strip().upper()
        if upper in self.asm:
            return "ASM"
        if upper in self.gsm:
            return "GSM"
        return None

    def age_days(self, today: date) -> int | None:
        return None if self.as_of is None else (today - self.as_of).days

    def is_stale(self, today: date) -> bool:
        """An unknown age counts as stale: it cannot be shown to be current."""
        age = self.age_days(today)
        return age is None or age > STALE_AFTER_DAYS

    def as_dict(self, today: date) -> dict:
        return {
            "asm_count": len(self.asm),
            "gsm_count": len(self.gsm),
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "age_days": self.age_days(today),
            "stale": self.is_stale(today),
            "source": self.source,
        }


@lru_cache(maxsize=2)
def load(path: str | None = None) -> SurveillanceList:
    """Read the bundled list. A missing or unreadable file yields an empty, stale list.

    Empty rather than an exception, because a screen with no surveillance data is degraded
    rather than broken — and `stale` is what says so.
    """
    target = Path(path) if path else SURVEILLANCE_FILE
    try:
        payload = json.loads(target.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return SurveillanceList(frozenset(), frozenset(), None, "")

    raw_date = payload.get("as_of")
    try:
        as_of = date.fromisoformat(raw_date) if raw_date else None
    except ValueError:
        as_of = None

    return SurveillanceList(
        asm=frozenset(s.strip().upper() for s in payload.get("asm", ())),
        gsm=frozenset(s.strip().upper() for s in payload.get("gsm", ())),
        as_of=as_of,
        source=payload.get("source", ""),
    )
