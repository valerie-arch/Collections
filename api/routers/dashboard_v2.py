"""Portfolio dashboard v2 — 10-KPI snapshot.

Single endpoint returns the three-layer dashboard (Behavioral / Financial /
Portfolio) in one round-trip. Caching keys on (period, start, end, fleet)
so the same selector hits warm data.

KPIs are computed by api/agents/dashboard_v2/compute.py — see that module
for the per-KPI formulas and the "available=False" semantics for KPIs that
depend on data we haven't shipped yet (snapshot writer for KPIs 6 + 8).
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.agents.dashboard_v2.compute import (
    blocked_cure_rate, blocked_roll_rates,
    compute_active_payer_rate, compute_aging, compute_lifetime_efficiency,
    compute_monthly_collections, compute_mrr, compute_net_charge_off,
    compute_on_time_rate, compute_recovery_on_churned, resolve_window,
)
from collections_v3.io_.write_offs import WriteOffLedger, load_write_off_ledger

router = APIRouter()


INVOICES_DIR = Path("sample_inputs/zoho/invoices")
SUBSCRIPTIONS_DIR = Path("sample_inputs/zoho")


# ---------------------------------------------------------------------------
# Cached loaders (mtime-keyed so disk changes invalidate)
# ---------------------------------------------------------------------------

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


@lru_cache(maxsize=2)
def _load_subs_cached(mtime_key: float):
    from api.agents.collections_report.parsers import (
        load_subscription_status_dates, load_subscription_status_map,
    )
    candidates = sorted(SUBSCRIPTIONS_DIR.glob("zoho_subscriptions*.csv"))
    if not candidates:
        return {}, {}
    latest = candidates[-1]
    return (
        load_subscription_status_map(latest),
        load_subscription_status_dates(latest),
    )


def _load_subs():
    files = list(SUBSCRIPTIONS_DIR.glob("zoho_subscriptions*.csv"))
    if not files:
        return {}, {}
    return _load_subs_cached(max(f.stat().st_mtime for f in files))


def _load_ledger() -> Optional[WriteOffLedger]:
    """Returns None if neither WRITE_OFFS_SHEET_ID nor a local template
    exist — KPIs 9 + 2-net then render as 'no data'."""
    try:
        return load_write_off_ledger()
    except FileNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        # Sheet existed but failed to parse; don't take the whole endpoint
        # down — just degrade the affected KPIs.
        import logging
        logging.getLogger(__name__).warning(
            "write-off ledger failed to load: %s", e,
        )
        return None


def _filter_by_fleet(invoices, fleet: str):
    if fleet == "All":
        return invoices
    # Reuse the existing fleet resolver from the legacy trends router so
    # the two pages agree on fleet attribution.
    from api.routers.trends import (
        _load_os_fleet, _load_subscription_map, _resolve_rider_fleet,
    )
    subs = _load_subscription_map()
    names = _load_os_fleet()
    return [
        i for i in invoices
        if _resolve_rider_fleet(i.customer_id, i.customer_name, subs, names) == fleet
    ]


def _filter_by_agency(invoices, agency: str):
    """Restrict invoices to riders assigned to a specific 3rd-party agency
    (Hortta / TSAC). Reuses Reports' resolver so the two pages agree."""
    if agency == "All":
        return invoices
    from api.routers.reports import _resolve_agencies
    agency_map = _resolve_agencies(invoices)
    return [
        i for i in invoices if agency_map.get(i.customer_id) == agency
    ]


def _serialize(obj):
    """asdict() that preserves date/Decimal as JSON-safe primitives."""
    if is_dataclass(obj):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


@router.get("/trends")
def dashboard_trends(
    lookback: str = Query("12m", pattern="^(3m|6m|12m|all)$"),
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    agency: str = Query("All", pattern="^(All|Hortta|TSAC)$"),
    as_of: Optional[date] = None,
):
    """Four trend series (Collections Rate, MRR Movement, Charge-off,
    Lifetime Efficiency) over the requested lookback window."""
    from api.agents.dashboard_v2.trends import (
        charge_off_trend, collections_rate_trend, lifetime_efficiency_trend,
        month_axis, mrr_movement_trend,
    )

    invoices = _load_invoices()
    if not invoices:
        raise HTTPException(
            status_code=400,
            detail="No invoice data — sync from Drive first.",
        )
    invoices = _filter_by_fleet(invoices, fleet)
    invoices = _filter_by_agency(invoices, agency)
    sub_map, sub_dates = _load_subs()
    ledger = _load_ledger()

    today = as_of or date.today()
    axis = month_axis(today, lookback)

    cr = collections_rate_trend(invoices, axis)
    mrr = mrr_movement_trend(
        invoices, axis,
        subscription_status_map=sub_map,
        subscription_status_dates=sub_dates,
    )
    co = charge_off_trend(ledger, axis)
    eff = lifetime_efficiency_trend(invoices, axis)

    return {
        "as_of": today.isoformat(),
        "fleet": fleet,
        "lookback": lookback,
        "axis": {"labels": axis.labels},
        "collections_rate": _serialize(cr),
        "mrr_movement": _serialize(mrr),
        "charge_off": _serialize(co),
        "lifetime_efficiency": _serialize(eff),
    }


@router.get("/snapshot")
def dashboard_snapshot(
    period: str = Query("mtd", pattern="^(mtd|lifetime|custom)$"),
    start: Optional[date] = None,
    end: Optional[date] = None,
    fleet: str = Query("All", pattern="^(All|Wahu|TSA)$"),
    agency: str = Query("All", pattern="^(All|Hortta|TSAC)$"),
    as_of: Optional[date] = None,
):
    """Return all 10 KPIs grouped by layer."""
    invoices = _load_invoices()
    if not invoices:
        raise HTTPException(
            status_code=400,
            detail="No invoice data — sync from Drive via /api/drives/sync first.",
        )
    invoices = _filter_by_fleet(invoices, fleet)
    invoices = _filter_by_agency(invoices, agency)
    sub_map, sub_dates = _load_subs()
    ledger = _load_ledger()

    today = as_of or date.today()
    window = resolve_window(period, today, start, end)

    # Compute everything.
    active_payer = compute_active_payer_rate(
        invoices, as_of=today, subscription_status_map=sub_map,
    )
    on_time = compute_on_time_rate(invoices, window=window)
    roll = blocked_roll_rates()

    monthly = compute_monthly_collections(
        invoices, window=window, write_off_ledger=ledger,
    )
    mrr = compute_mrr(
        invoices, as_of=today, window=window,
        subscription_status_map=sub_map,
        subscription_status_dates=sub_dates,
    )

    aging = compute_aging(invoices, as_of=today)
    lifetime = compute_lifetime_efficiency(invoices)
    cure = blocked_cure_rate()
    nco = compute_net_charge_off(
        ledger, window=window,
        avg_outstanding_ghs=aging.total_outstanding_ghs,
    )
    recovery = compute_recovery_on_churned(
        invoices, window=window,
        subscription_status_map=sub_map,
        subscription_status_dates=sub_dates,
    )

    return {
        "as_of": today.isoformat(),
        "fleet": fleet,
        "window": _serialize(window),
        "data_sources": {
            "invoices": len(invoices),
            "write_off_ledger_loaded": ledger is not None,
            "subscriptions_loaded": bool(sub_map),
        },
        "behavioral": {
            "active_payer_rate": _serialize(active_payer),
            "on_time_payment_rate": _serialize(on_time),
            "roll_rates": _serialize(roll),
        },
        "financial": {
            "monthly_collections_rate": _serialize(monthly),
            "mrr": _serialize(mrr),
        },
        "portfolio": {
            "aging": _serialize(aging),
            "lifetime_efficiency": _serialize(lifetime),
            "cure_rate": _serialize(cure),
            "net_charge_off": _serialize(nco),
            "recovery_on_churned": _serialize(recovery),
        },
    }
