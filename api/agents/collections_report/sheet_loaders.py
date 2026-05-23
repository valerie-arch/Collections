"""Resolve fleet + agency assignments from Google Sheets.

The web API used to read fleet info from a local CSV and agency info from a
manually-maintained JSON. On Railway those files don't exist, so every rider
defaulted to Wahu fleet with no agency. This module bridges the API to the
Bike Fleet and Assignment Zones Google Sheets that collections_v3 already
knows how to read, with a CSV/JSON fallback for local dev.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


OS_FLEET_CSV = Path("sample_inputs/wahu_os/rider_fleet.csv")


@lru_cache(maxsize=1)
def _fleet_from_sheet() -> dict[str, str]:
    """Return {normalized_name: 'TSA'} from the Bike Fleet sheet."""
    from collections_v3.io_.bike_fleet import load_tsa_roster
    roster = load_tsa_roster()
    return {name: "TSA" for name in roster.riders}


def resolve_fleet_map() -> dict[str, str]:
    """{normalized_name: 'Wahu'|'TSA'}. Sheet first, CSV fallback."""
    try:
        return _fleet_from_sheet()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Bike Fleet sheet unavailable ({exc}); falling back to CSV.")
        if not OS_FLEET_CSV.exists():
            return {}
        from api.agents.collections_report.parsers import load_os_fleet_map
        return load_os_fleet_map(OS_FLEET_CSV)


@lru_cache(maxsize=1)
def _zones_and_tsa():
    from collections_v3.io_.bike_fleet import load_tsa_roster, normalize_name
    from collections_v3.io_.zones import load_zones, lookup_agency_for_address
    return {
        "zones": load_zones(),
        "tsa": load_tsa_roster(),
        "normalize_name": normalize_name,
        "lookup": lookup_agency_for_address,
    }


def resolve_agency_map(invoices) -> dict[str, str]:
    """{customer_id: 'Hortta'|'TSAC'} derived from zones sheet + TSA override.

    Rules: TSA fleet → always TSAC. Wahu fleet → look up customer name in
    zones roster to get address, then match address against neighborhood list
    to assign Hortta (West Zone) or TSAC (East Zone). Riders without a
    matchable address are omitted; the manual agency_store JSON can still
    fill them in.
    """
    try:
        ctx = _zones_and_tsa()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Zones/TSA sheets unavailable ({exc}); skipping derived agencies.")
        return {}

    zones = ctx["zones"]
    tsa = ctx["tsa"]
    normalize_name = ctx["normalize_name"]
    lookup = ctx["lookup"]

    out: dict[str, str] = {}
    seen: set[str] = set()
    for inv in invoices:
        cid = inv.customer_id
        if not cid or cid in seen:
            continue
        seen.add(cid)

        name_norm = normalize_name(inv.customer_name)
        if name_norm in tsa.riders:
            out[cid] = "TSAC"
            continue

        address = zones.addresses.get(name_norm)
        if not address:
            continue
        agency = lookup(address, zones.neighborhood_to_agency)
        if agency:
            out[cid] = agency

    return out
