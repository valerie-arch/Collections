"""qb_upload_log singleton — append-only log of confirmed QB uploads.

Each successful upload to QuickBooks adds exactly ONE row (spec acceptance):
  week | file_pair | row_counts | operator | qb_confirmation_id | uploaded_at

`file_pair` is a string like "qb_invoices_2026-W20 + qb_payments_2026-W20".
`row_counts` carries the row counts of the invoice + payment files at
upload time so the log is self-explanatory.

This file is never overwritten — append-only is the singleton contract
in the artifact registry.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


COLUMNS = [
    "week", "file_pair", "row_counts", "operator",
    "qb_confirmation_id", "uploaded_at",
]
LOCAL_PATH = Path("artifacts/qb_upload_log.xlsx")


def _load(path: Path = LOCAL_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_excel(path, dtype=str, engine="openpyxl")
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNS].fillna("").astype(str)


def append_upload(
    *,
    week: str,
    file_pair: str,
    row_counts: dict[str, int],
    operator: str,
    qb_confirmation_id: str,
    path: Path = LOCAL_PATH,
) -> pd.DataFrame:
    """Append exactly one row recording a confirmed upload. Returns the
    full log post-append."""
    df = _load(path)
    new_row = {
        "week": week,
        "file_pair": file_pair,
        "row_counts": "; ".join(f"{k}={v}" for k, v in sorted(row_counts.items())),
        "operator": operator,
        "qb_confirmation_id": qb_confirmation_id,
        "uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    df = pd.concat([df, pd.DataFrame([new_row], columns=COLUMNS)], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, engine="openpyxl")
    return df
