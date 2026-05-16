"""Agent execution scaffolding.

Each step runs through `run_step`, which creates a Run + StepResult, invokes
the agent function, and records duration/outcome. Real per-step logic is
implemented in subsequent sprints — Sprint 0 ships no-op agents so the
orchestration plumbing is exercised end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from api.models.orm import Exception_, Run, StepResult


@dataclass
class AgentResult:
    """Outcome of a single step. Agents return this; the runner persists it."""

    success: bool = True
    output_path: Optional[str] = None
    row_count: int = 0
    warning_count: int = 0
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    error_message: Optional[str] = None


AgentFn = Callable[[Session, Run], AgentResult]


def run_step(
    db: Session,
    step: int,
    agent_fn: AgentFn,
    *,
    run_date: Optional[date] = None,
) -> Run:
    """Execute one step end-to-end and persist the run + result."""
    if not 1 <= step <= 12:
        raise ValueError(f"step must be 1..12, got {step}")

    run = Run(
        run_date=run_date or date.today(),
        trigger_step=step,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()  # populate run.run_id without committing

    result_row = StepResult(
        run_id=run.run_id,
        step=step,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(result_row)
    db.flush()

    started = datetime.utcnow()
    try:
        result = agent_fn(db, run)
    except Exception as exc:  # noqa: BLE001 — runner must not raise
        result = AgentResult(success=False, error_message=str(exc))

    finished = datetime.utcnow()
    duration_ms = int((finished - started).total_seconds() * 1000)

    result_row.status = "succeeded" if result.success else "failed"
    result_row.completed_at = finished
    result_row.duration_ms = duration_ms
    result_row.output_path = result.output_path
    result_row.row_count = result.row_count
    result_row.warning_count = result.warning_count
    result_row.exception_count = len(result.exceptions)

    for exc_payload in result.exceptions:
        db.add(
            Exception_(
                run_id=run.run_id,
                step=step,
                severity=exc_payload.get("severity", "error"),
                error_code=exc_payload.get("error_code"),
                message=exc_payload["message"],
                context=exc_payload.get("context"),
            )
        )

    run.status = "succeeded" if result.success else "failed"
    run.completed_at = finished
    run.error_message = result.error_message

    db.commit()
    db.refresh(run)
    return run
