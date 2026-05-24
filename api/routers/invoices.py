"""Filterable invoice listing.

Returns deduped invoice rows from the Zoho corpus with filters for status,
fleet, agency, date range, and free-text search. Used by the new /invoices
page in the web app.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


INVOICES_DIR = Path("sample_inputs/zoho/invoices")
SUBSCRIPTIONS_DIR = Path("sample_inputs/zoho")


@lru_cache(maxsize=2)
def _load_invoices_cached(mtime_key: float):
    from api.agents.collections_report.parsers import parse_invoice_folder
    return parse_invoice_folder(INVOICES_DIR)


def _load_invoices():
    if not INVOICES_DIR.exists():
        return []
    mtime = max(
        (p.stat().st_mtime for p in INVOICES_DIR.glob("*.csv")), default=0.0,
    )
    return _load_invoices_cached(mtime)


@router.get("/list")
def list_invoices(
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    status: str = Query("all", pattern="^(all|open|paid|overdue|partial|void|draft)$"),
    start: Optional[date] = None,
    end: Optional[date] = None,
    q: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """Return filtered invoice rows + summary counters."""
    invoices = _load_invoices()
    if not invoices:
        raise HTTPException(
            status_code=400,
            detail="No invoice data — sync from Drive via /api/drives/sync first.",
        )

    # Fleet filter — reuse the legacy trends router's resolver so attribution
    # is consistent across pages.
    if fleet != "All":
        from api.routers.trends import (
            _load_os_fleet, _load_subscription_map, _resolve_rider_fleet,
        )
        subs = _load_subscription_map()
        names = _load_os_fleet()
        invoices = [
            i for i in invoices
            if _resolve_rider_fleet(i.customer_id, i.customer_name, subs, names) == fleet
        ]

    # Date range filter (on invoice_date).
    if start is not None:
        invoices = [i for i in invoices if i.invoice_date >= start]
    if end is not None:
        invoices = [i for i in invoices if i.invoice_date <= end]

    # Status filter. Treat "open" as balance > 0; other statuses match the
    # raw Zoho status field.
    if status == "open":
        invoices = [i for i in invoices if i.balance > 0]
    elif status == "paid":
        invoices = [i for i in invoices if i.balance == 0 and i.total > 0]
    elif status != "all":
        invoices = [i for i in invoices if (i.status or "").lower() == status]

    # Free-text search across customer name + invoice id/number.
    if q:
        needle = q.strip().lower()
        if needle:
            invoices = [
                i for i in invoices
                if needle in (i.customer_name or "").lower()
                or needle in (i.invoice_id or "").lower()
                or needle in (i.customer_id or "").lower()
            ]

    # Newest first.
    invoices.sort(key=lambda i: i.invoice_date, reverse=True)

    total = len(invoices)
    page = invoices[offset:offset + limit]

    total_invoiced = sum(float(i.total) for i in invoices)
    total_outstanding = sum(float(i.balance) for i in invoices if i.balance > 0)
    open_count = sum(1 for i in invoices if i.balance > 0)

    return {
        "total": total,
        "open_count": open_count,
        "total_invoiced_ghs": round(total_invoiced, 2),
        "total_outstanding_ghs": round(total_outstanding, 2),
        "limit": limit,
        "offset": offset,
        "rows": [
            {
                "invoice_id": i.invoice_id,
                "customer_id": i.customer_id,
                "customer_name": i.customer_name,
                "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None,
                "due_date": i.due_date.isoformat() if i.due_date else None,
                "status": i.status,
                "total_ghs": float(i.total),
                "balance_ghs": float(i.balance),
                "last_payment_date": (
                    i.last_payment_date.isoformat() if i.last_payment_date else None
                ),
            }
            for i in page
        ],
    }
