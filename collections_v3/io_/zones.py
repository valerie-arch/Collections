"""Load the Collection Assignment Zones Google Sheet.

Returns two things:
  1. A customer roster (Customer Name -> Address), used to look up addresses
     for Wahu fleet invoices.
  2. A zone table (Neighborhood -> Agency), used to assign Wahu fleet
     riders to Hortta (West Zone) or TSAC (East Zone). All TSA fleet riders
     go to TSAC regardless of address.

The sheet may have the roster and the zone tables on separate tabs OR
embedded as separate sections of one tab. This loader handles both: it
scans every tab and pulls roster rows and zone rows wherever they appear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from api.config import settings
from api.integrations.google_drive import DriveClient
from collections_v3.io_.bike_fleet import normalize_name
from collections_v3.io_.sheet_loader import (
    download_google_sheet_as_xlsx,
    list_tab_names,
    read_tab_no_header,
)


WEST_AGENCY = "Hortta"
EAST_AGENCY = "TSAC"


@dataclass
class ZonesData:
    addresses: dict[str, str] = field(default_factory=dict)  # normalized_name -> address
    raw_addresses: dict[str, str] = field(default_factory=dict)  # name -> address (original case)
    neighborhood_to_agency: list[tuple[str, str]] = field(default_factory=list)  # ordered (neighborhood_lc, agency)
    source_tabs: dict[str, list[str]] = field(default_factory=dict)  # what we found per tab


def _scan_for_roster_section(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Find rows that look like (Customer Name, Address). Returns (name,
    address) pairs.

    Heuristic: pick rows where one column matches 'customer name' as the
    header (case-insensitive) and another matches 'customer address'. Then
    take subsequent rows as data until we hit a blank row.
    """
    out: list[tuple[str, str]] = []
    df = df.fillna("").astype(str)
    n_rows, n_cols = df.shape
    if n_rows == 0 or n_cols == 0:
        return out

    for header_row in range(n_rows):
        row = [df.iat[header_row, c].strip().lower() for c in range(n_cols)]
        name_col = next(
            (c for c, v in enumerate(row) if v == "customer name"), None
        )
        addr_col = next(
            (c for c, v in enumerate(row) if v == "customer address"), None
        )
        if name_col is None or addr_col is None:
            continue
        # Walk down until we hit a fully-blank row.
        for r in range(header_row + 1, n_rows):
            data = [df.iat[r, c].strip() for c in range(n_cols)]
            if not any(data):
                break
            name = data[name_col].strip()
            addr = data[addr_col].strip()
            if name and name.lower() != "customer name":
                out.append((name, addr))
    return out


def _scan_for_zone_sections(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Find West Zone / East Zone sections and return ordered
    (neighborhood, agency) tuples.

    Each zone section starts with a row whose text contains 'West Zone' or
    'East Zone'. Subsequent rows are numbered, with the neighborhood name in
    an adjacent column. The sheet sometimes splits a zone across two pairs
    of columns (`# | Neighborhood | # | Neighborhood`) — handle both.
    """
    out: list[tuple[str, str]] = []
    df = df.fillna("").astype(str)
    n_rows, n_cols = df.shape
    if n_rows == 0 or n_cols == 0:
        return out

    current_agency: Optional[str] = None
    for r in range(n_rows):
        row = [df.iat[r, c].strip() for c in range(n_cols)]
        joined_lc = " ".join(row).lower()

        if "west zone" in joined_lc:
            current_agency = WEST_AGENCY
            continue
        if "east zone" in joined_lc:
            current_agency = EAST_AGENCY
            continue
        if current_agency is None:
            continue

        # Within a zone section, look at every cell that's a non-numeric,
        # non-header neighborhood name. Skip pure-number cells (the index
        # column) and skip header words like '#' or 'Neighborhood'.
        for c in range(n_cols):
            v = row[c].strip()
            if not v:
                continue
            vl = v.lower()
            if vl in ("#", "neighborhood"):
                continue
            if v.isdigit():
                continue
            if "zone" in vl and "assigned" in vl:
                continue  # header line variants
            out.append((vl, current_agency))
    return out


def load_zones(*, client: Optional[DriveClient] = None) -> ZonesData:
    xlsx = download_google_sheet_as_xlsx(
        settings.ASSIGNMENT_ZONES_SHEET_ID, client=client,
    )
    tabs = list_tab_names(xlsx)

    data = ZonesData()
    for tab in tabs:
        df = read_tab_no_header(xlsx, tab)
        found_here: list[str] = []
        pairs = _scan_for_roster_section(df)
        for name, addr in pairs:
            key = normalize_name(name)
            if not key:
                continue
            # Keep first occurrence — duplicates would shadow earlier rows.
            if key not in data.addresses:
                data.addresses[key] = addr
                data.raw_addresses[name] = addr
        if pairs:
            found_here.append(f"roster ({len(pairs)} rows)")

        zones = _scan_for_zone_sections(df)
        if zones:
            data.neighborhood_to_agency.extend(zones)
            found_here.append(f"zones ({len(zones)} rows)")

        if found_here:
            data.source_tabs[tab] = found_here

    # Sort the neighborhood list by descending length so more-specific
    # phrases (e.g. 'Achimota (east side)') match before short prefixes
    # (e.g. 'Achimota').
    data.neighborhood_to_agency.sort(key=lambda kv: len(kv[0]), reverse=True)
    return data


def lookup_agency_for_address(
    address: str, neighborhood_to_agency: list[tuple[str, str]]
) -> Optional[str]:
    """Return the first matching agency for `address`, or None.

    Matching is case-insensitive substring. The caller is expected to have
    pre-sorted longest-neighborhood-first to handle east/west-side overlaps.
    """
    if not address:
        return None
    a_lc = address.lower()
    for n_lc, agency in neighborhood_to_agency:
        if n_lc in a_lc:
            return agency
    return None
