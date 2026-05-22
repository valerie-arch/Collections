"""Per-rider credit balance carried across runs.

Each rider's credit balance is a positive number representing money the
rider has overpaid that hasn't been refunded (Operator Rule #3 — never
auto-refund). Step 4 reads the prior balance, offsets it against this
run's outstanding, and writes the new balance back for next time.

Storage is local-first (artifacts/rider_credits.xlsx) on the same model
as rider_agency_history. When the Shared-Drive write path expands to
singletons, we can swap in a Drive-backed implementation without
changing the public surface.

Schema:
  rider_id | rider_name | balance | last_updated
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd


CREDITS_COLUMNS = ["rider_id", "rider_name", "balance", "last_updated"]
LOCAL_PATH = Path("artifacts/rider_credits.xlsx")


def load_balances(path: Path = LOCAL_PATH) -> dict[str, float]:
    """Return {rider_id: balance_ghs}. Empty when the file doesn't exist."""
    if not path.exists():
        return {}
    df = pd.read_excel(path, dtype=str, engine="openpyxl")
    for c in CREDITS_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[CREDITS_COLUMNS].fillna("")
    out: dict[str, float] = {}
    for r in df.itertuples(index=False):
        rid = str(r.rider_id).strip()
        if not rid:
            continue
        try:
            out[rid] = float(r.balance)
        except (TypeError, ValueError):
            out[rid] = 0.0
    return out


def write_balances(
    balances: dict[str, float],
    *,
    rider_id_to_name: Optional[dict[str, str]] = None,
    today: Optional[date] = None,
    path: Path = LOCAL_PATH,
) -> pd.DataFrame:
    """Overwrite the credits file with the supplied balances.

    Zero balances are dropped — we only persist riders with a non-zero
    credit. `rider_id_to_name` is used to look up names for the audit
    column; missing entries leave the name blank.
    """
    today = today or date.today()
    rider_id_to_name = rider_id_to_name or {}
    rows = []
    for rid, bal in balances.items():
        if round(bal, 2) <= 0:
            continue
        rows.append({
            "rider_id": rid,
            "rider_name": rider_id_to_name.get(rid, ""),
            "balance": round(bal, 2),
            "last_updated": today.isoformat(),
        })
    df = pd.DataFrame(rows, columns=CREDITS_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, engine="openpyxl")
    return df
