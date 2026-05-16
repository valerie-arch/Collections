"""Exception and suspense management endpoints.

`/outliers` is the live data-driven view — derived from the invoice corpus
on the fly. The legacy `/` (pipeline exceptions) and `/suspense` (DB-backed
suspense ledger) still exist for future Step-5 integration.
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.agents.collections_report.outliers import detect_outliers
from api.database import get_db
from api.models.orm import Exception_, SuspenseItem

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


@router.get("/outliers")
def list_outliers(
    category: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
):
    """Surfaces invoice-level outliers (very old open, large balance, mismatched
    status, unpaid recurring, duplicates) computed live from the invoice corpus."""
    invoices = _load_invoices()
    if not invoices:
        return {"counts": {}, "items": [], "_note": "No invoice data — sync from Drive first."}
    report = detect_outliers(invoices)
    items = report.items
    if category:
        items = [i for i in items if i.category == category]
    if severity:
        items = [i for i in items if i.severity == severity]
    # Augment counts with severity-roll-ups + total for the UI tiles.
    counts = dict(report.counts)
    counts["_total"] = sum(1 for _ in report.items)
    counts["_critical"] = sum(1 for i in report.items if i.severity in ("error", "critical"))
    counts["_warning"] = sum(1 for i in report.items if i.severity == "warning")
    counts["_info"] = sum(1 for i in report.items if i.severity == "info")
    return {
        "as_of": report.as_of.isoformat(),
        "counts": counts,
        "total": len(items),
        "items": [i.__dict__ for i in items[:limit]],
    }


@router.get("/")
def list_exceptions(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    step: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Exception_)
    if severity:
        q = q.filter(Exception_.severity == severity)
    if status:
        q = q.filter(Exception_.status == status)
    if step:
        q = q.filter(Exception_.step == step)
    rows = q.order_by(Exception_.created_at.desc()).limit(limit).all()
    return [
        {
            "exception_id": r.exception_id,
            "run_id": r.run_id,
            "step": r.step,
            "severity": r.severity,
            "status": r.status,
            "error_code": r.error_code,
            "message": r.message,
            "context": r.context,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/suspense")
def list_suspense_items(
    status: Optional[str] = None,
    channel: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(SuspenseItem)
    if status:
        q = q.filter(SuspenseItem.status == status)
    if channel:
        q = q.filter(SuspenseItem.channel == channel)
    rows = q.order_by(SuspenseItem.created_at.desc()).limit(limit).all()
    return [
        {
            "suspense_id": r.suspense_id,
            "run_date": r.run_date.isoformat(),
            "channel": r.channel,
            "channel_reference": r.channel_reference,
            "amount_ghs": float(r.amount_ghs) if r.amount_ghs is not None else None,
            "msisdn": r.msisdn,
            "status": r.status,
            "rider_id": r.rider_id,
            "invoice_id": r.invoice_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.patch("/suspense/{suspense_id}/clear")
def clear_suspense_item(
    suspense_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Clear a suspense item: assign to rider/invoice and mark resolved.

    Body: {rider_id, invoice_id, note, cleared_by_user_id?}
    """
    item = db.query(SuspenseItem).filter(SuspenseItem.suspense_id == suspense_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="suspense item not found")
    if item.status == "resolved":
        raise HTTPException(status_code=409, detail="already cleared")

    item.rider_id = payload.get("rider_id")
    item.invoice_id = payload.get("invoice_id")
    item.clearance_note = payload.get("note")
    item.cleared_by = payload.get("cleared_by_user_id")
    item.cleared_at = datetime.utcnow()
    item.status = "resolved"
    db.commit()
    return {"status": "cleared", "suspense_id": suspense_id}
