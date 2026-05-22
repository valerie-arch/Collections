"""Load the TSA bike roster from the Bike Fleet Google Sheet.

Returns the set of normalized rider names currently assigned to a TSA bike.
Every billed Zoho customer not in that set is treated as Wahu fleet, per
the user's rule: "All non-TSA bikes that have ever been billed are Wahu Fleet."

The Bike Fleet sheet has one tab per fleet (e.g. "Wahu Mobility Ltd" and
"TSA (Tel Solutions Africa)"). We only need the TSA tab — we discover it by
sheet-name substring match so the loader survives small renames.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from api.config import settings
from api.integrations.google_drive import DriveClient
from collections_v3.io_.sheet_loader import (
    download_google_sheet_as_xlsx,
    list_tab_names,
    read_tab,
)


REQUIRED_COLUMNS = {"bike name", "assigned rider"}


def normalize_name(name: str) -> str:
    """Lowercased, whitespace-collapsed name for cross-source joins."""
    if not name:
        return ""
    return " ".join(str(name).strip().lower().split())


@dataclass
class TSAFleet:
    sheet_name: str          # the tab we read
    rider_count: int         # rows we found with an Assigned Rider
    riders: set[str]         # normalized names assigned to TSA bikes
    raw_assigned: list[str]  # original-case names (for the flags report)


def _find_tsa_tab(tab_names: list[str]) -> str:
    candidates = [t for t in tab_names if "tsa" in t.lower()]
    if not candidates:
        raise FileNotFoundError(
            f"Bike Fleet sheet has no tab whose name contains 'TSA'. "
            f"Available tabs: {tab_names}"
        )
    # Prefer the longest match (so 'TSA (Tel Solutions Africa)' wins over
    # something accidentally named 'TSA Notes').
    return max(candidates, key=len)


def load_tsa_roster(*, client: Optional[DriveClient] = None) -> TSAFleet:
    xlsx = download_google_sheet_as_xlsx(
        settings.BIKE_FLEET_SHEET_ID, client=client,
    )
    tabs = list_tab_names(xlsx)
    tsa_tab = _find_tsa_tab(tabs)

    df = read_tab(xlsx, tsa_tab)
    norm_cols = {c.strip().lower(): c for c in df.columns if c is not None}
    missing = REQUIRED_COLUMNS - set(norm_cols)
    if missing:
        raise ValueError(
            f"TSA tab '{tsa_tab}' is missing required columns {sorted(missing)}. "
            f"Found: {list(df.columns)}"
        )

    bike_col = norm_cols["bike name"]
    rider_col = norm_cols["assigned rider"]

    # Only keep rows where the bike name actually marks this as TSA — defensive
    # in case the tab includes a header row or unrelated entries.
    is_tsa = df[bike_col].fillna("").astype(str).str.strip().str.upper().str.startswith("TSA-")
    df = df[is_tsa].copy()

    raw = df[rider_col].fillna("").astype(str).tolist()
    raw_clean = [r.strip() for r in raw if r and r.strip().lower() != "unassigned"]
    norm = {normalize_name(r) for r in raw_clean}

    return TSAFleet(
        sheet_name=tsa_tab,
        rider_count=len(raw_clean),
        riders=norm,
        raw_assigned=raw_clean,
    )
