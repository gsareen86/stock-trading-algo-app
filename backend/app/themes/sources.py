"""Reading the sources a theme run counts.

Two adapters, and the runner composes them. Each records whether it could read anything at all,
because that distinction is what stops a broken downloader looking like a quiet market.

**Order books are not in the financials endpoint**, which the spec assumed and which turned out
to be wrong: `quarter_results` carries sales, expenses, margins, profit and EPS, and nothing
about order inflow. Order books are disclosed in *commentary* — "order inflow was up 40% this
quarter" is a sentence in a transcript, not a line item — so the commentary adapter is where
that signal actually lives, and `order_book` is one of the concepts it extracts.

**Policy is read from financial news in English, not from the government's own wire.** PIB
publishes press releases, and neither route reaches them usefully: its release listing is an
ASP.NET postback page with no links in the served HTML, and its RSS returns Hindi regardless of
the language parameter, which English phrase matching cannot read. Indian financial media cover
scheme and budget announcements in English within hours, the platform already reads those
feeds, and using them costs nothing new. Recorded here so the next person does not spend the
same afternoon on PIB.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.clock import now_utc
from app.domain.themes import Reference, SourceKind
from app.themes.detect import extract

log = logging.getLogger(__name__)

FEEDS_FILE = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "news_research"
    / "resources"
    / "feeds.json"
)

#: How far back a policy sweep looks. Themes move over quarters; a fortnight of headlines is
#: plenty to notice a scheme announcement without drowning the counts in daily noise.
DEFAULT_POLICY_HOURS = 336


@dataclass(frozen=True, slots=True)
class SourceResult:
    """What one adapter produced, and whether it managed to read anything."""

    references: list[Reference]
    documents_read: int = 0
    available: bool = True


def commentary_references(
    symbols: list[str],
    reader,
    period: str,
    sectors: dict[str, str] | None = None,
    limit: int | None = None,
) -> SourceResult:
    """Concepts a set of companies discussed in their own commentary.

    The highest-signal source the platform has: "we are seeing unprecedented demand for X"
    appears in a transcript quarters before it appears in a price, and this is also where order
    inflow is disclosed.

    ``reader`` takes a symbol and returns document text, or nothing. It is injected so tests run
    offline and so the caller decides how many documents a run may fetch — commentary is
    scrape-only and slow, and a run over five hundred names would take hours.
    """
    sectors = sectors or {}
    references: list[Reference] = []
    read = 0
    failures = 0

    for symbol in symbols[: limit or len(symbols)]:
        try:
            document = reader(symbol)
        except Exception as exc:
            log.debug("commentary read failed for %s: %s", symbol, exc)
            failures += 1
            continue
        if not document:
            failures += 1
            continue

        text, source_ref = document
        read += 1
        references.extend(
            extract(
                symbol=symbol,
                period=period,
                text=text,
                kind=SourceKind.COMMENTARY,
                source_ref=source_ref,
                sector=sectors.get(symbol),
            )
        )

    # Available means "this adapter read something". Every attempt failing is a source that is
    # down, and a run needs to say so rather than quietly reporting fewer themes.
    return SourceResult(references=references, documents_read=read, available=read > 0)


def policy_references(
    fetcher=None,
    hours: int = DEFAULT_POLICY_HOURS,
    period: str | None = None,
) -> SourceResult:
    """Concepts appearing in policy and scheme coverage.

    **Unattributed by construction.** A scheme announcement is not a company saying anything, so
    these references carry no symbol and cannot contribute to breadth — breadth counts distinct
    *companies*, and letting a single budget announcement inflate it would be the "loud month"
    failure the thresholds exist to prevent. Policy corroborates a theme and is visible in its
    source list; it never manufactures one.
    """
    period = period or now_utc().strftime("%b %Y")
    entries, available = _feed_entries(fetcher, hours)

    references: list[Reference] = []
    for title, summary, link, source in entries:
        text = f"{title}. {summary}"
        if not _looks_like_policy(text):
            continue
        references.extend(
            extract(
                # No company. `ThemeEvidence.companies` ignores unattributed references, so
                # this can support a theme and can never inflate its breadth.
                symbol="",
                period=period,
                text=text,
                kind=SourceKind.POLICY,
                source_ref=link or f"feed://{source}",
            )
        )

    return SourceResult(
        references=references, documents_read=len(entries), available=available
    )


def filing_references(
    symbols: list[str],
    reader,
    period: str,
    sectors: dict[str, str] | None = None,
    limit: int | None = None,
) -> SourceResult:
    """Concepts a company disclosed to the exchange.

    Weaker signal than commentary and stronger provenance. A transcript is management talking;
    a filing is the thing itself — a new plant, a capacity addition, an order won — and it is
    where a capex commitment appears before anyone discusses it on a call.

    ``reader`` takes a symbol and returns ``(text, source_ref)`` pairs, one per filing, so a
    company's several announcements each get read. Injected for the same reasons as the others.
    """
    sectors = sectors or {}
    references: list[Reference] = []
    read = 0

    for symbol in symbols[: limit or len(symbols)]:
        try:
            filings = reader(symbol) or []
        except Exception as exc:
            log.debug("filing read failed for %s: %s", symbol, exc)
            continue

        for text, source_ref in filings:
            if not text:
                continue
            read += 1
            references.extend(
                extract(
                    symbol=symbol,
                    period=period,
                    text=text,
                    kind=SourceKind.FILING,
                    source_ref=source_ref,
                    sector=sectors.get(symbol),
                )
            )

    return SourceResult(references=references, documents_read=read, available=read > 0)


#: Words that mark an item as being about government action rather than about a company. Kept
#: deliberately narrow: a policy reference that is really a company story would attribute a
#: scheme to a market move.
_POLICY_MARKERS = (
    "scheme",
    "ministry",
    "cabinet",
    "government",
    "policy",
    "budget",
    "subsidy",
    "incentive",
    "tender",
    "mandate",
    "notification",
    "parliament",
)


def _looks_like_policy(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _POLICY_MARKERS)


def _feed_entries(fetcher, hours: int) -> tuple[list[tuple[str, str, str, str]], bool]:
    """(title, summary, link, source) from the configured feeds, and whether any answered."""
    if fetcher is not None:
        # An injected fetcher signals a dead source by raising, exactly as the commentary
        # reader does. An empty list means "the feeds answered and had nothing recent",
        # which is a different fact and must not be reported as unavailable.
        try:
            return fetcher(hours), True
        except Exception as exc:
            log.debug("injected feed fetcher failed: %s", exc)
            return [], False

    try:
        import feedparser
        import requests
    except ImportError:  # pragma: no cover - both are base dependencies
        return [], False

    try:
        feeds = json.loads(FEEDS_FILE.read_text("utf-8")).get("feeds", [])
    except Exception as exc:
        log.warning("feed list unreadable: %s", exc)
        return [], False

    cutoff = now_utc().timestamp() - hours * 3600
    entries: list[tuple[str, str, str, str]] = []
    answered = 0

    for feed in feeds:
        try:
            response = requests.get(
                feed["url"],
                headers={"User-Agent": "swing-lt-platform/0.1 (personal research)"},
                timeout=15,
            )
            parsed = feedparser.parse(response.content)
        except Exception as exc:
            log.debug("feed %s unavailable: %s", feed.get("source"), exc)
            continue
        if not parsed.entries:
            continue
        answered += 1

        for entry in parsed.entries:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published is not None:
                import calendar

                if calendar.timegm(published) < cutoff:
                    continue
            entries.append(
                (
                    entry.get("title", ""),
                    entry.get("summary", ""),
                    entry.get("link", ""),
                    feed.get("source", "feed"),
                )
            )

    return entries, answered > 0
