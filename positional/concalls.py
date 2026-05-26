"""
Management-outlook source material from Screener.in.

Gathers the qualitative inputs the Phase-3 analyst reasons over:
  * Screener's auto-generated Pros / Cons bullets   (HTML, always available)
  * Recent announcements                            (HTML, high-signal)
  * Latest concall transcript                       (PDF → text, chunked)
  * Latest investor presentation                    (PDF → text)

Everything degrades gracefully: if a PDF host blocks the request or pypdf is
missing, we fall back to the HTML signals. PDFs are immutable per URL, so we
cache the extracted text forever on disk.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Dict, Optional

import requests

from config import CACHE_DIR, POSITIONAL_CONCALL_MAX_PAGES

log = logging.getLogger(__name__)

_CONCALL_CACHE = Path(CACHE_DIR) / "concalls"
_CONCALL_CACHE.mkdir(parents=True, exist_ok=True)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 25
_MIN_INTERVAL_SEC = 2.0
_last_fetch_ts = 0.0


def _base(ticker: str) -> str:
    return ticker.replace(".NS", "").replace(".BO", "").strip().upper()


def _polite_sleep() -> None:
    global _last_fetch_ts
    delta = time.time() - _last_fetch_ts
    if delta < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - delta)


_pypdf_warned = False


def _referer_for(url: str) -> str | None:
    """BSE/NSE reject PDF requests without a matching Referer; supply one."""
    u = url.lower()
    if "bseindia" in u:
        return "https://www.bseindia.com/"
    if "nseindia" in u:
        return "https://www.nseindia.com/"
    if "screener.in" in u:
        return "https://www.screener.in/"
    return None


def fetch_pdf_text(url: str, max_pages: int = POSITIONAL_CONCALL_MAX_PAGES) -> str:
    """Download a PDF and extract text (first ``max_pages`` pages). Cached on disk
    by URL hash. Returns "" on any failure (caller falls back to HTML signals)."""
    global _pypdf_warned, _last_fetch_ts
    if not url:
        return ""
    key = hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()[:24]
    txt_path = _CONCALL_CACHE / f"{key}.txt"
    if txt_path.exists():
        try:
            return txt_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    try:
        from pypdf import PdfReader
    except ImportError:
        if not _pypdf_warned:
            log.warning("[concall] pypdf not installed — concall transcript PDFs will be "
                        "skipped. Run `pip install -r requirements.txt` (or `pip install pypdf`).")
            _pypdf_warned = True
        return ""

    pdf_path = _CONCALL_CACHE / f"{key}.pdf"
    try:
        if not pdf_path.exists():
            _polite_sleep()
            headers = {"User-Agent": _USER_AGENT, "Accept": "application/pdf,*/*"}
            ref = _referer_for(url)
            if ref:
                headers["Referer"] = ref
            resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT,
                                allow_redirects=True)
            _last_fetch_ts = time.time()
            ctype = resp.headers.get("Content-Type", "").lower()
            is_pdf = "pdf" in ctype or resp.content[:4] == b"%PDF"
            if resp.status_code != 200 or not is_pdf:
                log.info("[concall] PDF fetch miss %s (HTTP %s, type %s)",
                         url[:90], resp.status_code, ctype or "?")
                return ""
            pdf_path.write_bytes(resp.content)

        reader = PdfReader(str(pdf_path))
        pages = reader.pages[:max_pages]
        text = "\n".join((p.extract_text() or "") for p in pages).strip()
        if text:
            txt_path.write_text(text, encoding="utf-8")
            log.info("[concall] extracted %d chars from %s", len(text), url[:90])
        else:
            log.info("[concall] PDF had no extractable text (scanned image?) %s", url[:90])
        return text
    except Exception as e:
        log.warning("[concall] PDF extract failed for %s: %s", url[:90], e)
        return ""


def _latest_with(concalls: list, key: str) -> dict | None:
    """Most-recent concall row (screener lists newest first) that has ``key`` set."""
    for row in concalls:
        if row.get(key):
            return row
    return None


def gather_management_material(ticker: str) -> Dict:
    """Collect Pros/Cons + announcements + latest concall/presentation text.

    Returns a dict with at least: pros, cons, announcements, concall_date,
    concall_text, ppt_text, sources, available.
    """
    out: Dict = {
        "ticker": _base(ticker), "pros": [], "cons": [], "announcements": [],
        "concall_date": None, "concall_text": "", "ppt_text": "",
        "sources": [], "available": False,
    }
    try:
        from longterm.screener_scraper import fetch_company
        parsed = fetch_company(_base(ticker))
    except Exception as e:
        log.warning("[concall] screener fetch failed for %s: %s", ticker, e)
        return out

    if not parsed:
        return out

    out["pros"] = parsed.get("pros") or []
    out["cons"] = parsed.get("cons") or []
    out["announcements"] = parsed.get("announcements") or []
    if parsed.get("url"):
        out["sources"].append(parsed["url"])

    concalls = parsed.get("concalls") or []
    # Pick the most recent quarter that actually has a transcript (skip rows where
    # the Transcript button is greyed out / missing); fall back to a presentation.
    transcript_row = _latest_with(concalls, "transcript_url")
    ppt_row = _latest_with(concalls, "ppt_url")
    log.info("[concall] %s: %d concalls on screener; latest transcript=%s ppt=%s",
             out["ticker"], len(concalls),
             (transcript_row or {}).get("transcript_url", "none"),
             (ppt_row or {}).get("ppt_url", "none"))

    if transcript_row:
        out["concall_date"] = transcript_row.get("date")
        out["concall_text"] = fetch_pdf_text(transcript_row["transcript_url"])
        # Record the actual concall document as a source whenever we found the link.
        out["sources"].append(transcript_row["transcript_url"])
    if ppt_row:
        out["concall_date"] = out["concall_date"] or ppt_row.get("date")
        out["ppt_text"] = fetch_pdf_text(ppt_row["ppt_url"])
        out["sources"].append(ppt_row["ppt_url"])

    out["available"] = bool(
        out["pros"] or out["cons"] or out["announcements"]
        or out["concall_text"] or out["ppt_text"]
    )
    return out
