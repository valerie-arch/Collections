"""QuickBooks accounting entries — preview + xlsx download endpoints."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from api.agents.collections_report.quickbooks import (
    build_invoice_export,
    build_payment_export,
)
from api.agents.collections_report.quickbooks_xlsx import write_qb_xlsx

router = APIRouter()

INVOICES_DIR = Path("sample_inputs/zoho/invoices")
SUBSCRIPTIONS_DIR = Path("sample_inputs/zoho")
OS_FLEET_CSV = Path("sample_inputs/wahu_os/rider_fleet.csv")


@lru_cache(maxsize=2)
def _load_invoices_cached(mtime_key: float):
    from api.agents.collections_report.parsers import parse_invoice_folder
    return parse_invoice_folder(INVOICES_DIR)


@lru_cache(maxsize=2)
def _load_subs_cached(mtime_key: float):
    from api.agents.collections_report import load_subscription_status_map
    files = sorted(SUBSCRIPTIONS_DIR.glob("zoho_subscriptions*.csv"))
    return load_subscription_status_map(files[-1]) if files else {}


@lru_cache(maxsize=2)
def _load_os_fleet_cached(mtime_key: float):
    from api.agents.collections_report import load_os_fleet_map
    return load_os_fleet_map(OS_FLEET_CSV) if OS_FLEET_CSV.exists() else {}


def _load_invoices():
    if not INVOICES_DIR.exists():
        return []
    mtime = max((p.stat().st_mtime for p in INVOICES_DIR.glob("*.csv")), default=0.0)
    return _load_invoices_cached(mtime)


def _load_subs():
    files = list(SUBSCRIPTIONS_DIR.glob("zoho_subscriptions*.csv"))
    if not files:
        return {}
    return _load_subs_cached(max(f.stat().st_mtime for f in files))


def _load_os_fleet():
    from api.agents.collections_report.sheet_loaders import resolve_fleet_map
    return resolve_fleet_map()


def _build(
    type_: str,
    window_start: date,
    window_end: date,
    fleet: str,
):
    invoices = _load_invoices()
    if not invoices:
        return None
    kwargs = dict(
        window_start=window_start,
        window_end=window_end,
        fleet=fleet,
        subscription_status_map=_load_subs(),
        name_fleet_map=_load_os_fleet(),
    )
    if type_ == "invoices":
        return build_invoice_export(invoices, **kwargs)
    return build_payment_export(invoices, **kwargs)


@router.get("/")
def preview(
    type: str = Query("invoices", pattern="^(invoices|payments)$"),
    window_start: date = Query(...),
    window_end: date = Query(...),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    limit: int = Query(50, ge=1, le=500),
):
    """JSON preview — top-N rows + total + count."""
    if window_end < window_start:
        raise HTTPException(status_code=400, detail="window_end must be >= window_start")
    export = _build(type, window_start, window_end, fleet)
    if export is None:
        return {
            "type": type, "fleet": fleet, "row_count": 0,
            "total_amount_ghs": 0.0, "rows": [],
            "_note": "No invoice data — sync from Drive first.",
        }
    rows = export.invoice_rows if type == "invoices" else export.payment_rows
    return {
        "type": type,
        "fleet": fleet,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "row_count": export.row_count,
        "total_amount_ghs": float(export.total_amount),
        "rows": [asdict(r) for r in rows[:limit]],
    }


@router.get("/download")
def download(
    type: str = Query("invoices", pattern="^(invoices|payments)$"),
    window_start: date = Query(...),
    window_end: date = Query(...),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
):
    if window_end < window_start:
        raise HTTPException(status_code=400, detail="window_end must be >= window_start")
    export = _build(type, window_start, window_end, fleet)
    if export is None:
        raise HTTPException(status_code=400, detail="No invoice data — sync from Drive first.")
    payload = write_qb_xlsx(export)
    filename = (
        f"Wahu_QB_{type}_{fleet}_{window_start.isoformat()}_to_{window_end.isoformat()}.xlsx"
    )
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
