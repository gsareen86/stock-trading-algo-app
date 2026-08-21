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


def read_documents(
    symbols: list[str],
    reader,
    extractor,
    store,
    period: str,
    kind: SourceKind = SourceKind.COMMENTARY,
    sectors: dict[str, str] | None = None,
    limit: int | None = None,
) -> SourceResult:
    """Read documents with a model and persist what it read.

    **A document already read is skipped**, which is what makes a weekly run affordable: a
    local model takes minutes per document and a published document never changes. Skipping is
    not a cache optimisation, it is the reason counts stay stable — re-reading would produce a
    slightly different answer every time and the thresholds would drift underneath them.

    ``reader`` yields ``(text, source_ref)`` per symbol; ``extractor`` is the concept-extraction
    tool; ``store`` persists. All three are injected so tests run offline and so the caller
    decides how many documents a run may spend time on.
    """
    sectors = sectors or {}
    read = 0
    attempted = 0

    for symbol in symbols[: limit or len(symbols)]:
        try:
            documents = reader(symbol) or []
        except Exception as exc:
            log.debug("document read failed for %s: %s", symbol, exc)
            continue

        for text, source_ref in documents:
            if not text or store.has_read(source_ref):
                continue
            attempted += 1

            extracted = extractor(symbol, period, text, source_ref)
            if not extracted:
                continue

            store.record(
                [
                    {**concept, "kind": kind.value, "sector": sectors.get(symbol)}
                    for concept in extracted
                ]
            )
            read += 1

    # References come from the store rather than from this pass: a run counts everything ever
    # read, not only what it happened to read today. A week with no new filings still has
    # themes.
    return SourceResult(
        references=[r for r in store.references() if r.kind is kind],
        documents_read=read,
        # Nothing attempted is not the same as everything failing. A run that found no new
        # documents read nothing and is fine; a run that tried and failed on all of them is a
        # source that is down.
        available=read > 0 or attempted == 0,
    )


def policy_references(
    classifier,
    fetcher=None,
    hours: int = DEFAULT_POLICY_HOURS,
    period: str | None = None,
) -> SourceResult:
    """Concepts appearing in policy and scheme coverage.

    **Unattributed by construction.** A scheme announcement is not a company saying anything, so
    these references carry no symbol and cannot contribute to breadth — breadth counts distinct
    *companies*, and letting one budget announcement inflate it would be the loud-month failure
    the thresholds exist to prevent. Policy corroborates a theme and is visible in its source
    list; it never manufactures one.

    ``classifier`` takes headlines and returns those that report government action, each with
    the industry it affects. That subject *is* the concept — the policy's own description of
    what it touches, rather than a word somebody guessed would appear.
    """
    period = period or now_utc().strftime("%b %Y")
    entries, feeds_answered = _feed_entries(fetcher, hours)
    if not entries:
        return SourceResult(references=[], documents_read=0, available=feeds_answered)

    headlines = [f"{title}. {summary}"[:300] for title, summary, _, _ in entries]
    try:
        classified = classifier(headlines)
    except Exception as exc:
        log.warning("policy classification unavailable: %s", exc)
        return SourceResult(references=[], documents_read=len(entries), available=False)

    references: list[Reference] = []
    for result in classified:
        index = result.get("index")
        if not isinstance(index, int) or not 0 <= index < len(entries):
            continue
        subject = (result.get("subject") or "").strip().lower()
        if not subject:
            continue
        _, _, link, source = entries[index]
        references.append(
            Reference(
                # No company. `ThemeEvidence.companies` ignores unattributed references, so
                # this can support a theme and can never inflate its breadth.
                symbol="",
                concept=subject,
                period=period,
                kind=SourceKind.POLICY,
                source_ref=link or f"feed://{source}",
                excerpt=result.get("headline", "")[:400],
            )
        )

    return SourceResult(
        references=references, documents_read=len(entries), available=True
    )


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
