"""APScheduler setup for the 12-step agent workflow.

Cron triggers are derived from SOP §4. Each job calls `_dispatch(step)` which
opens a DB session and invokes the registered agent through `run_step`.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from api.agents import run_step
from api.agents.registry import STEP_NAMES, get_agent
from api.config import settings
from api.database import SessionLocal

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=settings.SCHEDULER_TIMEZONE)


def _dispatch(step: int) -> None:
    db = SessionLocal()
    try:
        run = run_step(db, step, get_agent(step))
        logger.info(
            "step %d (%s) -> %s row_count=%d",
            step, STEP_NAMES[step], run.status, run.step_results[0].row_count,
        )
    except Exception:
        logger.exception("step %d dispatch failed", step)
        db.rollback()
    finally:
        db.close()


def _add(step: int, trigger: CronTrigger, suffix: str = "") -> None:
    job_id = f"step_{step}{('_' + suffix) if suffix else ''}"
    scheduler.add_job(
        func=_dispatch,
        args=[step],
        trigger=trigger,
        id=job_id,
        name=f"Step {step}: {STEP_NAMES[step]}{(' (' + suffix + ')') if suffix else ''}",
        replace_existing=True,
    )


def init_scheduler() -> None:
    """Wire all 12 SOP §4 jobs and start the scheduler."""
    # Daily ingest cascade (Steps 1, 2, 4, 5, 9): chain off Step 1 at 06:00.
    # Each runs a few minutes apart so logs are readable without a real DAG.
    _add(1, CronTrigger(hour=6, minute=0))
    _add(2, CronTrigger(hour=6, minute=5))
    _add(4, CronTrigger(hour=6, minute=15))
    _add(5, CronTrigger(hour=6, minute=30))
    _add(9, CronTrigger(hour=7, minute=0))

    # Weekly cycle (Sunday).
    _add(3, CronTrigger(day_of_week=6, hour=23, minute=59))
    _add(6, CronTrigger(day_of_week=6, hour=22, minute=0))   # Bolt earnings drop
    _add(7, CronTrigger(day_of_week=6, hour=22, minute=30))  # Earnings deduction
    _add(8, CronTrigger(day_of_week=0, hour=8, minute=0))    # Statements Mon AM

    # Dunning cadence.
    _add(10, CronTrigger(day_of_week=2, hour=10, minute=0), suffix="wed_soft")
    _add(10, CronTrigger(day_of_week=4, hour=9, minute=0), suffix="fri_firm")

    # Monday close-out.
    _add(11, CronTrigger(day_of_week=0, hour=10, minute=0))
    _add(12, CronTrigger(day_of_week=0, hour=11, minute=0))

    # Daily collections-activity report: 18:00 Africa/Accra → Drive upload + email.
    def _activities_daily_job() -> None:
        try:
            from api.agents.activities_daily import run_daily_report
            result = run_daily_report()
            logger.info("activities daily: %s", result)
        except Exception:
            logger.exception("activities daily job failed")

    scheduler.add_job(
        func=_activities_daily_job,
        trigger=CronTrigger(hour=settings.ACTIVITIES_REPORT_HOUR, minute=0),
        id="activities_daily_report",
        name=f"Activities daily report ({settings.ACTIVITIES_REPORT_HOUR}:00 Africa/Accra → Drive archive)",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("✓ Scheduler initialized with all 12 SOP §4 steps")


def trigger_step_now(step: int) -> str:
    """Manually fire a step (used by /api/runs/trigger)."""
    db = SessionLocal()
    try:
        run = run_step(db, step, get_agent(step))
        return run.run_id
    finally:
        db.close()
