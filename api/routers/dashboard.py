"""Wahu Collections · Agency Console — read API.

Five endpoints, all honouring the same {fleet, agency} (+ date/period/q)
filter triple as the CLI:

    GET  /dashboard/overview?fleet=&agency=&date=
    GET  /dashboard/activities?fleet=&agency=&date=
    GET  /dashboard/performance?fleet=&agency=&period=
    GET  /dashboard/suspense?fleet=&agency=
    GET  /dashboard/riders?fleet=&agency=&q=
    POST /dashboard/activities         (log a new collector action)
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from collections_v3.dashboard import readers
from collections_v3.dashboard.activity_log import (
    ACTION_TYPES, list_all as list_activities_raw, log_activity,
)


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(
    fleet: str = Query("All"),
    agency: str = Query("All"),
    date_: Optional[date] = Query(None, alias="date"),
):
    return readers.overview(fleet=fleet, agency=agency, on_date=date_)


@router.get("/activities")
def activities(
    fleet: str = Query("All"),
    agency: str = Query("All"),
    date_: Optional[date] = Query(None, alias="date"),
):
    return readers.activities(fleet=fleet, agency=agency, on_date=date_)


@router.post("/activities")
def log_collector_action(payload: dict = Body(...)):
    """Append one collector action to the agency_activity log."""
    try:
        return log_activity(
            agency=payload["agency"],
            collector_id=payload["collector_id"],
            rider_id=payload["rider_id"],
            action_type=payload["action_type"],
            outcome=payload.get("outcome", ""),
            amount_ghs=float(payload.get("amount_ghs", 0) or 0),
            notes=payload.get("notes", ""),
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"missing field: {e.args[0]}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/activities/raw")
def list_activities_endpoint():
    """Audit endpoint: every logged action, newest first."""
    items = list_activities_raw()
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"count": len(items), "items": items}


@router.get("/performance")
def performance(
    fleet: str = Query("All"),
    agency: str = Query("All"),
    period: str = Query("Week"),
):
    return readers.performance(fleet=fleet, agency=agency, period=period)


@router.get("/suspense")
def suspense(
    fleet: str = Query("All"),
    agency: str = Query("All"),
):
    return readers.suspense(fleet=fleet, agency=agency)


@router.get("/riders")
def riders(
    fleet: str = Query("All"),
    agency: str = Query("All"),
    q: str = Query(""),
):
    return readers.riders(fleet=fleet, agency=agency, q=q)
