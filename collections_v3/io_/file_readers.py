"""Read CSV / XLSX bytes into a pandas DataFrame."""

from __future__ import annotations

import io
from typing import Optional

import pandas as pd

from collections_v3.io_.drive_resolver import ResolvedFile


def read_resolved(rf: ResolvedFile, *, sheet_name: Optional[str] = None) -> pd.DataFrame:
    """Return a DataFrame with string-typed columns.

    Numeric coercion happens in each loader so we don't lose leading zeros on
    phone numbers or invoice IDs that look numeric.
    """
    name_lc = rf.effective_name.lower()
    buf = io.BytesIO(rf.content)
    if name_lc.endswith(".csv") or rf.effective_mime == "text/csv":
        return pd.read_csv(buf, dtype=str, keep_default_na=False, na_values=[""])
    if name_lc.endswith((".xlsx", ".xls")):
        return pd.read_excel(
            buf,
            sheet_name=sheet_name or 0,
            dtype=str,
            engine="openpyxl",
            keep_default_na=False,
            na_values=[""],
        )
    raise ValueError(
        f"Don't know how to read {rf.effective_name} (mime={rf.effective_mime})"
    )
