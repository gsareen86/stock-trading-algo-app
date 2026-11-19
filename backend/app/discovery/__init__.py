"""Sector-first Discovery Funnel — RRG sector placement, movers, quality facets, and ranking."""

from app.discovery.movers import NotableMover, find_movers
from app.discovery.quality import QualityFacet, QualityReport, evaluate_quality
from app.discovery.ranking import (
    CandidateEntry,
    filter_candidates,
    rank_candidates,
    select_ranking_verdict,
)
from app.discovery.scanner import (
    DiscoveryScanner,
    ScanInProgressError,
    ScanSummary,
    verdict_from_dict,
)
from app.discovery.sectors import (
    BENCHMARK_NIFTY50,
    BENCHMARK_NIFTY500,
    SectorPlacement,
    compute_sector_rrg,
    detect_quadrant_shifts,
    place_sector,
)

__all__ = [
    "BENCHMARK_NIFTY50",
    "BENCHMARK_NIFTY500",
    "CandidateEntry",
    "DiscoveryScanner",
    "NotableMover",
    "QualityFacet",
    "QualityReport",
    "ScanInProgressError",
    "ScanSummary",
    "SectorPlacement",
    "compute_sector_rrg",
    "detect_quadrant_shifts",
    "evaluate_quality",
    "filter_candidates",
    "find_movers",
    "place_sector",
    "rank_candidates",
    "select_ranking_verdict",
    "verdict_from_dict",
]
