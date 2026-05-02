"""
Phase A orchestrator: build universe -> score quality.

Two ways to invoke:
1. CLI:    python -m longterm.tasks [--limit N] [--force] [--score-only]
2. Code:   from longterm.tasks import run_phase_a; run_phase_a()

The dashboard's "Long-Term Research" tab calls ``run_phase_a`` with a
progress callback so the user sees per-ticker progress without blocking
Streamlit's main thread (the call is short-circuited via a thread inside
the tab handler).

Cadence (recommended; the scheduler hookup comes in Phase E):
- Universe rebuild: weekly (shareholding patterns are quarterly anyway)
- Quality re-score: weekly or on-demand from the dashboard
"""
from __future__ import annotations

import argparse
import logging
from typing import Callable, Dict, Optional

from db.models import init_db
from longterm.quality import score_universe
from longterm.universe import build_universe

log = logging.getLogger(__name__)


def run_phase_a(
    limit: Optional[int] = None,
    force: bool = False,
    score_only: bool = False,
    progress_cb: Optional[Callable] = None,
    skip_existing: bool = False,
) -> Dict[str, Dict[str, int]]:
    """
    Run universe build + quality scoring end-to-end.

    Parameters
    ----------
    limit       : cap tickers (testing). None = full NIFTY 500.
    force       : bypass screener.in HTML cache.
    score_only  : skip universe rebuild; just re-score the existing universe.
    skip_existing : if True, only process tickers that aren't already in
                  ``lt_universe`` (resume an interrupted run without
                  re-scraping the first N tickers).
    progress_cb : ``callable(stage:str, idx:int, total:int, ticker:str, info)``

    Returns ``{"universe": {...}, "quality": {...}}`` count dicts.
    """
    init_db()  # make sure lt_universe / lt_quality exist

    universe_counts: Dict[str, int] = {}
    if not score_only:
        log.info("Phase A: building universe (skip_existing=%s)...", skip_existing)
        universe_counts = build_universe(
            limit=limit,
            force=force,
            skip_existing=skip_existing,
            progress_cb=(
                (lambda i, t, tk, v: progress_cb("universe", i, t, tk, v))
                if progress_cb else None
            ),
        )
        log.info("Universe: %s", universe_counts)

    log.info("Phase A: scoring quality...")
    quality_counts = score_universe(
        force=force,
        progress_cb=(
            (lambda i, t, tk, sc: progress_cb("quality", i, t, tk, sc))
            if progress_cb else None
        ),
    )
    log.info("Quality: %s", quality_counts)

    return {"universe": universe_counts, "quality": quality_counts}


def main():
    ap = argparse.ArgumentParser(description="Run long-term Phase A pipeline.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Limit tickers (smoke-test). Default: full universe.")
    ap.add_argument("--force", action="store_true",
                    help="Bypass screener.in HTML cache.")
    ap.add_argument("--score-only", action="store_true",
                    help="Skip universe rebuild; just re-score current universe.")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Resume mode — only process tickers not already in lt_universe.")
    ap.add_argument("--verbose", action="store_true",
                    help="Verbose logging.")
    args = ap.parse_args()

    logging.basicConfig(
        level=(logging.DEBUG if args.verbose else logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    res = run_phase_a(
        limit=args.limit,
        force=args.force,
        score_only=args.score_only,
        skip_existing=args.skip_existing,
    )
    print(res)


if __name__ == "__main__":
    main()
