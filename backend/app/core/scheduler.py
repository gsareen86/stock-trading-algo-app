"""Running things on a timer.

**The reload guard is the part that matters.** `uvicorn --reload` runs two processes: a
supervisor that watches files and a child that serves. Both execute the application factory, so
a scheduler started naively runs twice, and every scheduled job fires twice — silently, only in
development, and only for whoever is running with reload on. Two theme runs firing together is
exactly the case `ThemeStore.running_run` refuses, so the symptom would be a mysterious
"already in progress" rather than anything pointing at the cause.

uvicorn marks the child with `RUN_MAIN`, so only the child schedules. A process that is not the
reloader's child schedules normally — which covers production, where there is only one.

Jobs never raise into the scheduler. A weekly run that dies takes its own run down and nothing
else; a scheduler that dies takes every future run with it, and nobody notices for a week.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

log = logging.getLogger(__name__)

#: Set by uvicorn's reloader in the child process only. Absent when reload is off, in which
#: case there is exactly one process and it should schedule.
_RELOAD_CHILD_MARKER = "RUN_MAIN"


def is_reloader_supervisor() -> bool:
    """True in the parent process of `uvicorn --reload`, which must not schedule.

    Detected by the marker's *absence* combined with the reloader being active. `RUN_MAIN` is
    set only in the child, so when reload is on, the process without it is the supervisor.
    """
    reloading = os.environ.get("UVICORN_RELOAD") == "true"
    return reloading and os.environ.get(_RELOAD_CHILD_MARKER) != "true"


class Scheduler:
    """A thin wrapper over APScheduler that degrades to doing nothing.

    Absent APScheduler, an unschedulable environment or a supervisor process all produce a
    scheduler that accepts jobs and runs none. That is a platform without automation, which is
    the state it has been in until now — not a broken one.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._jobs: list[tuple[str, Callable[[], None], dict]] = []
        self._scheduler = None
        self._enabled = enabled and not is_reloader_supervisor()
        if enabled and not self._enabled:
            log.info("scheduler suppressed in the reloader supervisor process")

    @property
    def active(self) -> bool:
        return self._scheduler is not None

    def every_week(self, job_id: str, run: Callable[[], None], day: str, hour: int) -> None:
        self._jobs.append((job_id, run, {"trigger": "cron", "day_of_week": day, "hour": hour}))

    def every_day(self, job_id: str, run: Callable[[], None], hour: int) -> None:
        self._jobs.append((job_id, run, {"trigger": "cron", "hour": hour}))

    def start(self) -> bool:
        """Begin scheduling. False when nothing will run, for any reason."""
        if not self._enabled or not self._jobs:
            return False

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError:
            log.info("apscheduler is not installed; nothing is scheduled")
            return False

        scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
        for job_id, run, trigger in self._jobs:
            scheduler.add_job(
                _guarded(job_id, run),
                id=job_id,
                # A run that overruns its next slot must not stack a second copy on top of
                # itself. The theme store would refuse the second anyway; not starting it is
                # cleaner than relying on that.
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                **trigger,
            )

        scheduler.start()
        self._scheduler = scheduler
        log.info("scheduled %d job(s): %s", len(self._jobs), ", ".join(j[0] for j in self._jobs))
        return True

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def job_ids(self) -> list[str]:
        return [job_id for job_id, _, _ in self._jobs]


def _guarded(job_id: str, run: Callable[[], None]) -> Callable[[], None]:
    """Wrap a job so its failure never reaches the scheduler.

    A job that dies takes its own run down. A scheduler that dies takes every future run with
    it, and the failure is invisible until someone wonders why nothing has updated in a month.
    """

    def job() -> None:
        try:
            run()
        except Exception as exc:
            log.warning("scheduled job %s failed: %s", job_id, exc)

    return job
