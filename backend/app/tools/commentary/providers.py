"""Finding a company's management commentary, and reading it.

**One provider, not two.** The design allowed for a licensed API serving transcripts and a
document pipeline behind it. The API was checked against a live key and serves no transcripts
at all — its full company payload contains no transcript, concall, document or PDF of any
kind, and it publishes no spec in which another endpoint might hide. So the seam remains and
the pipeline is the capability. If a licensed source appears, it slots in here and nothing
above this file changes.

**Resolved past the aggregator wherever possible.** Screener lists the documents; the documents
themselves are mostly hosted by BSE or by the company's own investor-relations site. Following
the link to its origin is both more durable — an aggregator's markup changes, an exchange's
document URL does not — and less load on a free service nobody is paying.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.core.rate_limit import RateLimiter
from app.domain.financials import parse_period

log = logging.getLogger(__name__)

SCREENER_COMPANY_URL = "https://www.screener.in/company/{symbol}/consolidated/"

#: Identifies the client honestly. A free service being read by a program is owed at least
#: the ability to see who is doing it.
USER_AGENT = "swing-lt-platform/0.1 (personal equity research; contact via repository)"

#: Hosts whose documents are the primary record rather than a copy of one.
EXCHANGE_HOSTS = ("bseindia.com", "nseindia.com")

DEFAULT_MIN_INTERVAL_SECONDS = 2.0

#: Characters per section. A 40-page transcript does not fit a 12B model's context, and a tool
#: that returns one unusable blob is correct in tests and useless in practice.
DEFAULT_SECTION_CHARS = 6000


@dataclass(frozen=True, slots=True)
class Document:
    """One located document, before it has been read."""

    symbol: str
    kind: str
    url: str
    #: The provider's own period label, e.g. `Jul 2026`.
    period: str | None = None
    period_end: date | None = None

    @property
    def is_exchange_hosted(self) -> bool:
        return any(host in self.url.lower() for host in EXCHANGE_HOSTS)


class ScreenerDocumentLocator:
    """Finds transcript and report links on a company's aggregator page.

    ``fetcher`` is injectable so tests parse recorded markup instead of reaching the network.
    """

    def __init__(
        self,
        fetcher=None,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        timeout: float = 25.0,
    ) -> None:
        self._fetcher = fetcher
        self._limiter = RateLimiter(min_interval_seconds)
        self._timeout = timeout

    def _html(self, symbol: str) -> str | None:
        url = SCREENER_COMPANY_URL.format(symbol=symbol)
        if self._fetcher is not None:
            return self._fetcher(url)

        import requests

        self._limiter.wait()
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=self._timeout,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text

    def locate(self, symbol: str) -> list[Document]:
        """Documents for a symbol, newest first. Empty on any failure — never raises."""
        try:
            html = self._html(symbol)
        except Exception as exc:
            log.warning("document lookup failed for %s: %s", symbol, exc)
            return []
        if not html:
            return []
        try:
            return parse_documents(symbol, html)
        except Exception as exc:
            log.warning("document markup unparseable for %s: %s", symbol, exc)
            return []


def parse_documents(symbol: str, html: str) -> list[Document]:
    """Transcript and annual-report links out of a company page.

    Written against real markup: concalls live in `div.documents.concalls`, one `li` per
    period, each carrying a date and links labelled `Transcript`, `PPT` and `REC`. Only the
    transcript is prose — a slide deck is not commentary and a recording is not text.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    found: list[Document] = []

    for box, kind, wanted in (
        ("concalls", "transcript", ("transcript",)),
        ("annual-reports", "annual_report", ("financial", "annual", "from bse", "from nse")),
    ):
        container = soup.find(
            "div", class_=lambda c, b=box: bool(c) and "documents" in c and b in c
        )
        if container is None:
            continue

        for row in container.find_all("li"):
            label = _row_period(row)
            for link in row.find_all("a", href=True):
                text = link.get_text(" ", strip=True).lower()
                if not any(term in text for term in wanted):
                    continue
                url = link["href"].strip()
                if not url.lower().startswith("http"):
                    continue
                found.append(
                    Document(
                        symbol=symbol,
                        kind=kind,
                        url=url,
                        period=label,
                        period_end=parse_period(label) if label else None,
                    )
                )

    # Newest first, and exchange-hosted before an equivalent elsewhere: for the same period a
    # BSE URL outlives a company microsite reorganisation.
    found.sort(
        key=lambda d: (
            d.period_end is not None,
            d.period_end or date.min,
            d.is_exchange_hosted,
        ),
        reverse=True,
    )
    return found


_PERIOD = re.compile(r"^[A-Z][a-z]{2}\s+\d{4}$")


def _row_period(row) -> str | None:
    """The `Jul 2026` label a document row carries, if it has one."""
    for node in row.find_all(string=True):
        text = str(node).strip()
        if _PERIOD.match(text):
            return text
    return None


class DocumentReader:
    """Downloads a document once and turns it into ordered, addressable sections."""

    def __init__(
        self,
        cache_dir: str | Path,
        downloader=None,
        extractor=None,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        section_chars: int = DEFAULT_SECTION_CHARS,
        timeout: float = 60.0,
    ) -> None:
        self._dir = Path(cache_dir)
        self._downloader = downloader
        self._extractor = extractor
        self._limiter = RateLimiter(min_interval_seconds)
        self._section_chars = section_chars
        self._timeout = timeout
        self._dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url: str) -> Path:
        # Hashed because a BSE attachment URL is a query string, not a filename.
        return self._dir / f"{hashlib.sha256(url.encode()).hexdigest()[:20]}.txt"

    def _download(self, url: str) -> bytes:
        if self._downloader is not None:
            return self._downloader(url)

        import requests

        self._limiter.wait()
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=self._timeout
        )
        response.raise_for_status()
        return response.content

    def _extract(self, payload: bytes) -> str:
        if self._extractor is not None:
            return self._extractor(payload)

        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n\n".join(p for p in pages if p.strip())

    def text(self, url: str) -> str | None:
        """The document's text, downloaded at most once. ``None`` when it cannot be read."""
        cached = self._cache_path(url)
        if cached.exists():
            try:
                return cached.read_text("utf-8")
            except Exception as exc:
                log.debug("unreadable document cache for %s: %s", url, exc)

        try:
            payload = self._download(url)
        except Exception as exc:
            log.warning("document download failed for %s: %s", url, exc)
            return None

        try:
            text = self._extract(payload)
        except Exception as exc:
            # A document we cannot read is reported as such, never as partial text: half a
            # transcript read as though it were whole is worse than none.
            log.warning("document text extraction failed for %s: %s", url, exc)
            return None

        if not text.strip():
            return None

        try:
            cached.write_text(text, encoding="utf-8")
        except Exception as exc:
            log.debug("document cache write failed for %s: %s", url, exc)
        return text

    def sections(self, url: str) -> list[str]:
        """The document split into ordered, individually addressable pieces."""
        text = self.text(url)
        return split_sections(text, self._section_chars) if text else []


def split_sections(text: str, section_chars: int) -> list[str]:
    """Split on paragraph boundaries, never mid-sentence, bounded by size.

    Sections reconstruct the document's own order, so a caller reading them in sequence reads
    the document. Splitting on a character count alone would cut sentences in half and hand a
    model a fragment that changes meaning.
    """
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    sections: list[str] = []
    current: list[str] = []
    size = 0

    for paragraph in paragraphs:
        # A single paragraph larger than the bound is hard-split; nothing else can be done
        # with it, and dropping it would lose content silently.
        if len(paragraph) > section_chars:
            if current:
                sections.append("\n\n".join(current))
                current, size = [], 0
            for start in range(0, len(paragraph), section_chars):
                sections.append(paragraph[start : start + section_chars])
            continue

        if size + len(paragraph) > section_chars and current:
            sections.append("\n\n".join(current))
            current, size = [], 0

        current.append(paragraph)
        size += len(paragraph) + 2

    if current:
        sections.append("\n\n".join(current))
    return sections
