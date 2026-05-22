"""Shared agency-assignment logic.

Used by step0 (per-invoice tagging for the snapshot) and step1 (per-rider
tagging for the scope set). Keeping it in one place means the "Wahu rider
with no area → Unassigned + flag" rule can't drift between steps.

Inputs:
  rider_name: str
  tsa_fleet: TSAFleet (set of normalised names currently on a TSA bike)
  zones:     ZonesData (name -> address; address -> agency)

Output:
  Assignment(fleet, agency, flags, matched_address)

Per-spec acceptance:
  - TSA rider always lands in TSAC, regardless of address.
  - Wahu rider with no matched zone lands in Unassigned + flag.
"""

from __future__ import annotations

from dataclasses import dataclass

from collections_v3.config import TSA_DEFAULT_AGENCY
from collections_v3.io_.bike_fleet import TSAFleet, normalize_name
from collections_v3.io_.zones import ZonesData, lookup_agency_for_address


FLAG_NO_ADDRESS = "no_address"
FLAG_ADDRESS_NOT_IN_ZONES = "address_not_in_zones"


@dataclass
class Assignment:
    fleet: str           # "Wahu" | "TSA"
    agency: str          # "TSAC" | "Hortta" | "Unassigned"
    flags: list[str]
    matched_address: str


def assign(rider_name: str, tsa_fleet: TSAFleet, zones: ZonesData) -> Assignment:
    flags: list[str] = []
    key = normalize_name(rider_name)

    fleet = "TSA" if (key and key in tsa_fleet.riders) else "Wahu"

    if fleet == "TSA":
        return Assignment(fleet=fleet, agency=TSA_DEFAULT_AGENCY, flags=flags, matched_address="")

    address = zones.addresses.get(key, "")
    if not address:
        flags.append(FLAG_NO_ADDRESS)
        return Assignment(fleet=fleet, agency="Unassigned", flags=flags, matched_address="")

    agency = lookup_agency_for_address(address, zones.neighborhood_to_agency)
    if not agency:
        flags.append(FLAG_ADDRESS_NOT_IN_ZONES)
        return Assignment(fleet=fleet, agency="Unassigned", flags=flags, matched_address=address)
    return Assignment(fleet=fleet, agency=agency, flags=flags, matched_address=address)
