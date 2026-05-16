"""Formal reports endpoints (Reports A/B/C).

Report A (/collections, /collections/download): fully implemented. Pulls
deduped Zoho invoice CSVs from sample_inputs/zoho/invoices/, runs the
report engine, returns JSON or xlsx bytes. Supports lifetime/MTD/custom
view, status filter (active/recovery/completed/all), and fleet filter.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.agents.collections_report import (
    build_report,
    write_report_xlsx,
)
from api.agents.collections_report.memo import build_memo, render_docx, render_pdf, render_text
from api.database import get_db
from api.models.orm import CompletionEvent, SuspenseItem
from api.storage import agencies as agency_store

router = APIRouter()


# ---- Report A: Collections ---------------------------------------------------

INVOICES_DIR = Path("sample_inputs/zoho/invoices")
SUBSCRIPTIONS_DIR = Path("sample_inputs/zoho")
OS_FLEET_CSV = Path("sample_inputs/wahu_os/rider_fleet.csv")


@lru_cache(maxsize=2)
def _load_invoices_cached(mtime_key: float):
    from api.agents.collections_report.parsers import parse_invoice_folder
    return parse_invoice_folder(INVOICES_DIR)


@lru_cache(maxsize=2)
def _load_subscriptions_cached(mtime_key: float):
    """Load the most-recent zoho_subscriptions_*.csv as a status map."""
    from api.agents.collections_report import load_subscription_status_map
    candidates = sorted(SUBSCRIPTIONS_DIR.glob("zoho_subscriptions*.csv"))
    if not candidates:
        return {}
    return load_subscription_status_map(candidates[-1])


@lru_cache(maxsize=2)
def _load_os_fleet_cached(mtime_key: float):
    from api.agents.collections_report import load_os_fleet_map
    if not OS_FLEET_CSV.exists():
        return {}
    return load_os_fleet_map(OS_FLEET_CSV)


def _load_invoices():
    if not INVOICES_DIR.exists():
        return []
    mtime = max(
        (p.stat().st_mtime for p in INVOICES_DIR.glob("*.csv")),
        default=0.0,
    )
    return _load_invoices_cached(mtime)


def _load_subscription_map():
    if not SUBSCRIPTIONS_DIR.exists():
        return {}
    files = list(SUBSCRIPTIONS_DIR.glob("zoho_subscriptions*.csv"))
    if not files:
        return {}
    return _load_subscriptions_cached(max(f.stat().st_mtime for f in files))


def _load_os_fleet():
    if not OS_FLEET_CSV.exists():
        return {}
    return _load_os_fleet_cached(OS_FLEET_CSV.stat().st_mtime)


def _build(
    view: str,
    status: str,
    fleet: str,
    as_of: Optional[date],
    window_start: Optional[date],
    window_end: Optional[date],
    agency: Optional[str] = None,
):
    invoices = _load_invoices()
    if not invoices:
        return None
    return build_report(
        invoices,
        view=view,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        fleet=fleet,  # type: ignore[arg-type]
        as_of=as_of,
        window_start=window_start,
        window_end=window_end,
        subscription_status_map=_load_subscription_map(),
        name_fleet_map=_load_os_fleet(),
        agency_map=agency_store.agency_map(),
        agency_filter=agency if agency and agency != "All" else None,
    )


@router.get("/collections")
def collections_report(
    view: str = Query("mtd", pattern="^(mtd|lifetime|custom)$"),
    status: str = Query("active", pattern="^(active|recovery|completed|all)$"),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    agency: Optional[str] = None,
    as_of: Optional[date] = None,
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
):
    data = _build(view, status, fleet, as_of, window_start, window_end, agency)
    if data is None:
        return {
            "report": "A — Collections",
            "view": view,
            "status_filter": status,
            "fleet": fleet,
            "_note": (
                "No invoice CSVs found in sample_inputs/zoho/invoices/. "
                "Click 'Sync Drive' on the Reports page, or drop CSVs in that folder."
            ),
            "active_riders": 0,
            "headlines": {},
            "bands": [],
            "ageing": [],
            "riders": [],
        }

    return {
        "report": "A — Collections",
        "view": data.view,
        "status_filter": data.status_filter,
        "fleet": data.fleet_filter,
        "as_of": data.as_of.isoformat(),
        "window": {
            "start": data.window_start.isoformat(),
            "end": data.window_end.isoformat(),
            "label": data.window_label,
        },
        "active_riders": data.active_riders,
        "total_rider_population": data.total_rider_population,
        "headlines": {
            "lifetime_invoiced_ghs": float(data.lifetime_invoiced_ghs),
            "lifetime_collected_ghs": float(data.lifetime_collected_ghs),
            "lifetime_outstanding_ghs": float(data.lifetime_outstanding_ghs),
            "open_invoice_lines": data.open_invoice_lines,
            "cash_in_window_ghs": float(data.cash_in_window_ghs),
            "cash_applied_to_period_ghs": float(data.cash_applied_to_period_ghs),
            "cash_applied_to_prior_ghs": float(data.cash_applied_to_prior_ghs),
            "riders_paid_in_window": data.riders_paid_in_window,
            "payment_activity_rate": (
                data.riders_paid_in_window / data.active_riders
                if data.active_riders > 0
                else 0.0
            ),
            "collection_ratio": (
                float(data.lifetime_collected_ghs / data.lifetime_invoiced_ghs)
                if data.lifetime_invoiced_ghs > 0
                else 0.0
            ),
        },
        "bands": [
            {
                "band": b.band,
                "riders": b.riders,
                "outstanding_ghs": float(b.outstanding_ghs),
                "definition": b.definition,
            }
            for b in data.risk_bands
        ],
        "ageing": [
            {
                "label": a.label,
                "open_invoices": a.open_invoices,
                "outstanding_ghs": float(a.outstanding_ghs),
            }
            for a in data.ageing
        ],
        "riders": [
            {
                "customer_id": s.customer_id,
                "customer_name": s.customer_name,
                "first_invoice": s.first_invoice.isoformat(),
                "last_invoice": s.last_invoice.isoformat(),
                "months_since_last_invoice": s.months_since_last_invoice,
                "lifetime_invoices": s.lifetime_invoices,
                "open_invoices": s.open_invoices,
                "lifetime_invoiced_ghs": float(s.lifetime_invoiced_ghs),
                "lifetime_collected_ghs": float(s.lifetime_collected_ghs),
                "lifetime_outstanding_ghs": float(s.lifetime_outstanding_ghs),
                "collection_ratio": s.collection_ratio,
                "risk_band": s.risk_band,
                "status": s.status,
                "fleet": s.fleet,
                "agency": s.agency,
                "plans": s.plans,
            }
            for s in data.scorecards
        ],
    }


@router.get("/collections/download")
def download_collections_report(
    view: str = Query("mtd", pattern="^(mtd|lifetime|custom)$"),
    status: str = Query("active", pattern="^(active|recovery|completed|all)$"),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    agency: Optional[str] = None,
    as_of: Optional[date] = None,
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
):
    data = _build(view, status, fleet, as_of, window_start, window_end, agency)
    if data is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "No invoice CSVs found. Sync from Drive or drop CSVs into "
                "sample_inputs/zoho/invoices/ first."
            ),
        )
    payload = write_report_xlsx(data)
    filename = (
        f"Wahu_Collections_{data.view}_{data.status_filter}_"
        f"{data.as_of.isoformat()}.xlsx"
    )
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_memo_or_404(
    view: str, status: str, fleet: str, agency: Optional[str],
    as_of: Optional[date], window_start: Optional[date], window_end: Optional[date],
):
    data = _build(view, status, fleet, as_of, window_start, window_end, agency)
    if data is None:
        raise HTTPException(status_code=400, detail="No invoice data — sync from Drive first.")
    return data, build_memo(data)


@router.get("/collections/memo")
def collections_memo(
    view: str = Query("mtd", pattern="^(mtd|lifetime|custom)$"),
    status: str = Query("active", pattern="^(active|recovery|completed|all)$"),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    agency: Optional[str] = None,
    as_of: Optional[date] = None,
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
):
    """Plain-text memo preview for the in-app modal."""
    data, memo = _build_memo_or_404(view, status, fleet, agency, as_of, window_start, window_end)
    return {
        "view": data.view,
        "status_filter": data.status_filter,
        "fleet": data.fleet_filter,
        "as_of": data.as_of.isoformat(),
        "window_label": data.window_label,
        "memo_text": render_text(memo),
    }


@router.get("/collections/memo.pdf")
def collections_memo_pdf(
    view: str = Query("mtd", pattern="^(mtd|lifetime|custom)$"),
    status: str = Query("active", pattern="^(active|recovery|completed|all)$"),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    agency: Optional[str] = None,
    as_of: Optional[date] = None,
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
):
    data, memo = _build_memo_or_404(view, status, fleet, agency, as_of, window_start, window_end)
    payload = render_pdf(memo)
    filename = f"Wahu_Memo_{data.view}_{data.status_filter}_{data.as_of.isoformat()}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/collections/memo.docx")
def collections_memo_docx(
    view: str = Query("mtd", pattern="^(mtd|lifetime|custom)$"),
    status: str = Query("active", pattern="^(active|recovery|completed|all)$"),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    agency: Optional[str] = None,
    as_of: Optional[date] = None,
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
):
    """.docx — open in Google Docs via File → Open → Upload."""
    data, memo = _build_memo_or_404(view, status, fleet, agency, as_of, window_start, window_end)
    payload = render_docx(memo)
    filename = f"Wahu_Memo_{data.view}_{data.status_filter}_{data.as_of.isoformat()}.docx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---- Reports B/C (skeletons until Sprints 4–8) ------------------------------


def _period_window(period: str) -> tuple[date, date]:
    today = date.today()
    if period == "current_week":
        start = today - timedelta(days=today.weekday())
        return start, today
    if period == "month_to_date":
        return today.replace(day=1), today
    if period == "today":
        return today, today
    return today.replace(day=1), today


def _fleet_filter(query, column, fleet: Optional[str]):
    if fleet and fleet != "All":
        return query.filter(column == fleet)
    return query


@router.get("/recovery")
def recovery_report(
    period: str = "month_to_date",
    fleet: Optional[str] = "All",
    db: Session = Depends(get_db),
):
    """Report B — aged debt and churned riders (full impl in Sprints 4–5)."""
    start, end = _period_window(period)
    suspense_open = (
        db.query(SuspenseItem)
        .filter(
            SuspenseItem.run_date.between(start, end),
            SuspenseItem.status == "open",
        )
        .with_entities(func.coalesce(func.sum(SuspenseItem.amount_ghs), 0))
        .scalar()
    )
    return {
        "report": "B — Recovery",
        "period": period,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "fleet": fleet,
        "open_suspense_ghs": float(suspense_open or 0),
        "churned_riders": 0,
        "_note": "Aged-debt aggregation implemented in Sprint 5.",
    }


@router.get("/completed")
def completed_riders_report(
    period: str = "month_to_date",
    fleet: Optional[str] = "All",
    db: Session = Depends(get_db),
):
    """Report C — riders fully paid out in the window."""
    start, end = _period_window(period)
    q = _fleet_filter(
        db.query(CompletionEvent).filter(
            CompletionEvent.completion_date.between(start, end)
        ),
        CompletionEvent.fleet,
        fleet,
    )
    events = q.all()
    total_paid = sum((float(e.total_amount_paid_ghs) for e in events), 0.0)
    return {
        "report": "C — Completed Riders",
        "period": period,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "fleet": fleet,
        "completed_count": len(events),
        "total_amount_paid_ghs": total_paid,
        "events": [
            {
                "subscription_id": e.subscription_id,
                "rider_id": e.rider_id,
                "completion_date": e.completion_date.isoformat(),
                "total_weeks_billed": e.total_weeks_billed,
                "total_amount_paid_ghs": float(e.total_amount_paid_ghs),
                "fleet": e.fleet,
            }
            for e in events
        ],
    }
