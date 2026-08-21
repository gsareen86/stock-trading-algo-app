"""Reading the open web, under an allowance.

**Why the platform searches at all.** Everything else here reads a company's own words or its
own numbers. Those are the best sources and they have one gap that matters: a company's business
description is written *before* the thing you are looking for. Kaynes Technology is building a
semiconductor assembly plant; its published description says "integrated electronics
manufacturer" and nothing else, because that is what it was when the description was written. No
granularity of description matching reaches it. The plant is real, it is reported, and it is
reachable only by looking outside the platform's own data.

**The result is an excerpt, never an answer.** This returns what pages said, with their URLs.
Deciding which of those name a real participant is a separate step, and turning a name into a
candidate is a third one that happens against the platform's own universe. Keeping those apart
is the whole safety argument: a model may propose a name, and only the universe may confirm it.

**Three empties, and they are not the same thing.** Unconfigured means nobody set this up.
Exhausted means the allowance ran out this month. Unavailable means the provider could not be
reached. A reader looking at a tier with no Indian exposure needs to know which of those was
true before believing the emptiness, and a single empty list would tell them nothing.

``client`` is injectable and every test in this repository runs offline against recorded
results. No test may spend a request from a metered allowance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)

BASE_URL = "https://api.tavily.com/search"
SOURCE = "tavily"


class SearchOutcome(StrEnum):
    """Why a search returned what it returned."""

    OK = "ok"
    #: No API key. Nobody set this up.
    UNCONFIGURED = "unconfigured"
    #: The monthly allowance is spent. It will work again next month.
    EXHAUSTED = "exhausted"
    #: The provider could not be reached, or refused.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One page, as the provider described it."""

    title: str
    url: str
    excerpt: str

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url, "excerpt": self.excerpt}


@dataclass(frozen=True, slots=True)
class SearchResults:
    """What one query produced, and why it produced that."""

    query: str
    outcome: SearchOutcome = SearchOutcome.OK
    hits: tuple[SearchHit, ...] = ()
    reason: str | None = None

    @property
    def available(self) -> bool:
        """Whether the search actually ran. An empty *available* result is a real answer."""
        return self.outcome is SearchOutcome.OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "outcome": self.outcome.value,
            "available": self.available,
            "reason": self.reason,
            "hits": [h.as_dict() for h in self.hits],
        }


def unavailable(query: str, outcome: SearchOutcome, reason: str) -> SearchResults:
    return SearchResults(query=query, outcome=outcome, reason=reason)


@dataclass
class _Recorded:
    """Queries this process has already run, so one pass never pays twice for one question."""

    entries: dict[str, SearchResults] = field(default_factory=dict)


class TavilySearchSource:
    """Web search, rate-limited and metered.

    The allowance is counted on the way *out*, before the call: a request that was made and
    then failed still consumed a credit, and a counter that recorded only successes would
    drift under exactly the conditions that make an allowance matter.
    """

    def __init__(
        self,
        api_key: str | None,
        client=None,
        budget=None,
        limiter=None,
        max_results: int = 8,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._budget = budget
        self._limiter = limiter
        self._max_results = max_results
        self._timeout = timeout
        self._session: Any = None
        #: Within one run the same sub-category is often asked about twice. Repeating the
        #: query would spend a second credit for an answer already held.
        self._seen = _Recorded()

    @property
    def configured(self) -> bool:
        return bool(self._api_key) or self._client is not None

    def _call(self, query: str) -> dict[str, Any]:
        if self._client is not None:
            return self._client(query, self._max_results) or {}

        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"Content-Type": "application/json"})

        response = self._session.post(
            BASE_URL,
            json={
                "api_key": self._api_key,
                "query": query,
                "max_results": self._max_results,
                # Excerpts, not whole pages. A page of HTML would cost far more model time to
                # read than the answer is worth, and the excerpt is what carries the claim.
                "include_answer": False,
                "search_depth": "basic",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json() or {}

    def search(self, query: str) -> SearchResults:
        """Run one query. Never raises: a search that fails is a result that says so."""
        query = " ".join((query or "").split())
        if not query:
            return unavailable(query, SearchOutcome.UNAVAILABLE, "empty query")

        held = self._seen.entries.get(query)
        if held is not None:
            return held

        if not self.configured:
            return unavailable(
                query, SearchOutcome.UNCONFIGURED, "TAVILY_API_KEY is not configured"
            )

        if self._budget is not None and not self._budget.allow(f"search:{query[:120]}"):
            log.warning("search refused by monthly allowance: %s", query)
            return unavailable(
                query, SearchOutcome.EXHAUSTED, "monthly search allowance reached"
            )

        if self._limiter is not None:
            self._limiter.wait()

        try:
            payload = self._call(query)
        except Exception as exc:
            log.warning("search failed for %r: %s", query, exc)
            return unavailable(query, SearchOutcome.UNAVAILABLE, f"provider failed: {exc}")

        hits = []
        for row in payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            # A hit with no URL is not followable, and an unfollowable citation is not a
            # citation. It is dropped rather than shown as a source nobody can open.
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=str(row.get("title") or "").strip()[:300],
                    url=url,
                    excerpt=str(row.get("content") or "").strip()[:1200],
                )
            )

        result = SearchResults(query=query, outcome=SearchOutcome.OK, hits=tuple(hits))
        self._seen.entries[query] = result
        return result
