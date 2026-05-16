"""Monthly portfolio trends endpoint."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from api.agents.collections_report.trends import build_trends
from api.agents.collections_report.trends_xlsx import write_trends_xlsx

router = APIRouter()

INVOICES_DIR = Path("sample_inputs/zoho/invoices")
SUBSCRIPTIONS_DIR = Path("sample_inputs/zoho")
OS_FLEET_CSV = Path("sample_inputs/wahu_os/rider_fleet.csv")


@lru_cache(maxsize=2)
def _load_invoices_cached(mtime_key: float):
    from api.agents.collections_report.parsers import parse_invoice_folder
    return parse_invoice_folder(INVOICES_DIR)


def _load_invoices():
    if not INVOICES_DIR.exists():
        return []
    mtime = max(
        (p.stat().st_mtime for p in INVOICES_DIR.glob("*.csv")),
        default=0.0,
    )
    return _load_invoices_cached(mtime)


@lru_cache(maxsize=2)
def _load_subscriptions_cached(mtime_key: float):
    from api.agents.collections_report import load_subscription_status_map
    candidates = sorted(SUBSCRIPTIONS_DIR.glob("zoho_subscriptions*.csv"))
    if not candidates:
        return {}
    return load_subscription_status_map(candidates[-1])


def _load_subscription_map():
    files = list(SUBSCRIPTIONS_DIR.glob("zoho_subscriptions*.csv"))
    if not files:
        return {}
    return _load_subscriptions_cached(max(f.stat().st_mtime for f in files))


@lru_cache(maxsize=2)
def _load_os_fleet_cached(mtime_key: float):
    from api.agents.collections_report import load_os_fleet_map
    return load_os_fleet_map(OS_FLEET_CSV)


def _load_os_fleet():
    if not OS_FLEET_CSV.exists():
        return {}
    return _load_os_fleet_cached(OS_FLEET_CSV.stat().st_mtime)


def _resolve_rider_fleet(
    customer_id: str,
    customer_name: str,
    subs_map: dict[str, tuple[str, bool]],
    name_map: dict[str, str],
) -> str:
    """Fleet rules: OS rider list wins; then subscription TSA flag; default Wahu."""
    if customer_name:
        f = name_map.get(customer_name.strip().lower())
        if f in ("TSA", "Wahu"):
            return f
    sub = subs_map.get(customer_id)
    if sub and sub[1]:
        return "TSA"
    return "Wahu"


def _filter_invoices_by_fleet(invoices, fleet: str):
    if fleet == "All":
        return invoices
    subs = _load_subscription_map()
    names = _load_os_fleet()
    return [
        i for i in invoices
        if _resolve_rider_fleet(i.customer_id, i.customer_name, subs, names) == fleet
    ]


def _build_portfolio(
    months_back: int, as_of: Optional[date], fleet: str
):
    invoices = _load_invoices()
    if not invoices:
        return None
    invoices = _filter_invoices_by_fleet(invoices, fleet)
    if not invoices:
        return None
    # When filtered to TSA/Wahu only, also scope subscription rollups to the
    # matching cohort so cumulative active/recovery/completed match the view.
    subs = _load_subscription_map()
    if fleet != "All":
        active_ids = {i.customer_id for i in invoices if i.customer_id}
        subs = {cid: v for cid, v in subs.items() if cid in active_ids}
    return build_trends(
        invoices,
        as_of=as_of,
        subscription_status_map=subs,
        months_back=months_back,
    )


@router.get("/portfolio")
def portfolio_trends(
    months_back: int = Query(24, ge=3, le=60),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    as_of: Optional[date] = None,
):
    report = _build_portfolio(months_back, as_of, fleet)
    if report is None:
        raise HTTPException(
            status_code=400,
            detail=f"No invoice data for fleet={fleet} — sync from Drive first.",
        )
    return {
        "as_of": report.as_of.isoformat(),
        "fleet": fleet,
        "cumulative": {
            "active": report.cumulative_active,
            "completed": report.cumulative_completed,
            "recovery": report.cumulative_recovery,
        },
        "months": [
            {
                "label": m.label,
                "year": m.year,
                "month": m.month,
                "invoiced_ghs": float(m.invoiced_ghs),
                "collected_ghs": float(m.collected_ghs),
                "outstanding_ghs": float(m.outstanding_ghs),
                "active_riders": m.active_riders,
                "new_riders": m.new_riders,
                "invoices_issued": m.invoices_issued,
                "mrr_ghs": float(m.mrr_ghs),
            }
            for m in report.months
        ],
        "top_10_outstanding": [
            {
                "customer_id": r.customer_id,
                "customer_name": r.customer_name,
                "lifetime_invoiced_ghs": float(r.lifetime_invoiced_ghs),
                "lifetime_collected_ghs": float(r.lifetime_collected_ghs),
                "lifetime_outstanding_ghs": float(r.lifetime_outstanding_ghs),
                "collection_ratio": r.collection_ratio,
            }
            for r in report.top_10_outstanding
        ],
        "bottom_10_ratio": [
            {
                "customer_id": r.customer_id,
                "customer_name": r.customer_name,
                "lifetime_invoiced_ghs": float(r.lifetime_invoiced_ghs),
                "lifetime_collected_ghs": float(r.lifetime_collected_ghs),
                "lifetime_outstanding_ghs": float(r.lifetime_outstanding_ghs),
                "collection_ratio": r.collection_ratio,
            }
            for r in report.bottom_10_ratio
        ],
        "top_10_collected_lifetime": [
            {
                "customer_id": r.customer_id,
                "customer_name": r.customer_name,
                "lifetime_invoiced_ghs": float(r.lifetime_invoiced_ghs),
                "lifetime_collected_ghs": float(r.lifetime_collected_ghs),
                "lifetime_outstanding_ghs": float(r.lifetime_outstanding_ghs),
                "collection_ratio": r.collection_ratio,
            }
            for r in report.top_10_collected_lifetime
        ],
    }


@router.get("/portfolio/download")
def download_portfolio_trends(
    months_back: int = Query(24, ge=3, le=60),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    as_of: Optional[date] = None,
):
    """Download the portfolio trends as a multi-sheet xlsx."""
    report = _build_portfolio(months_back, as_of, fleet)
    if report is None:
        raise HTTPException(
            status_code=400,
            detail=f"No invoice data for fleet={fleet} — sync from Drive first.",
        )
    payload = write_trends_xlsx(report, fleet=fleet)
    filename = f"Wahu_Portfolio_Trends_{fleet}_{report.as_of.isoformat()}.xlsx"
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
