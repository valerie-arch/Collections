"""Load billed Zoho invoices from the Invoices Drive folder.

Zoho exports one row per line item; we aggregate to one row per Invoice ID,
summing line totals. Voided / draft invoices are excluded entirely.

Output schema (canonical field names used through the pipeline):

    invoice_id, invoice_number, invoice_date, due_date,
    rider_id, rider_name, amount, amount_due, status, fleet

The conceptual "Fleet" comes from Zoho's `TSA` boolean column (true → TSA,
false → Wahu). Zoho has no literal Fleet column.

`rider_id` is Zoho's `Customer Number` (e.g. CUS-21) — the human-readable ID
that the Rider Register uses to join. `Customer ID` (the long numeric one) is
preserved as `customer_id_zoho` for cross-reference.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient
from collections_v3.config import EXCLUDED_STATUSES
from collections_v3.io_.drive_resolver import ResolvedFile, list_matching
from collections_v3.io_.file_readers import read_resolved


# Column aliases — Zoho's export headers have varied across exports.
ZOHO_ALIASES: dict[str, tuple[str, ...]] = {
    "invoice_id": ("Invoice ID", "invoice_id"),
    "invoice_number": ("Invoice Number", "Invoice#", "invoice_number"),
    "customer_id_zoho": ("Customer ID", "customer_id"),
    "rider_id": ("Customer Number", "customer_number"),
    "rider_name": ("Customer Name", "customer_name"),
    "invoice_date": ("Invoice Date", "invoice_date", "Date"),
    "due_date": ("Due Date", "due_date"),
    "status": ("Invoice Status", "Status", "status"),
    "line_total": ("Item Total", "Line Item Total"),
    "invoice_total": ("Total", "Invoice Total", "total"),
    "balance": ("Balance", "balance", "Outstanding"),
    "tsa_flag": ("TSA",),
}

REQUIRED_CANONICAL = (
    "invoice_id", "invoice_number", "rider_id", "rider_name",
    "invoice_date", "status", "line_total", "balance", "tsa_flag",
)


def _resolve_aliases(actual_cols: Iterable[str]) -> dict[str, str]:
    """Return canonical_name -> actual_column. Raises if a required field is
    not derivable from any known alias."""
    norm = {c.strip().lower(): c for c in actual_cols if c}
    mapping: dict[str, str] = {}
    missing: list[str] = []
    for canon, aliases in ZOHO_ALIASES.items():
        for a in aliases:
            if a.strip().lower() in norm:
                mapping[canon] = norm[a.strip().lower()]
                break
    for req in REQUIRED_CANONICAL:
        if req not in mapping:
            missing.append(req)
    if missing:
        raise ValueError(
            f"Zoho invoice file is missing canonical fields {missing}. "
            f"Looked up aliases {[ZOHO_ALIASES[m] for m in missing]}. "
            f"Actual columns: {list(actual_cols)}"
        )
    return mapping


def _to_money(s: object) -> Decimal:
    if s is None or s == "" or pd.isna(s):
        return Decimal("0")
    cleaned = str(s).replace(",", "").replace("GHS", "").strip()
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def _to_bool(s: object) -> bool:
    if s is None or pd.isna(s):
        return False
    return str(s).strip().lower() in ("true", "yes", "1", "tsa")


def _normalize_one_file(rf: ResolvedFile) -> pd.DataFrame:
    """Read one Zoho CSV/XLSX and aggregate to one row per invoice_id."""
    df = read_resolved(rf)
    if df.empty:
        return pd.DataFrame()
    mapping = _resolve_aliases(df.columns)

    # Pull canonical columns; some are line-level and need aggregation.
    work = pd.DataFrame()
    for canon, col in mapping.items():
        work[canon] = df[col]

    # Coerce types we care about.
    work["line_total_d"] = work["line_total"].map(_to_money)
    work["balance_d"] = work["balance"].map(_to_money)
    work["status_lc"] = work["status"].fillna("").map(lambda v: str(v).strip().lower())
    work["tsa_bool"] = work["tsa_flag"].map(_to_bool)

    # Aggregate to one row per invoice_id. Sum line totals; keep first balance
    # (Zoho writes the same balance on every line of an invoice).
    grouped = work.groupby("invoice_id", as_index=False).agg(
        invoice_number=("invoice_number", "first"),
        customer_id_zoho=("customer_id_zoho", "first"),
        rider_id=("rider_id", "first"),
        rider_name=("rider_name", "first"),
        invoice_date=("invoice_date", "first"),
        due_date=("due_date", "first"),
        status=("status_lc", "first"),
        amount=("line_total_d", "sum"),
        amount_due=("balance_d", "first"),
        tsa_bool=("tsa_bool", "max"),
    )

    # Derived fleet from TSA boolean (Zoho has no Fleet column).
    grouped["fleet_zoho"] = grouped["tsa_bool"].map(lambda b: "TSA" if b else "Wahu")
    grouped["source_file"] = rf.effective_name
    grouped = grouped.drop(columns=["tsa_bool"])
    return grouped


def load_billed_invoices(
    *, client: Optional[DriveClient] = None
) -> pd.DataFrame:
    """Pull every Zoho invoice file from the invoices Drive folder, aggregate
    and dedupe to one row per invoice_id, then exclude void/draft.

    Returns a DataFrame with the canonical fields documented at module top.
    """
    folder_id = settings.ZOHO_INVOICES_DRIVE_FOLDER_ID
    name_filter = settings.DRIVE_INVOICE_FILENAME_FILTER or "Invoice"

    files = list_matching(folder_id, name_filter, client=client)
    if not files:
        raise FileNotFoundError(
            f"No Zoho invoice files matching '{name_filter}' found in Drive "
            f"folder {folder_id}."
        )

    from collections_v3.io_.drive_resolver import GOOGLE_SHEET_MIME
    from api.integrations.google_drive import get_drive_client
    client = client or get_drive_client()

    frames: list[pd.DataFrame] = []
    for f in files:
        if not (
            f.mime_type in (GOOGLE_SHEET_MIME, "text/csv")
            or f.name.lower().endswith((".csv", ".xlsx", ".xls"))
        ):
            continue
        if f.mime_type == GOOGLE_SHEET_MIME:
            content = client.download_file(f.id, export_mime="text/csv")
            name = f.name if f.name.lower().endswith(".csv") else f.name + ".csv"
            rf = ResolvedFile(drive_file=f, content=content, effective_name=name, effective_mime="text/csv")
        else:
            content = client.download_file(f.id)
            rf = ResolvedFile(drive_file=f, content=content, effective_name=f.name, effective_mime=f.mime_type)
        frames.append(_normalize_one_file(rf))

    if not frames:
        return pd.DataFrame()

    all_invoices = pd.concat(frames, ignore_index=True)

    # Cross-file dedupe by invoice_id — keep the row from the file with the
    # latest invoice_date (or fall back to first).
    all_invoices["invoice_date_dt"] = pd.to_datetime(
        all_invoices["invoice_date"], errors="coerce"
    )
    all_invoices = (
        all_invoices.sort_values(["invoice_id", "invoice_date_dt"], na_position="first")
        .drop_duplicates(subset=["invoice_id"], keep="last")
        .drop(columns=["invoice_date_dt"])
    )

    # Exclude void / draft.
    billed = all_invoices[~all_invoices["status"].isin(EXCLUDED_STATUSES)].copy()
    billed.reset_index(drop=True, inplace=True)
    return billed
