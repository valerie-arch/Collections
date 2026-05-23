"""Collections activities endpoints — log, list, recommend, daily report."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from api.agents.activities_daily import run_daily_report
from api.agents.collections_report.recommender import recommend_for_all, recommend_for_rider
from api.storage import activities as store
from api.storage import agencies as agency_store

router = APIRouter()

INVOICES_DIR = Path("sample_inputs/zoho/invoices")


@lru_cache(maxsize=2)
def _load_invoices_cached(mtime_key: float):
    from api.agents.collections_report.parsers import parse_invoice_folder
    return parse_invoice_folder(INVOICES_DIR)


def _load_invoices():
    if not INVOICES_DIR.exists():
        return []
    mtime = max((p.stat().st_mtime for p in INVOICES_DIR.glob("*.csv")), default=0.0)
    return _load_invoices_cached(mtime)


def _invoices_by_rider() -> dict[str, list]:
    out: dict[str, list] = {}
    for inv in _load_invoices():
        if inv.customer_id:
            out.setdefault(inv.customer_id, []).append(inv)
    return out


def _full_agency_map(by_rider: dict[str, list]) -> dict[str, dict]:
    """Merge sheet-derived agencies with manual JSON assignments.

    Sheet-derived rows (from the Assignment Zones Google Sheet + TSA roster)
    fill the bulk. Manual assignments in data/agency_assignments.json override
    on conflict and carry their original metadata. Recommender expects the
    rich {customer_id: {agency, assigned_at, note}} shape.
    """
    from api.agents.collections_report.sheet_loaders import resolve_agency_map
    invoices = [inv for invs in by_rider.values() for inv in invs]
    derived = resolve_agency_map(invoices)
    out: dict[str, dict] = {
        cid: {"agency": agency, "assigned_at": None, "note": None}
        for cid, agency in derived.items()
    }
    out.update(agency_store.list_assignments())
    return out


@router.get("/")
def list_activities(
    customer_id: Optional[str] = None,
    action: Optional[str] = None,
    agency: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
):
    items = store.list_filtered(
        customer_id=customer_id, action=action, agency=agency, since=since, until=until
    )
    return {"items": items, "count": len(items), "actions": list(store.ACTIONS)}


@router.post("/")
def create_activity(payload: dict = Body(...)):
    cust_id = (payload.get("customer_id") or "").strip()
    # Snapshot the rider's current agency assignment at time of action.
    agency_rec = agency_store.list_assignments().get(cust_id) or {}
    try:
        return store.create(
            customer_id=cust_id,
            customer_name=payload.get("customer_name", ""),
            action=payload.get("action", ""),
            note=payload.get("note", ""),
            actor=payload.get("actor"),
            agency=agency_rec.get("agency"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{activity_id}")
def delete_activity(activity_id: str):
    removed = store.delete(activity_id)
    if not removed:
        raise HTTPException(status_code=404, detail="activity not found")
    return {"removed": True}


@router.get("/recommendations")
def recommendations(
    agency: Optional[str] = None,
    limit: int = 100,
):
    """Bulk recommendations for every rider with outstanding."""
    by_rider = _invoices_by_rider()
    if not by_rider:
        return {"items": [], "_note": "No invoice data — sync from Drive first."}
    activity_log = store.list_all()
    agency_map = _full_agency_map(by_rider)
    recs = recommend_for_all(
        by_rider, activity_log=activity_log, agency_map=agency_map
    )
    if agency:
        if agency == "Unassigned":
            recs = [r for r in recs if not r.agency]
        else:
            recs = [r for r in recs if r.agency == agency]
    # Filter out no_action (rider current) to reduce noise.
    recs = [r for r in recs if r.recommended_action != "no_action"]
    return {"items": [asdict(r) for r in recs[:limit]], "total": len(recs)}


@router.get("/recommendations/{customer_id}")
def recommendation_for(customer_id: str):
    by_rider = _invoices_by_rider()
    invs = by_rider.get(customer_id)
    if not invs:
        raise HTTPException(status_code=404, detail="rider has no invoices")
    activity_log = store.list_all()
    agency_rec = _full_agency_map(by_rider).get(customer_id) or {}
    rec = recommend_for_rider(
        invs,
        activity_log=activity_log,
        agency=agency_rec.get("agency"),
        agency_assigned_at=agency_rec.get("assigned_at"),
    )
    return asdict(rec)


@router.post("/run-daily")
def trigger_daily(day: Optional[date] = None):
    """Manual fire of the 18:00 job: build xlsx → Drive upload → email finance."""
    return run_daily_report(day)
