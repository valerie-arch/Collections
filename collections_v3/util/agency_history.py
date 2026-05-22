"""rider_agency_history singleton — append rows when a rider's agency
flips between runs.

Columns: rider_id | agency | start | end

Each "current" assignment is stored as a row with `end` blank. When the
agency changes, the previous current row gets its `end` populated and a
new current row is appended. Historical payments stay attributed to
whoever held the rider at the time.

Storage strategy is local-first:
  * Always read/write `artifacts/rider_agency_history.xlsx`.
  * Once the Shared-Drive issue from Prompt 1 is resolved, a Drive-backed
    layer can be added here without changing the public surface.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd


HISTORY_COLUMNS = ["rider_id", "agency", "start", "end"]
LOCAL_PATH = Path("artifacts/rider_agency_history.xlsx")


def _load_existing(path: Path = LOCAL_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    df = pd.read_excel(path, dtype=str, engine="openpyxl")
    for c in HISTORY_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    # Blank cells round-trip through XLSX as NaN; coerce back to "" so the
    # "open row" check (end == "") behaves consistently across runs.
    df = df[HISTORY_COLUMNS].fillna("").astype(str)
    return df


def _write(df: pd.DataFrame, path: Path = LOCAL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, engine="openpyxl")


def append_changes(
    current: dict[str, str],
    *,
    today: Optional[date] = None,
    path: Path = LOCAL_PATH,
) -> pd.DataFrame:
    """Reconcile `current` ({rider_id -> agency}) against the history file.

    For each rider in `current`:
      * If the rider has no open row in history: append a new (start=today,
        end=blank) row.
      * If the rider has an open row but the agency differs: close the old
        row (set end=today) and append a new open row.
      * If the rider has an open row with the same agency: leave it alone.

    Riders previously in history but absent from `current` are left untouched
    — we don't auto-close just because they're not in this run's scope.

    Returns the post-write DataFrame.
    """
    today = today or date.today()
    today_s = today.isoformat()
    df = _load_existing(path)

    # Find the open row per rider (end is blank).
    open_mask = df["end"].astype(str).str.strip() == ""
    open_rows = df[open_mask]
    open_by_rider: dict[str, int] = {}
    for idx, row in open_rows.iterrows():
        # If multiple "open" rows exist (shouldn't, but defensive), keep
        # the LAST one as canonical.
        open_by_rider[str(row["rider_id"]).strip()] = idx

    new_rows: list[dict] = []
    for rider_id, agency in current.items():
        rider_id = str(rider_id).strip()
        if not rider_id:
            continue
        idx = open_by_rider.get(rider_id)
        if idx is None:
            new_rows.append({
                "rider_id": rider_id, "agency": agency,
                "start": today_s, "end": "",
            })
            continue
        existing_agency = str(df.at[idx, "agency"]).strip()
        if existing_agency == agency:
            continue
        # Close the existing row and append the new one.
        df.at[idx, "end"] = today_s
        new_rows.append({
            "rider_id": rider_id, "agency": agency,
            "start": today_s, "end": "",
        })

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows, columns=HISTORY_COLUMNS)],
                       ignore_index=True)

    _write(df, path)
    return df


# ---------------------------------------------------------------------------
# Operator Rule 5 — agency at a point in time
# ---------------------------------------------------------------------------

def agency_at_date(
    rider_id: str, as_of: date, *, path: Path = LOCAL_PATH,
) -> Optional[str]:
    """Return the agency that held the rider on `as_of`, or None when
    there's no row covering that date. Used for historical-payment
    attribution (Rule 5: re-assignments are forward-only)."""
    df = _load_existing(path)
    if df.empty:
        return None
    rid = str(rider_id).strip()
    candidates = df[df["rider_id"].astype(str).str.strip() == rid]
    if candidates.empty:
        return None
    as_of_iso = as_of.isoformat()
    for r in candidates.itertuples(index=False):
        start = str(r.start).strip()
        end = str(r.end).strip()
        if start and start > as_of_iso:
            continue
        if end and end < as_of_iso:
            continue
        return str(r.agency)
    return None
