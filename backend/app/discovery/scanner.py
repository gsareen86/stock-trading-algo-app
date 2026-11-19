"""Daily Nifty Total Market discovery scanner with append-only persistence and concurrency lock."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now_utc
from app.data.protocols import CompanyFinancialsSource, PriceSource, UniverseSource
from app.data.sectors import all_sector_indices, for_instrument
from app.discovery.quality import QualityReport, evaluate_quality
from app.discovery.ranking import CandidateEntry, rank_candidates
from app.discovery.sectors import (
    BENCHMARK_NIFTY50,
    BENCHMARK_NIFTY500,
    SectorPlacement,
    compute_sector_rrg,
)
from app.domain.instrument import Instrument
from app.domain.verdict import Evidence, GateResult, Plan, Stance, Verdict
from app.llm.types import LLMGateway
from app.narratives.generator import narrate_all
from app.persistence.models import ScanEntry as ScanEntryRow
from app.persistence.models import ScanRun as ScanRunRow
from app.screening.screener import ScreenCriteria, Screener
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, int, int | None], None]


class ScanInProgressError(RuntimeError):
    """Raised when a scan is triggered while another scan is already running."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        super().__init__(f"scan run #{run_id} is already in progress")


@dataclass(frozen=True, slots=True)
class ScanSummary:
    run_id: int
    trigger: str
    outcome: str
    universe_origin: str
    index_name: str
    benchmark: str
    considered_count: int
    eligible_count: int
    entries_count: int
    sectors: list[SectorPlacement]
    entries: list[CandidateEntry]
    started_at: str
    finished_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trigger": self.trigger,
            "outcome": self.outcome,
            "universe_origin": self.universe_origin,
            "index_name": self.index_name,
            "benchmark": self.benchmark,
            "considered_count": self.considered_count,
            "eligible_count": self.eligible_count,
            "entries_count": self.entries_count,
            "sectors": [s.as_dict() for s in self.sectors],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_SCAN_LOCK = threading.Lock()
_ACTIVE_RUN_ID: int | None = None


def _verdict_to_dict(v: Verdict) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "strategy_id": v.strategy_id,
        "ticker": v.ticker,
        "as_of": v.as_of.isoformat(),
        "stance": v.stance.value,
        "conviction": v.conviction,
        "gates_passed": v.gates_passed,
        "gates": v.gates_as_json(),
        "evidence": v.evidence_as_json(),
        "narrative": v.narrative,
        "trace_id": v.trace_id,
    }
    if v.plan is not None:
        payload["plan"] = v.plan.as_dict()
    if v.plan_note is not None:
        payload["plan_note"] = v.plan_note
    return payload


def verdict_from_dict(raw: dict[str, Any]) -> Verdict:
    from datetime import UTC, datetime

    as_of = datetime.fromisoformat(raw["as_of"])
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    plan_raw = raw.get("plan")
    return Verdict(
        strategy_id=raw["strategy_id"],
        ticker=raw["ticker"],
        as_of=as_of,
        stance=Stance(raw["stance"]),
        conviction=int(raw["conviction"]),
        evidence=tuple(Evidence.from_dict(e) for e in (raw.get("evidence") or [])),
        gates=tuple(GateResult.from_dict(g) for g in (raw.get("gates") or [])),
        plan=Plan.from_dict(plan_raw) if isinstance(plan_raw, dict) else None,
        plan_note=raw.get("plan_note"),
        narrative=raw.get("narrative"),
        trace_id=raw.get("trace_id"),
    )


class DiscoveryScanner:
    """Runs the Sector-First Discovery Funnel and persists append-only scan runs."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        universe_source: UniverseSource,
        price_source: PriceSource,
        strategies: StrategyRegistry,
        fundamentals_source=None,
        company_financials_source: CompanyFinancialsSource | None = None,
        gateway: LLMGateway | None = None,
        theme_labeller: Callable[[list[str]], dict[str, list[dict[str, Any]]]] | None = None,
    ) -> None:
        self._sessions = session_factory
        self._universe = universe_source
        self._prices = price_source
        self._strategies = strategies
        self._fundamentals = fundamentals_source
        self._financials = company_financials_source
        self._gateway = gateway
        self._theme_labeller = theme_labeller

    async def run(
        self,
        *,
        trigger: str = "requested",
        benchmark: str = BENCHMARK_NIFTY500,
        criteria: ScreenCriteria | None = None,
        narrate_head: int = 10,
        narrate: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> ScanSummary:
        global _ACTIVE_RUN_ID

        if not _SCAN_LOCK.acquire(blocking=False):
            raise ScanInProgressError(_ACTIVE_RUN_ID or 0)

        run_id = 0
        try:
            with self._sessions() as session:
                existing = session.execute(
                    select(ScanRunRow)
                    .where(ScanRunRow.outcome == "running")
                    .order_by(ScanRunRow.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if existing is not None:
                    raise ScanInProgressError(existing.id)

            snapshot = await asyncio.to_thread(self._universe.snapshot)
            with self._sessions() as session:
                row = ScanRunRow(
                    trigger=trigger,
                    universe_origin=snapshot.origin,
                    index_name=snapshot.index_name,
                    benchmark=benchmark,
                    outcome="running",
                    considered_count=len(snapshot.instruments),
                    eligible_count=0,
                    unevaluable=[],
                    sectors_snapshot=[],
                    started_at=now_utc(),
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                run_id = row.id
                _ACTIVE_RUN_ID = run_id

            def emit(step: str, label: str, completed: int, total: int | None) -> None:
                if on_progress is not None:
                    on_progress(step, label, completed, total)

            # 0. Batch-prefetch OHLCV prices (universe + sector indices + benchmarks) into cache
            total_universe = len(snapshot.instruments)
            prefetch_fn = getattr(self._prices, "prefetch", None)
            if prefetch_fn is not None:
                sector_insts = [s.as_instrument() for s in all_sector_indices()]
                bench_insts = [Instrument(BENCHMARK_NIFTY50), Instrument(BENCHMARK_NIFTY500)]
                all_targets = [*snapshot.instruments, *sector_insts, *bench_insts]
                emit(
                    "prices",
                    f"Downloading live OHLCV bars (0 / {len(all_targets)})",
                    0,
                    len(all_targets),
                )
                await asyncio.to_thread(
                    prefetch_fn,
                    all_targets,
                    interval="1d",
                    lookback_days=820,
                    chunk_size=75,
                    on_progress=lambda done, tot: emit(
                        "prices",
                        f"Downloading live OHLCV bars ({done} / {tot})",
                        done,
                        tot,
                    ),
                )

            # 1. Screen universe in universe order (runs off warm cache)
            emit("screening", f"Screening {total_universe} instruments", 0, total_universe)
            screen_result = await asyncio.to_thread(
                Screener(self._prices).run, snapshot, criteria=criteria
            )
            emit(
                "screening",
                f"Screened {total_universe} instruments ({len(screen_result.eligible)} eligible)",
                total_universe,
                total_universe,
            )

            # 2. Compute sector RRG quadrants
            emit("sectors", "Computing sector RRG rotation", 0, len(all_sector_indices()))
            sector_placements = await asyncio.to_thread(
                compute_sector_rrg, self._prices, benchmark=benchmark
            )
            emit(
                "sectors",
                "Computed sector RRG rotation",
                len(sector_placements),
                len(sector_placements),
            )

            # 3. Warm financials & quarterly EPS/revenue concurrently (30-day cached on disk)
            eligible = screen_result.eligible
            total_eligible = len(eligible)
            financials_map: dict[str, Any] = {}
            if self._financials is not None and eligible:
                emit(
                    "financials",
                    f"Loading financials & quality (0 / {total_eligible})",
                    0,
                    total_eligible,
                )

                def _warm_financials() -> dict[str, Any]:
                    fetched: dict[str, Any] = {}
                    done_count = 0

                    def _one(inst: Instrument):
                        try:
                            return inst.symbol, self._financials.financials(inst)
                        except Exception as exc:
                            log.debug("quality fetch failed for %s: %s", inst.symbol, exc)
                            return inst.symbol, None

                    with ThreadPoolExecutor(max_workers=12) as pool:
                        futures = [pool.submit(_one, inst) for inst in eligible]
                        for fut in as_completed(futures):
                            sym, fin_obj = fut.result()
                            fetched[sym] = fin_obj
                            done_count += 1
                            if done_count == total_eligible or done_count % 25 == 0:
                                emit(
                                    "financials",
                                    (
                                        f"Loading financials & quality "
                                        f"({done_count} / {total_eligible})"
                                    ),
                                    done_count,
                                    total_eligible,
                                )
                    return fetched

                financials_map = await asyncio.to_thread(_warm_financials)

            # 4. Evaluate all 4 strategies + Quality facets over eligible instruments
            strategy_defs = self._strategies.definitions()
            strategy_ctx = StrategyContext(
                price_source=self._prices,
                fundamentals_source=self._fundamentals,
            )

            theme_labels: dict[str, list[dict[str, Any]]] = {}
            if self._theme_labeller is not None and eligible:
                try:
                    theme_labels = (
                        await asyncio.to_thread(
                            self._theme_labeller, [inst.symbol for inst in eligible]
                        )
                        or {}
                    )
                except Exception as exc:
                    log.debug("theme labeller unavailable during scan: %s", exc)

            def _evaluate_all() -> list[CandidateEntry]:
                out: list[CandidateEntry] = []
                for idx, inst in enumerate(eligible):
                    if idx == 0 or (idx + 1) == total_eligible or (idx + 1) % 25 == 0:
                        emit(
                            "strategies",
                            f"Evaluating strategies & plans ({idx + 1} / {total_eligible})",
                            idx + 1,
                            total_eligible,
                        )
                    verdicts = [
                        defn.strategy.evaluate(inst, strategy_ctx) for defn in strategy_defs
                    ]
                    sec_idx = for_instrument(inst)
                    sec_key = sec_idx.key if sec_idx else None

                    fin = financials_map.get(inst.symbol)
                    quality_report: QualityReport = evaluate_quality(
                        fin, symbol=inst.symbol, sector_key=sec_key
                    )

                    out.append(
                        CandidateEntry.from_verdicts(
                            symbol=inst.symbol,
                            name=inst.name,
                            sector=inst.sector,
                            sector_key=sec_key,
                            universe_index=idx,
                            verdicts=verdicts,
                            quality=quality_report,
                            themes=theme_labels.get(inst.symbol, ()),
                        )
                    )
                return out

            entries = await asyncio.to_thread(_evaluate_all)

            # 5. Deterministic attribution ranking BEFORE any LLM narration
            ranked = rank_candidates(entries)

            # 6. Optional narration confined strictly to the ranked head
            if narrate and self._gateway is not None and narrate_head > 0 and ranked:
                head_slice = ranked[:narrate_head]
                to_narrate = [
                    v
                    for entry in head_slice
                    for v in entry.verdicts
                    if v.stance in (Stance.BUY, Stance.WATCH)
                ]
                if to_narrate:
                    emit("narrate", f"Narrating top {len(to_narrate)} verdicts", 0, len(to_narrate))
                    narrated_list, _ = await narrate_all(
                        to_narrate,
                        self._gateway,
                        on_each=lambda done, total: emit(
                            "narrate", f"Narrated {done} / {total} verdicts", done, total
                        ),
                    )
                    by_key = {(v.ticker, v.strategy_id): v for v in narrated_list}
                    updated_head: list[CandidateEntry] = []
                    for entry in head_slice:
                        new_verdicts = tuple(
                            by_key.get((v.ticker, v.strategy_id), v) for v in entry.verdicts
                        )
                        updated_head.append(entry.with_verdicts(new_verdicts))
                    ranked = updated_head + ranked[narrate_head:]
                    emit(
                        "narrate",
                        f"Narrated top {len(to_narrate)} verdicts",
                        len(to_narrate),
                        len(to_narrate),
                    )

            finished = now_utc()
            with self._sessions() as session:
                run_row = session.get(ScanRunRow, run_id)
                assert run_row is not None
                run_row.outcome = "complete"
                run_row.eligible_count = total_eligible
                run_row.unevaluable = [e.as_dict() for e in screen_result.excluded]
                run_row.sectors_snapshot = [s.as_dict() for s in sector_placements]
                run_row.finished_at = finished

                entry_rows = [
                    ScanEntryRow(
                        run_id=run_id,
                        universe_index=e.universe_index,
                        symbol=e.symbol,
                        name=e.name,
                        sector=e.sector,
                        sector_key=e.sector_key,
                        ranked_by=e.ranked_by,
                        ranked_conviction=e.ranked_conviction,
                        ranked_stance=e.ranked_stance,
                        buy_count=e.buy_stances,
                        verdicts=[_verdict_to_dict(v) for v in e.verdicts],
                        quality=e.quality.as_dict() if e.quality else {},
                        themes=list(e.themes),
                    )
                    for e in ranked
                ]
                session.add_all(entry_rows)
                session.commit()
                started_iso = run_row.started_at.isoformat()

            return ScanSummary(
                run_id=run_id,
                trigger=trigger,
                outcome="complete",
                universe_origin=snapshot.origin,
                index_name=snapshot.index_name,
                benchmark=benchmark,
                considered_count=len(snapshot.instruments),
                eligible_count=total_eligible,
                entries_count=len(ranked),
                sectors=sector_placements,
                entries=ranked,
                started_at=started_iso,
                finished_at=finished.isoformat(),
            )
        except ScanInProgressError:
            raise
        except asyncio.CancelledError:
            # Not an `Exception`, so the handler below never saw it and a cancelled scan kept
            # claiming to be running — refusing every later scan until a restart. Cancellation
            # is now only the server shutting down; a closed browser no longer causes it.
            log.warning("discovery scan #%s cancelled before completion", run_id)
            if run_id:
                with self._sessions() as session:
                    run_row = session.get(ScanRunRow, run_id)
                    if run_row is not None and run_row.outcome == "running":
                        run_row.outcome = "interrupted"
                        run_row.error = "cancelled before completion"
                        run_row.finished_at = now_utc()
                        session.commit()
            raise
        except Exception as exc:
            log.exception("discovery scan #%s failed: %s", run_id, exc)
            if run_id:
                with self._sessions() as session:
                    run_row = session.get(ScanRunRow, run_id)
                    if run_row is not None:
                        run_row.outcome = "failed"
                        run_row.error = str(exc)[:500]
                        run_row.finished_at = now_utc()
                        session.commit()
            raise
        finally:
            _ACTIVE_RUN_ID = None
            _SCAN_LOCK.release()
