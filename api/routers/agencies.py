"""3rd-party collections agency assignment endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from api.storage import agencies as store

router = APIRouter()


@router.get("/")
def list_assignments() -> dict:
    """Return all current assignments and the list of distinct agency names."""
    assignments = store.list_assignments()
    return {
        "assignments": assignments,
        "agencies": store.known_agencies(),
        "count": len(assignments),
    }


@router.post("/assign")
def assign(payload: dict = Body(...)) -> dict:
    """Assign a rider to a 3rd-party collections agency.

    Body: {customer_id, agency, note?}
    """
    customer_id = (payload.get("customer_id") or "").strip()
    agency = (payload.get("agency") or "").strip()
    note = (payload.get("note") or "").strip() or None
    if not customer_id or not agency:
        raise HTTPException(status_code=400, detail="customer_id and agency are required")
    record = store.assign(customer_id, agency, note)
    return {"customer_id": customer_id, **record}


@router.post("/unassign")
def unassign(payload: dict = Body(...)) -> dict:
    customer_id = (payload.get("customer_id") or "").strip()
    if not customer_id:
        raise HTTPException(status_code=400, detail="customer_id is required")
    removed = store.unassign(customer_id)
    return {"customer_id": customer_id, "removed": removed}
