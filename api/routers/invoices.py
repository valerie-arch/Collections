"""Filterable invoice register.

Powers the /invoices page. Returns deduped invoice rows with the same
VIEW (MTD/Lifetime/Custom) + STATUS (Active/Recovery/Completed/All) +
FLEET (All/Wahu/TSA) filter triplet used by the Reports page, plus three
KPI summaries:
  1. Number of invoices issued (segmented by stream)
  2. Total value invoiced (GHS)
  3. Invoice aging — Current / 1-30 / 31-60 / 61-90 / 90+ DPD on
     unpaid balance.

Stream segmentation is heuristic for now and documented inline; refine
once we have an explicit stream tag on the invoice corpus.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.agents.dashboard_v2.compute import compute_aging, resolve_window

router = APIRouter()


INVOICES_DIR = Path("sample_inputs/zoho/invoices")
SUBSCRIPTIONS_DIR = Path("sample_inputs/zoho")

# Stream segmentation thresholds. The 70 GHS daily-debit pattern lives at
# the low end; non-rider customers (B2B / dealership) typically have
# customer_ids absent from the subscription map.
DAILY_DEBIT_CEILING_GHS = Decimal("100")


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


def _classify_stream(inv, sub_map: dict[str, tuple[str, bool]]) -> str:
    """Heuristic stream classifier:
      * rider_daily  — total ≤ GHS 100 (the 70-GHS daily debit pattern)
      * rider_larger — total > GHS 100 AND customer present in subs map
      * b2b_dealer   — customer NOT in subs map (B2B fleet or dealership)
    """
    if inv.customer_id and inv.customer_id not in sub_map:
        return "b2b_dealer"
    if inv.total <= DAILY_DEBIT_CEILING_GHS:
        return "rider_daily"
    return "rider_larger"


STREAM_LABEL = {
    "rider_daily": "Rider daily debit (≤ GHS 100)",
    "rider_larger": "Rider catch-up / larger",
    "b2b_dealer": "B2B / Dealership",
}


@router.get("/list")
def list_invoices(
    view: str = Query("mtd", pattern="^(mtd|lifetime|custom)$"),
    status: str = Query("active", pattern="^(active|recovery|completed|all)$"),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    start: Optional[date] = None,
    end: Optional[date] = None,
    q: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    as_of: Optional[date] = None,
):
    """Filtered invoice register + KPI summaries."""
    invoices = _load_invoices()
    if not invoices:
        raise HTTPException(
            status_code=400,
            detail="No invoice data — sync from Drive via /api/drives/sync first.",
        )

    today = as_of or date.today()
    window = resolve_window(view, today, start, end)

    # Lazy-load filter maps used by fleet/status resolvers.
    from api.routers.trends import (
        _load_os_fleet, _load_subscription_map, _resolve_rider_fleet,
    )
    sub_map = _load_subscription_map()
    name_map = _load_os_fleet()

    # Fleet filter (matches Reports page semantics).
    if fleet != "All":
        invoices = [
            i for i in invoices
            if _resolve_rider_fleet(i.customer_id, i.customer_name, sub_map, name_map) == fleet
        ]

    # Status filter — by subscription status.
    if status != "all":
        invoices = [
            i for i in invoices
            if (sub_map.get(i.customer_id) or ("active", False))[0] == status
        ]

    # Date window: lifetime skips date filter; mtd/custom restrict by
    # invoice_date inside [window.start, window.end].
    if view != "lifetime":
        invoices = [
            i for i in invoices
            if window.start <= i.invoice_date <= window.end
        ]

    # Free-text search across customer name + invoice id/number + customer id.
    if q:
        needle = q.strip().lower()
        if needle:
            invoices = [
                i for i in invoices
                if needle in (i.customer_name or "").lower()
                or needle in (i.invoice_id or "").lower()
                or needle in (i.customer_id or "").lower()
            ]

    # Sort newest-first.
    invoices.sort(key=lambda i: i.invoice_date, reverse=True)

    # --- KPI 1: count + value per stream ---
    by_stream: dict[str, dict] = {
        s: {"stream": s, "label": lab, "count": 0, "total_ghs": Decimal("0")}
        for s, lab in STREAM_LABEL.items()
    }
    for inv in invoices:
        s = _classify_stream(inv, sub_map)
        by_stream[s]["count"] += 1
        by_stream[s]["total_ghs"] += inv.total

    # --- KPI 3: aging — reuse the dashboard's compute_aging helper ---
    aging = compute_aging(invoices, as_of=today)

    total = len(invoices)
    total_invoiced = sum((i.total for i in invoices), Decimal("0"))
    total_outstanding = sum(
        (i.balance for i in invoices if i.balance > 0), Decimal("0"),
    )
    open_count = sum(1 for i in invoices if i.balance > 0)

    page = invoices[offset:offset + limit]

    return {
        "as_of": today.isoformat(),
        "window": {
            "period": window.period, "start": window.start.isoformat(),
            "end": window.end.isoformat(), "label": window.label,
        },
        "filters": {"view": view, "status": status, "fleet": fleet},
        "summary": {
            "total_invoices": total,
            "open_count": open_count,
            "total_invoiced_ghs": round(float(total_invoiced), 2),
            "total_outstanding_ghs": round(float(total_outstanding), 2),
            "by_stream": [
                {
                    "stream": s["stream"], "label": s["label"],
                    "count": s["count"],
                    "total_ghs": round(float(s["total_ghs"]), 2),
                }
                for s in by_stream.values()
            ],
        },
        "aging": {
            "as_of": aging.as_of.isoformat(),
            "total_outstanding_ghs": aging.total_outstanding_ghs,
            "buckets": [
                {
                    "label": b.label, "rider_count": b.rider_count,
                    "open_invoice_count": b.open_invoice_count,
                    "ghs": b.ghs, "pct_of_ghs": b.pct_of_ghs,
                }
                for b in aging.buckets
            ],
        },
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
                "stream": _classify_stream(i, sub_map),
            }
            for i in page
        ],
    }
