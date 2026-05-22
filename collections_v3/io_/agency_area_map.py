"""Load the Area -> Agency lookup from the Collections Data Drive.

Strict header contract per the v3 spec: `Area, Agency`.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient
from collections_v3.io_.drive_resolver import resolve_latest
from collections_v3.io_.file_readers import read_resolved
from collections_v3.util.headers import require_headers


REQUIRED_COLUMNS = ["Area", "Agency"]


def load_agency_area_map(*, client: Optional[DriveClient] = None) -> pd.DataFrame:
    rf = resolve_latest(
        settings.COLLECTIONS_DRIVE_FOLDER_ID,
        settings.AGENCY_AREA_MAP_NAME,
        client=client,
    )
    df = read_resolved(rf)
    mapping = require_headers(
        "Agency Area Map", rf.effective_name, list(df.columns), REQUIRED_COLUMNS
    )
    out = pd.DataFrame({
        "area": df[mapping["Area"]].astype(str).str.strip(),
        "agency": df[mapping["Agency"]].astype(str).str.strip(),
    })
    out = out[out["area"] != ""].reset_index(drop=True)
    return out
