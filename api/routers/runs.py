"""Reconciliation run management endpoints."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.database import get_db
from api.models.orm import Run, StepResult
from api.scheduler import trigger_step_now

router = APIRouter()


def _serialize_run(run: Run) -> dict:
    return {
        "run_id": run.run_id,
        "run_date": run.run_date.isoformat(),
        "trigger_step": run.trigger_step,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_message": run.error_message,
    }


@router.get("/")
def list_runs(
    run_date: Optional[date] = None,
    status: Optional[str] = None,
    step: Optional[int] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Run)
    if run_date:
        q = q.filter(Run.run_date == run_date)
    if status:
        q = q.filter(Run.status == status)
    if step:
        q = q.filter(Run.trigger_step == step)
    runs = q.order_by(Run.created_at.desc()).limit(limit).all()
    return [_serialize_run(r) for r in runs]


@router.get("/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    results = (
        db.query(StepResult)
        .filter(StepResult.run_id == run_id)
        .order_by(StepResult.step.asc())
        .all()
    )
    return {
        **_serialize_run(run),
        "step_results": [
            {
                "result_id": r.result_id,
                "step": r.step,
                "status": r.status,
                "output_path": r.output_path,
                "row_count": r.row_count,
                "warning_count": r.warning_count,
                "exception_count": r.exception_count,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in results
        ],
    }


@router.post("/trigger")
def trigger_run(step: int = Query(..., ge=1, le=12)):
    """Manually run a step now. Returns the new run_id."""
    run_id = trigger_step_now(step)
    return {"run_id": run_id, "step": step, "status": "dispatched"}
