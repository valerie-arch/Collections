"""Load the Collection Agency Master from the Collections Data Drive.

Strict header contract per the v3 spec: `Agency, Contact, Commission %, Active`.
Valid agencies are TSAC, Hortta, Unassigned — anything else is flagged
downstream but kept.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient
from collections_v3.io_.drive_resolver import resolve_latest
from collections_v3.io_.file_readers import read_resolved
from collections_v3.util.headers import require_headers


REQUIRED_COLUMNS = ["Agency", "Contact", "Commission %", "Active"]


def _to_bool(s: object) -> bool:
    if s is None or pd.isna(s):
        return False
    return str(s).strip().lower() in ("true", "yes", "1", "y", "active")


def load_agency_master(*, client: Optional[DriveClient] = None) -> pd.DataFrame:
    rf = resolve_latest(
        settings.COLLECTIONS_DRIVE_FOLDER_ID,
        settings.AGENCY_MASTER_NAME,
        client=client,
    )
    df = read_resolved(rf)
    mapping = require_headers(
        "Collection Agency Master",
        rf.effective_name,
        list(df.columns),
        REQUIRED_COLUMNS,
    )
    out = pd.DataFrame({
        "agency": df[mapping["Agency"]].astype(str).str.strip(),
        "contact": df[mapping["Contact"]].astype(str).str.strip(),
        "commission_pct": df[mapping["Commission %"]].astype(str).str.strip(),
        "active": df[mapping["Active"]].map(_to_bool),
    })
    out = out[out["agency"] != ""].reset_index(drop=True)
    return out
