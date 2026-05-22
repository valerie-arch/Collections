"""Bolt weekly earnings loader.

Folder layout:
    {BOLT_DRIVE_FOLDER_ID}/
        01/2026 - January 2026/
            Bolt Food Payout Workings - [DD/MM/YYYY]   (one Google Sheet per week)
        02/2026 - February 2026/
            ...

Each weekly sheet has one row per rider for that week, with these columns
(case-insensitive substring match):
    Customer Name | TSA ? | Amount Owing | Current Debt | Bolt Payout
    | 5% | Payout After Commission | Approved Deduction For Overdue Invoice
    | Net Payout To Rider | Momo Account | Status | Fee Incurred | Comments

Filename convention: the [DD/MM/YYYY] date is the MONDAY AFTER the Mon-Sun
work week. So `Bolt Food Payout Workings - [ 18/05/2026]` reports the week
ending Sun May 17, paid on Mon May 18.

`load_bolt_for_week(ctx)` resolves the correct sheet from ctx.end (the
Sunday end of the reporting week). `load_bolt_earnings(ctx=None)` is a
convenience wrapper used by Step 1 — falls back to the latest weekly sheet
when no ctx is given.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient, DriveFile, get_drive_client
from collections_v3.io_.drive_resolver import GOOGLE_SHEET_MIME
from collections_v3.io_.file_readers import read_resolved
from collections_v3.io_.drive_resolver import ResolvedFile
from collections_v3.schemas import RunContext

logger = logging.getLogger(__name__)


FOLDER_MIME = "application/vnd.google-apps.folder"
CANONICAL_COLUMNS = [
    "rider_name", "week_start", "week_end", "tsa_flag",
    "amount_owing", "current_debt", "bolt_payout", "commission_5pct",
    "payout_after_commission", "approved_deduction",
    "net_payout_to_rider", "momo_account", "status",
    "fee_incurred", "comments", "source_file",
]


# Match "Bolt Food Payout Workings - [ DD/MM/YYYY ]" with optional spaces.
_FILENAME_DATE_RE = re.compile(r"\[\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*\]")


def _to_money(s: object) -> float:
    if s is None or s == "" or pd.isna(s):
        return 0.0
    cleaned = str(s).replace(",", "").replace("GHS", "").strip()
    if not cleaned or cleaned in ("-", "—"):
        return 0.0
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return 0.0


def _parse_filename_date(name: str) -> Optional[date]:
    m = _FILENAME_DATE_RE.search(name)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _payout_monday_for(reporting_end: date) -> date:
    """For a Mon-Sun reporting week ending on Sunday `reporting_end`, the
    payout Monday (and the filename date) is `reporting_end + 1`."""
    return reporting_end + timedelta(days=1)


def _week_window_from_filename(filename_date: date) -> tuple[date, date]:
    """Inverse of `_payout_monday_for` — return (Monday, Sunday) of the
    work week reported by a sheet whose title is dated `filename_date`."""
    week_end = filename_date - timedelta(days=1)         # the Sunday reported
    week_start = week_end - timedelta(days=6)            # that week's Monday
    return week_start, week_end


def _list_subfolders(folder_id: str, client: DriveClient) -> list[DriveFile]:
    return [
        f for f in client.list_folder(folder_id) if f.mime_type == FOLDER_MIME
    ]


def _list_sheets(folder_id: str, client: DriveClient) -> list[DriveFile]:
    out: list[DriveFile] = []
    for f in client.list_folder(folder_id):
        if f.mime_type == GOOGLE_SHEET_MIME or f.name.lower().endswith((".xlsx", ".xls", ".csv")):
            out.append(f)
    return out


def _find_sheet_for_week(
    root_folder_id: str, ctx: RunContext, *, client: DriveClient,
) -> Optional[DriveFile]:
    """Locate the sheet whose filename-date matches `ctx.end + 1 day`."""
    if not ctx.end:
        return None
    target_filename_date = _payout_monday_for(ctx.end)
    target_month = target_filename_date.month
    target_year = target_filename_date.year

    subfolders = _list_subfolders(root_folder_id, client)
    # Subfolder names look like "05/2026 - May 2026" — pick by year+month.
    chosen_sub: Optional[DriveFile] = None
    for sf in subfolders:
        if (f"{target_month:02d}/{target_year}" in sf.name
                or f"{target_year}-{target_month:02d}" in sf.name):
            chosen_sub = sf
            break
    if chosen_sub is None:
        # Fallback: search all subfolders.
        for sf in subfolders:
            for sheet in _list_sheets(sf.id, client):
                d = _parse_filename_date(sheet.name)
                if d == target_filename_date:
                    return sheet
        return None

    for sheet in _list_sheets(chosen_sub.id, client):
        d = _parse_filename_date(sheet.name)
        if d == target_filename_date:
            return sheet
    return None


def _find_latest_sheet(
    root_folder_id: str, *, client: DriveClient,
) -> Optional[tuple[DriveFile, date]]:
    """Walk all monthly subfolders, return (sheet, filename_date) of the
    sheet with the latest filename date."""
    latest: Optional[tuple[DriveFile, date]] = None
    for sf in _list_subfolders(root_folder_id, client):
        for sheet in _list_sheets(sf.id, client):
            d = _parse_filename_date(sheet.name)
            if d is None:
                continue
            if latest is None or d > latest[1]:
                latest = (sheet, d)
    return latest


def _download_as_resolved(f: DriveFile, *, client: DriveClient) -> ResolvedFile:
    if f.mime_type == GOOGLE_SHEET_MIME:
        data = client.download_file(f.id, export_mime="text/csv")
        name = f.name if f.name.lower().endswith(".csv") else f.name + ".csv"
        return ResolvedFile(drive_file=f, content=data, effective_name=name, effective_mime="text/csv")
    data = client.download_file(f.id)
    return ResolvedFile(drive_file=f, content=data, effective_name=f.name, effective_mime=f.mime_type or "")


_NEEDED_BOLT_COLS = ("customer name", "bolt payout")


def _normalize_bolt_sheet(rf: ResolvedFile, filename_date: date) -> pd.DataFrame:
    """Parse one weekly sheet into the canonical per-rider DataFrame."""
    df = read_resolved(rf)
    if df.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    norm = {str(c).strip().lower(): c for c in df.columns if c is not None}
    missing = [c for c in _NEEDED_BOLT_COLS if c not in norm]
    if missing:
        logger.warning(
            "Bolt sheet %s missing required cols %s; columns=%s",
            rf.effective_name, missing, list(df.columns),
        )
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    def col(key: str, default="") -> pd.Series:
        return df[norm[key]] if key in norm else pd.Series([default] * len(df))

    def str_col(key: str) -> pd.Series:
        """Like `col`, but coerces NaN -> "" BEFORE str(), so blank cells
        don't become the literal string "nan"."""
        return col(key).fillna("").astype(str).str.strip()

    work_start, work_end = _week_window_from_filename(filename_date)

    out = pd.DataFrame({
        "rider_name": str_col("customer name"),
        "week_start": work_start,
        "week_end": work_end,
        "tsa_flag": str_col("tsa ?"),
        "amount_owing": col("amount owing").map(_to_money),
        "current_debt": col("current debt").map(_to_money),
        "bolt_payout": col("bolt payout").map(_to_money),
        "commission_5pct": col("5%").map(_to_money),
        "payout_after_commission": col("payout after commission").map(_to_money),
        "approved_deduction": col("approved deduction for overdue invoice").map(_to_money),
        "net_payout_to_rider": col("net payout to rider").map(_to_money),
        "momo_account": str_col("momo account"),
        "status": str_col("status"),
        "fee_incurred": str_col("fee incurred"),
        "comments": str_col("comments"),
        "source_file": rf.effective_name,
    })
    # Drop blank/header-leftover rows. pandas may have surfaced NaN for
    # truly-empty cells — coerce, then string-filter.
    out["rider_name"] = out["rider_name"].fillna("").astype(str).str.strip()
    out = out[out["rider_name"] != ""]
    out = out[~out["rider_name"].str.lower().isin({"customer name", "total", "totals", "grand total"})]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_bolt_for_week(
    ctx: RunContext, *, client: Optional[DriveClient] = None,
) -> pd.DataFrame:
    """Pull the Bolt weekly workings sheet that covers ctx's reporting week."""
    client = client or get_drive_client()
    sheet = _find_sheet_for_week(settings.BOLT_DRIVE_FOLDER_ID, ctx, client=client)
    if sheet is None:
        logger.warning(
            "no Bolt sheet found for reporting week ending %s (looking for %s)",
            ctx.end, _payout_monday_for(ctx.end) if ctx.end else "<no ctx.end>",
        )
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    filename_date = _parse_filename_date(sheet.name)
    rf = _download_as_resolved(sheet, client=client)
    return _normalize_bolt_sheet(rf, filename_date)


def load_bolt_earnings(
    *, ctx: Optional[RunContext] = None, client: Optional[DriveClient] = None,
) -> pd.DataFrame:
    """Step 1 entry point.

    With ctx: returns the per-rider rows for the week defined by ctx.end.
    Without ctx: returns the latest available weekly sheet (so Step 1 has
    something non-empty to thread through even on bare ad-hoc invocations).
    """
    client = client or get_drive_client()
    if ctx is not None and ctx.end is not None:
        return load_bolt_for_week(ctx, client=client)

    latest = _find_latest_sheet(settings.BOLT_DRIVE_FOLDER_ID, client=client)
    if latest is None:
        logger.warning("no Bolt sheets in %s", settings.BOLT_DRIVE_FOLDER_ID)
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    sheet, fname_date = latest
    rf = _download_as_resolved(sheet, client=client)
    return _normalize_bolt_sheet(rf, fname_date)
