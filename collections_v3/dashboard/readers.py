"""Read-side computations for the 5 dashboard endpoints.

Inputs come from two places:
  * The activity log (collector productivity records)
  * The latest pipeline artifacts in artifacts/ (rider_outstanding,
    suspense, agency_performance, etc.)

Each reader honours the same {fleet, agency, date|period} filter triple
as the CLI.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from collections_v3.dashboard.activity_log import list_all as list_activities


ARTIFACTS_DIR = Path("artifacts")


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _filter_activities(
    items: list[dict], *,
    agency: Optional[str] = None,
    on_date: Optional[date] = None,
) -> list[dict]:
    out = []
    for it in items:
        if agency and agency != "All" and it.get("agency") != agency:
            continue
        if on_date is not None:
            ts = _parse_ts(it.get("timestamp", ""))
            if ts is None or ts.date() != on_date:
                continue
        out.append(it)
    return out


def _current_artifacts_dir() -> Path:
    """Always look up the module-level constant at call time so tests can
    monkeypatch `readers.ARTIFACTS_DIR` and have it actually take effect."""
    return ARTIFACTS_DIR


def _latest_artifact(prefix: str, *, artifacts_dir: Optional[Path] = None) -> Optional[Path]:
    artifacts_dir = artifacts_dir or _current_artifacts_dir()
    if not artifacts_dir.exists():
        return None
    matches = sorted(
        artifacts_dir.glob(f"{prefix}_*.xlsx"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return matches[0] if matches else None


def _read_excel(p: Optional[Path], **kw) -> pd.DataFrame:
    """Read an XLSX and coerce NaN -> "" so the result is JSON-safe."""
    if p is None or not p.exists():
        return pd.DataFrame()
    df = pd.read_excel(p, engine="openpyxl", **kw)
    return df.where(df.notna(), "")


def _read_outstanding(artifacts_dir: Optional[Path] = None) -> pd.DataFrame:
    return _read_excel(
        _latest_artifact("rider_outstanding", artifacts_dir=artifacts_dir),
        sheet_name="rider_outstanding",
    )


def _read_suspense(artifacts_dir: Optional[Path] = None) -> pd.DataFrame:
    return _read_excel(_latest_artifact("suspense", artifacts_dir=artifacts_dir))


def _read_agency_performance(artifacts_dir: Optional[Path] = None) -> pd.DataFrame:
    return _read_excel(_latest_artifact("agency_performance", artifacts_dir=artifacts_dir))


def _read_qb_upload_log() -> pd.DataFrame:
    p = _current_artifacts_dir() / "qb_upload_log.xlsx"
    return _read_excel(p if p.exists() else None)


def _jsonsafe_records(df: pd.DataFrame) -> list[dict]:
    """to_dict('records'), but with NaN coerced to None so FastAPI can
    serialise. Numeric columns keep their type."""
    if df is None or df.empty:
        return []
    # Replace pandas NaN with None for the JSON encoder.
    safe = df.where(df.notna(), None)
    return safe.to_dict("records")


# ---------------------------------------------------------------------------
# /dashboard/overview
# ---------------------------------------------------------------------------

def overview(
    *,
    fleet: str = "All",
    agency: str = "All",
    on_date: Optional[date] = None,
    artifacts_dir: Optional[Path] = None,
) -> dict:
    on_date = on_date or date.today()
    outstanding = _read_outstanding(artifacts_dir)
    if not outstanding.empty:
        if fleet and fleet != "All":
            outstanding = outstanding[outstanding["fleet"].astype(str) == fleet]
        if agency and agency != "All":
            outstanding = outstanding[outstanding["agency"].astype(str) == agency]

    wahu_riders = int((outstanding["fleet"].astype(str) == "Wahu").sum()) if not outstanding.empty else 0
    tsa_riders = int((outstanding["fleet"].astype(str) == "TSA").sum()) if not outstanding.empty else 0
    active_base = wahu_riders + tsa_riders

    activities = list_activities()
    today_acts = _filter_activities(activities, agency=agency if agency != "All" else None, on_date=on_date)
    engaged_today = len({a["rider_id"] for a in today_acts})
    actions_logged_today = len(today_acts)
    engagement_pct = round(100 * engaged_today / active_base, 1) if active_base else 0.0
    actions_per_engaged = round(actions_logged_today / engaged_today, 2) if engaged_today else 0.0

    # 7-day engagement avg (excluding today).
    base_start = on_date - timedelta(days=7)
    last7 = _filter_activities(activities, agency=agency if agency != "All" else None)
    days_to_engaged: dict[date, set] = {}
    for a in last7:
        ts = _parse_ts(a.get("timestamp", ""))
        if ts is None:
            continue
        d = ts.date()
        if base_start <= d < on_date:
            days_to_engaged.setdefault(d, set()).add(a["rider_id"])
    days_count = len(days_to_engaged) or 1
    engaged_7day_avg = round(sum(len(v) for v in days_to_engaged.values()) / days_count, 1)

    # Collected today (payment_received action_type only).
    collected_today = round(sum(
        float(a.get("amount_ghs", 0) or 0)
        for a in today_acts if a.get("action_type") == "payment_received"
    ), 2)
    same_weekday_last_week = on_date - timedelta(days=7)
    last_week_acts = _filter_activities(
        activities, agency=agency if agency != "All" else None,
        on_date=same_weekday_last_week,
    )
    collected_same_weekday_last_week = round(sum(
        float(a.get("amount_ghs", 0) or 0)
        for a in last_week_acts if a.get("action_type") == "payment_received"
    ), 2)

    return {
        "filters": {"fleet": fleet, "agency": agency, "date": on_date.isoformat()},
        "active_customer_base": {
            "total": active_base, "wahu": wahu_riders, "tsa": tsa_riders,
        },
        "engagement": {
            "engaged_today": engaged_today,
            "engagement_pct": engagement_pct,
            "engaged_7day_avg": engaged_7day_avg,
        },
        "actions": {
            "logged_today": actions_logged_today,
            "actions_per_engaged_rider": actions_per_engaged,
        },
        "collected": {
            "today_ghs": collected_today,
            "same_weekday_last_week_ghs": collected_same_weekday_last_week,
        },
        "qb_sync": _qb_sync_strip(),
    }


def _qb_sync_strip() -> list[dict]:
    """Per-ISO-week chip status from qb_upload_log.xlsx."""
    df = _read_qb_upload_log()
    if df.empty:
        return []
    out = []
    for r in df.itertuples(index=False):
        out.append({"week": str(getattr(r, "week", "")), "status": "synced",
                    "confirmation_id": str(getattr(r, "qb_confirmation_id", "")),
                    "uploaded_at": str(getattr(r, "uploaded_at", ""))})
    return out


# ---------------------------------------------------------------------------
# /dashboard/activities
# ---------------------------------------------------------------------------

def activities(
    *,
    fleet: str = "All",
    agency: str = "All",
    on_date: Optional[date] = None,
) -> dict:
    on_date = on_date or date.today()
    items = list_activities()
    today_items = _filter_activities(items, agency=agency if agency != "All" else None, on_date=on_date)

    # Actions by type with outcome breakdown.
    by_type: dict[str, dict] = {}
    for a in today_items:
        t = a.get("action_type", "")
        slot = by_type.setdefault(t, {"count": 0, "outcomes": {}, "amount_ghs": 0.0})
        slot["count"] += 1
        slot["amount_ghs"] = round(slot["amount_ghs"] + float(a.get("amount_ghs", 0) or 0), 2)
        outc = a.get("outcome", "") or "(none)"
        slot["outcomes"][outc] = slot["outcomes"].get(outc, 0) + 1

    # By agency.
    outstanding = _read_outstanding()
    base_by_agency: dict[str, int] = {}
    if not outstanding.empty:
        for ag, sub in outstanding.groupby("agency"):
            base_by_agency[str(ag)] = int(len(sub))
    engaged_by_agency: dict[str, set] = {}
    actions_by_agency: dict[str, int] = {}
    for a in today_items:
        ag = a.get("agency", "")
        engaged_by_agency.setdefault(ag, set()).add(a.get("rider_id", ""))
        actions_by_agency[ag] = actions_by_agency.get(ag, 0) + 1
    by_agency = []
    for ag in sorted(set(list(base_by_agency.keys()) + list(engaged_by_agency.keys()))):
        base = base_by_agency.get(ag, 0)
        engaged = len(engaged_by_agency.get(ag, set()))
        by_agency.append({
            "agency": ag, "engaged": engaged, "total_customer_base": base,
            "actions": actions_by_agency.get(ag, 0),
            "engagement_pct": round(100 * engaged / base, 1) if base else 0.0,
        })

    # Hour histogram.
    hist: dict[int, int] = {h: 0 for h in range(24)}
    for a in today_items:
        ts = _parse_ts(a.get("timestamp", ""))
        if ts is not None:
            hist[ts.hour] += 1
    peak = max(hist, key=hist.get) if any(hist.values()) else None

    return {
        "filters": {"fleet": fleet, "agency": agency, "date": on_date.isoformat()},
        "by_type": by_type,
        "by_agency": by_agency,
        "hour_histogram": [{"hour": h, "count": hist[h]} for h in range(24)],
        "peak_hour": peak,
        "total_actions": len(today_items),
    }


# ---------------------------------------------------------------------------
# /dashboard/performance
# ---------------------------------------------------------------------------

def performance(*, fleet: str = "All", agency: str = "All", period: str = "Week") -> dict:
    df = _read_agency_performance()
    if not df.empty and agency and agency != "All":
        df = df[df["agency"].astype(str) == agency]
    return {
        "filters": {"fleet": fleet, "agency": agency, "period": period},
        "rows": _jsonsafe_records(df) if not df.empty else [],
    }


# ---------------------------------------------------------------------------
# /dashboard/suspense
# ---------------------------------------------------------------------------

def suspense(*, fleet: str = "All", agency: str = "All") -> dict:
    df = _read_suspense()
    if df.empty:
        return {"filters": {"fleet": fleet, "agency": agency}, "rows": [], "buckets": {}}
    bucket_counts = (
        {str(k): int(v) for k, v in df["aging_bucket"].fillna("").value_counts().items()}
        if "aging_bucket" in df.columns else {}
    )
    return {
        "filters": {"fleet": fleet, "agency": agency},
        "buckets": bucket_counts,
        "rows": _jsonsafe_records(df.head(200)),
        "total_pending": int(len(df)),
    }


# ---------------------------------------------------------------------------
# /dashboard/riders
# ---------------------------------------------------------------------------

def riders(*, fleet: str = "All", agency: str = "All", q: str = "") -> dict:
    df = _read_outstanding()
    if df.empty:
        return {"filters": {"fleet": fleet, "agency": agency, "q": q}, "rows": []}
    if fleet and fleet != "All":
        df = df[df["fleet"].astype(str) == fleet]
    if agency and agency != "All":
        df = df[df["agency"].astype(str) == agency]
    if q:
        ql = q.lower()
        df = df[df["rider_name"].astype(str).str.lower().str.contains(ql)
                | df["rider_id"].astype(str).str.lower().str.contains(ql)]
    return {
        "filters": {"fleet": fleet, "agency": agency, "q": q},
        "count": int(len(df)),
        "rows": df.head(200).to_dict("records"),
    }
