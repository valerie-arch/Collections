"""Zoho Payments Received loader.

Pulls every payments CSV from the Zoho payments Drive folder, normalises to
canonical columns, dedupes on `payment_id`.

The `reference_number` field is the MoMo wallet ID / bank reference — this
is the join key Step 2's "2A — already-booked check" uses to decide
whether a receipt has already been applied in Zoho.
"""

from __future__ import annotations

import io
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient, get_drive_client
from collections_v3.io_.drive_resolver import (
    GOOGLE_SHEET_MIME, ResolvedFile, list_matching,
)
from collections_v3.io_.file_readers import read_resolved

logger = logging.getLogger(__name__)


CANONICAL_COLUMNS = [
    "payment_id", "payment_number", "invoice_number", "date",
    "payment_mode", "amount", "unused_amount", "reference_number",
    "customer_id", "customer_name", "company_name",
    "outstanding_receivable_amount", "source_file",
]


def _to_money(s: object) -> float:
    if s is None or s == "" or pd.isna(s):
        return 0.0
    cleaned = str(s).replace(",", "").replace("GHS", "").strip()
    if not cleaned:
        return 0.0
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return 0.0


def _normalize_one(rf: ResolvedFile) -> pd.DataFrame:
    df = read_resolved(rf)
    if df.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    # Zoho uses lowercase, snake_case headers in this export — match
    # case-insensitively to absorb minor drift.
    norm = {c.strip().lower(): c for c in df.columns if c}
    needed = ["payment_id", "date", "amount", "customer_id", "customer_name"]
    missing = [n for n in needed if n not in norm]
    if missing:
        raise ValueError(
            f"Zoho payments file {rf.effective_name} missing required columns "
            f"{missing}. Found: {list(df.columns)}"
        )

    def col(name: str) -> pd.Series:
        return df[norm[name]] if name in norm else pd.Series([""] * len(df))

    out = pd.DataFrame({
        "payment_id": col("payment_id").astype(str).str.strip(),
        "payment_number": col("payment_number").astype(str).str.strip(),
        "invoice_number": col("invoice_number").astype(str).str.strip(),
        "date": pd.to_datetime(col("date"), errors="coerce").dt.date,
        "payment_mode": col("payment_mode").astype(str).str.strip(),
        "amount": col("amount").map(_to_money),
        "unused_amount": col("unused_amount").map(_to_money) if "unused_amount" in norm else 0.0,
        "reference_number": col("reference_number").astype(str).str.strip(),
        "customer_id": col("customer_id").astype(str).str.strip(),
        "customer_name": col("customer_name").astype(str).str.strip(),
        "company_name": col("company_name").astype(str).str.strip() if "company_name" in norm else "",
        "outstanding_receivable_amount": (
            col("outstanding_receivable_amount").map(_to_money)
            if "outstanding_receivable_amount" in norm else 0.0
        ),
        "source_file": rf.effective_name,
    })
    return out[out["payment_id"] != ""].reset_index(drop=True)


def load_zoho_payments(
    *, client: Optional[DriveClient] = None
) -> pd.DataFrame:
    """Pull every payments CSV from the Zoho payments folder, aggregate
    and dedupe on payment_id."""
    folder_id = settings.ZOHO_PAYMENTS_DRIVE_FOLDER_ID
    files = list_matching(folder_id, "", client=client)
    if not files:
        logger.warning("no Zoho payment files in folder %s", folder_id)
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    client = client or get_drive_client()
    frames: list[pd.DataFrame] = []
    for f in files:
        if not (
            f.mime_type in (GOOGLE_SHEET_MIME, "text/csv")
            or f.name.lower().endswith((".csv", ".xlsx", ".xls"))
        ):
            continue
        if f.mime_type == GOOGLE_SHEET_MIME:
            data = client.download_file(f.id, export_mime="text/csv")
            name = f.name if f.name.lower().endswith(".csv") else f.name + ".csv"
            rf = ResolvedFile(
                drive_file=f, content=data, effective_name=name, effective_mime="text/csv",
            )
        else:
            data = client.download_file(f.id)
            rf = ResolvedFile(
                drive_file=f, content=data, effective_name=f.name, effective_mime=f.mime_type or "",
            )
        try:
            frames.append(_normalize_one(rf))
        except Exception as e:
            logger.exception("failed to load %s: %s", f.name, e)

    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    all_payments = pd.concat(frames, ignore_index=True)
    all_payments = all_payments.drop_duplicates(subset=["payment_id"], keep="last").reset_index(drop=True)
    logger.info("loaded %d Zoho payments (%d files)", len(all_payments), len(frames))
    return all_payments
