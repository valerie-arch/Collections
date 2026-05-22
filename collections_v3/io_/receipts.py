"""Receipts loader — MTN MoMo / Telecel Cash / bank statements.

Wraps the existing flexible parser in `api/agents/payments/parser.py` so
we don't reimplement column-alias matching for every Ghanaian statement
format. The output is normalised to the canonical ReceiptRecord shape.

Receipts are NOT scoped by --fleet/--agency in Step 1 (the spec is
explicit). Their fleet is inherited from the matched rider in Step 2.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient, get_drive_client
from collections_v3.util.phone import normalize_phone

logger = logging.getLogger(__name__)


@dataclass
class ReceiptsResult:
    receipts: pd.DataFrame   # canonical columns (see ALL_COLUMNS below)
    sources: list[str]       # source filenames
    duplicates_removed: int  # rows dropped by dedupe


ALL_COLUMNS = [
    "txn_id", "channel", "date", "amount", "sender_name",
    "sender_phone_canonical", "sender_phone_raw", "reference",
    "narration", "source_file",
]


def _payment_rows_to_df(rows) -> pd.DataFrame:
    """Convert PaymentRow dataclasses (from api/agents/payments/parser.py)
    into a DataFrame with our canonical column names."""
    if not rows:
        return pd.DataFrame(columns=ALL_COLUMNS)
    records = []
    for r in rows:
        records.append({
            "txn_id": (r.reference or "").strip(),
            "channel": r.channel or "unknown",
            "date": r.date,
            "amount": float(r.amount_ghs) if r.amount_ghs is not None else 0.0,
            "sender_name": (r.raw_name or "").strip(),
            "sender_phone_canonical": normalize_phone(r.msisdn or ""),
            "sender_phone_raw": (r.msisdn or "").strip(),
            "reference": (r.reference or "").strip(),
            "narration": (r.raw_name or "").strip(),
            "source_file": r.source_file,
        })
    return pd.DataFrame(records, columns=ALL_COLUMNS)


def _dedupe(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Spec: dedupe MoMo on Transaction ID; dedupe bank on Transaction Ref.

    Both fields end up in `txn_id` after normalisation. We dedupe globally
    on (channel, txn_id) when txn_id is non-empty; rows with blank txn_id
    are kept as-is (we have no key to dedupe on).
    """
    if df.empty:
        return df, 0
    with_key = df[df["txn_id"].astype(str).str.strip() != ""]
    no_key = df[df["txn_id"].astype(str).str.strip() == ""]
    deduped = with_key.drop_duplicates(subset=["channel", "txn_id"], keep="first")
    removed = len(with_key) - len(deduped)
    return pd.concat([deduped, no_key], ignore_index=True), removed


def _list_receipt_files(
    folder_id: str, client: DriveClient
) -> list:
    accepted_mime = {
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
        "application/vnd.google-apps.spreadsheet",
    }
    files = client.list_folder(folder_id)
    return [
        f for f in files
        if f.mime_type in accepted_mime
        or f.name.lower().endswith((".csv", ".xlsx", ".xls"))
    ]


def load_from_drive(
    folder_id: Optional[str] = None, *, client: Optional[DriveClient] = None,
) -> ReceiptsResult:
    """Pull every receipt file from `folder_id` (defaults to
    PAYMENTS_DRIVE_FOLDER_ID), parse and normalise."""
    # Import lazily so the package still imports cleanly if api/ deps shift.
    from api.agents.drive_sync import sync_payments
    from api.agents.payments.parser import parse_folder

    folder_id = folder_id or settings.PAYMENTS_DRIVE_FOLDER_ID
    # Reuse the existing FastAPI drive sync — it caches to
    # sample_inputs/payments/ and skips unchanged files.
    sync_payments(folder_id=folder_id)

    local_folder = Path("sample_inputs/payments")
    rows = list(parse_folder(local_folder))
    df = _payment_rows_to_df(rows)
    deduped, removed = _dedupe(df)
    sources = sorted({r.source_file for r in rows})
    logger.info(
        "loaded %d receipts from %d files (%d dups removed)",
        len(deduped), len(sources), removed,
    )
    return ReceiptsResult(receipts=deduped, sources=sources, duplicates_removed=removed)


def load_from_paths(paths: Iterable[str | Path]) -> ReceiptsResult:
    """Offline / test variant — parse a list of local files."""
    from api.agents.payments.parser import parse_payment_file
    rows: list = []
    for p in paths:
        rows.extend(parse_payment_file(p))
    df = _payment_rows_to_df(rows)
    deduped, removed = _dedupe(df)
    return ReceiptsResult(
        receipts=deduped,
        sources=sorted({str(p) for p in paths}),
        duplicates_removed=removed,
    )
