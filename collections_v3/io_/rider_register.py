"""Load the Rider Register from the Collections Data Drive.

Strict header contract per the v3 spec: `Rider ID, Phones, Bike Reg, Fleet,
Area, Subscription Start`. Mismatch aborts the run.

`Rider ID` is expected to be Zoho's `Customer Number` value (e.g. CUS-21).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient
from collections_v3.io_.drive_resolver import resolve_latest
from collections_v3.io_.file_readers import read_resolved
from collections_v3.util.headers import require_headers


REQUIRED_COLUMNS = ["Rider ID", "Phones", "Bike Reg", "Fleet", "Area", "Subscription Start"]


def load_rider_register(*, client: Optional[DriveClient] = None) -> pd.DataFrame:
    rf = resolve_latest(
        settings.COLLECTIONS_DRIVE_FOLDER_ID,
        settings.RIDER_REGISTER_NAME,
        client=client,
    )
    df = read_resolved(rf)
    mapping = require_headers(
        "Rider Register", rf.effective_name, list(df.columns), REQUIRED_COLUMNS
    )

    out = pd.DataFrame({
        "rider_id": df[mapping["Rider ID"]].astype(str).str.strip(),
        "phones": df[mapping["Phones"]].astype(str).str.strip(),
        "bike_reg": df[mapping["Bike Reg"]].astype(str).str.strip(),
        "fleet_register": df[mapping["Fleet"]].astype(str).str.strip(),
        "area": df[mapping["Area"]].astype(str).str.strip(),
        "subscription_start": df[mapping["Subscription Start"]].astype(str).str.strip(),
    })
    # Drop completely-blank rows the user may have left at the end of the sheet.
    out = out[out["rider_id"] != ""].reset_index(drop=True)
    return out
