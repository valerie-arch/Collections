"""Step → agent function registry.

Sprint 0: every step is a no-op stub that records a successful run with zero
rows. As real agents land (Sprints 1–10), replace each entry here.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from api.agents.base import AgentResult
from api.models.orm import Run

AgentFn = Callable[[Session, Run], AgentResult]


def _noop(name: str) -> AgentFn:
    def _fn(db: Session, run: Run) -> AgentResult:  # noqa: ARG001
        return AgentResult(success=True, row_count=0)

    _fn.__name__ = f"noop_{name}"
    return _fn


STEP_NAMES: dict[int, str] = {
    1: "Rider Population",
    2: "Org Split (WF/TSA)",
    3: "Weekly Billing",
    4: "Payments Reconciliation",
    5: "Suspense & Exceptions",
    6: "Bolt Earnings Ingest",
    7: "Earnings Deduction",
    8: "Rider Statements",
    9: "MTD Ranking",
    10: "SMS Reminders",
    11: "Collections Memo",
    12: "QuickBooks Posting",
}


REGISTRY: dict[int, AgentFn] = {
    step: _noop(name) for step, name in STEP_NAMES.items()
}


def get_agent(step: int) -> AgentFn:
    if step not in REGISTRY:
        raise KeyError(f"no agent registered for step {step}")
    return REGISTRY[step]
