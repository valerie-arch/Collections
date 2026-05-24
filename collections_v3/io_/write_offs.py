"""Write-off ledger loader.

A Finance-maintained Google Sheet (or local XLSX during dev) with two tabs:

    WriteOffs   — one row per written-off balance
    Recoveries  — zero+ rows per write_off_id, each a partial recovery event

Drives KPI 9 (Net Charge-Off Rate) and KPI 10 (Recovery Rate on Churned
Riders) on the portfolio dashboard. Also feeds the net-of-write-offs split
on KPI 2 (Monthly Collections Rate).

Source resolution order:
  1. WRITE_OFFS_SHEET_ID env / settings — Drive file id (Google Sheet or
     uploaded XLSX). Read via DriveClient.
  2. local fallback at collections_v3/io_/templates/write_off_ledger_template.xlsx
     for tests and dev runs without Drive credentials.

Returns two DataFrames with stable canonical columns. Rows that fail
validation (missing required field, malformed date/amount) are dropped
with a warning rather than raising — Finance will see the loss reflected
in the dashboard "data quality" panel and can fix the sheet inline.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient, get_drive_client
from collections_v3.io_.sheet_loader import download_google_sheet_as_xlsx

logger = logging.getLogger(__name__)


WRITE_OFFS_COLUMNS = [
    "write_off_id", "rider_id", "rider_name", "write_off_date",
    "amount_ghs", "reason", "approved_by", "notes",
]
RECOVERIES_COLUMNS = [
    "recovery_id", "write_off_id", "recovery_date",
    "amount_ghs", "source", "source_txn_id", "notes",
]

VALID_REASONS = {
    "vehicle_returned", "long_term_default", "deceased",
    "bankruptcy", "other",
}
VALID_SOURCES = {
    "mtn", "telecel", "bank", "bolt_deduction", "cash", "other",
}

_LOCAL_FALLBACK = (
    Path(__file__).resolve().parent / "templates"
    / "write_off_ledger_template.xlsx"
)


@dataclass
class WriteOffLedger:
    write_offs: pd.DataFrame
    recoveries: pd.DataFrame
    source: str                  # "drive:<file_id>" or "local:<path>"
    dropped_write_off_rows: int
    dropped_recovery_rows: int


def _s(v: object) -> str:
    """Safe string coercion that treats NaN/None as ""."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def _to_money(v: object) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip().replace(",", "").replace("GHS", "")
    if not s:
        return None
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def _to_date(v: object) -> Optional[date]:
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return pd.to_datetime(v).date()
    except (ValueError, TypeError):
        return None


def _resolve_bytes(*, client: Optional[DriveClient]) -> tuple[bytes, str]:
    """Return (xlsx_bytes, source_label). Prefer Drive; fall back to local."""
    file_id = getattr(settings, "WRITE_OFFS_SHEET_ID", "") or ""
    if file_id:
        client = client or get_drive_client()
        data = download_google_sheet_as_xlsx(file_id, client=client)
        return data, f"drive:{file_id}"
    if _LOCAL_FALLBACK.exists():
        return _LOCAL_FALLBACK.read_bytes(), f"local:{_LOCAL_FALLBACK}"
    raise FileNotFoundError(
        "No WRITE_OFFS_SHEET_ID configured and local fallback missing at "
        f"{_LOCAL_FALLBACK}"
    )


def _read_tab(xlsx_bytes: bytes, tab: str) -> pd.DataFrame:
    return pd.read_excel(
        io.BytesIO(xlsx_bytes),
        sheet_name=tab,
        engine="openpyxl",
        dtype=object,
        keep_default_na=False,
        na_values=[""],
    )


def _validate_write_offs(raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if raw.empty:
        return pd.DataFrame(columns=WRITE_OFFS_COLUMNS), 0
    rows: list[dict] = []
    dropped = 0
    for r in raw.to_dict("records"):
        wo_id = _s(r.get("write_off_id"))
        rid = _s(r.get("rider_id"))
        d = _to_date(r.get("write_off_date"))
        amt = _to_money(r.get("amount_ghs"))
        reason = _s(r.get("reason")).lower()
        if not wo_id or not rid or d is None or amt is None or amt <= 0:
            dropped += 1
            continue
        if reason and reason not in VALID_REASONS:
            logger.warning("write_off %s has unknown reason %r — keeping as 'other'",
                           wo_id, reason)
            reason = "other"
        rows.append({
            "write_off_id": wo_id,
            "rider_id": rid,
            "rider_name": _s(r.get("rider_name")),
            "write_off_date": d,
            "amount_ghs": float(amt),
            "reason": reason or "other",
            "approved_by": _s(r.get("approved_by")),
            "notes": _s(r.get("notes")),
        })
    return pd.DataFrame(rows, columns=WRITE_OFFS_COLUMNS), dropped


def _validate_recoveries(
    raw: pd.DataFrame, known_write_off_ids: set[str],
) -> tuple[pd.DataFrame, int]:
    if raw.empty:
        return pd.DataFrame(columns=RECOVERIES_COLUMNS), 0
    rows: list[dict] = []
    dropped = 0
    for r in raw.to_dict("records"):
        rc_id = _s(r.get("recovery_id"))
        wo_id = _s(r.get("write_off_id"))
        d = _to_date(r.get("recovery_date"))
        amt = _to_money(r.get("amount_ghs"))
        if not rc_id or not wo_id or d is None or amt is None or amt <= 0:
            dropped += 1
            continue
        if wo_id not in known_write_off_ids:
            logger.warning("recovery %s references unknown write_off_id %s — dropping",
                           rc_id, wo_id)
            dropped += 1
            continue
        src = _s(r.get("source")).lower()
        if src and src not in VALID_SOURCES:
            logger.warning("recovery %s has unknown source %r — keeping as 'other'",
                           rc_id, src)
            src = "other"
        rows.append({
            "recovery_id": rc_id,
            "write_off_id": wo_id,
            "recovery_date": d,
            "amount_ghs": float(amt),
            "source": src or "other",
            "source_txn_id": _s(r.get("source_txn_id")),
            "notes": _s(r.get("notes")),
        })
    return pd.DataFrame(rows, columns=RECOVERIES_COLUMNS), dropped


def load_write_off_ledger(
    *, client: Optional[DriveClient] = None,
) -> WriteOffLedger:
    """Load and validate the write-off ledger.

    Single entry point used by Step 4, the dashboard API, and tests. The
    returned DataFrames are always schema-conformant — invalid rows are
    dropped (with counts retained on the result) so callers can report
    data-quality issues without crashing.
    """
    xlsx_bytes, src_label = _resolve_bytes(client=client)
    raw_wo = _read_tab(xlsx_bytes, "WriteOffs")
    raw_rc = _read_tab(xlsx_bytes, "Recoveries")
    wo_df, wo_dropped = _validate_write_offs(raw_wo)
    rc_df, rc_dropped = _validate_recoveries(
        raw_rc, set(wo_df["write_off_id"].tolist())
    )
    logger.info(
        "write-off ledger loaded from %s: %d write-offs, %d recoveries "
        "(dropped %d / %d invalid rows)",
        src_label, len(wo_df), len(rc_df), wo_dropped, rc_dropped,
    )
    return WriteOffLedger(
        write_offs=wo_df,
        recoveries=rc_df,
        source=src_label,
        dropped_write_off_rows=wo_dropped,
        dropped_recovery_rows=rc_dropped,
    )


def net_charge_off(
    ledger: WriteOffLedger,
    *,
    start: date,
    end: date,
) -> dict:
    """Sum write-offs and recoveries inside a window. Used by KPI 9.

    Returns dict with: charge_offs_ghs, recoveries_ghs, net_charge_off_ghs.
    Recoveries are dated by recovery_date, not write_off_date — they
    count against the window in which the cash actually came in.
    """
    wo = ledger.write_offs
    rc = ledger.recoveries
    wo_in_window = wo[
        (wo["write_off_date"] >= start) & (wo["write_off_date"] <= end)
    ] if not wo.empty else wo
    rc_in_window = rc[
        (rc["recovery_date"] >= start) & (rc["recovery_date"] <= end)
    ] if not rc.empty else rc
    co = float(wo_in_window["amount_ghs"].sum()) if not wo_in_window.empty else 0.0
    rec = float(rc_in_window["amount_ghs"].sum()) if not rc_in_window.empty else 0.0
    return {
        "charge_offs_ghs": round(co, 2),
        "recoveries_ghs": round(rec, 2),
        "net_charge_off_ghs": round(co - rec, 2),
    }
