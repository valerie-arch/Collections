"""Offline check for Prompt 1 logic.

Builds a synthetic invoices DataFrame + a TSAFleet + a ZonesData and runs
the assignment + tab-building logic without touching Google Drive. This
lets us validate the agency tagger before swapping in real credentials.
"""

from __future__ import annotations

import io
import pandas as pd
import pytest

from collections_v3.io_.bike_fleet import TSAFleet, normalize_name
from collections_v3.io_.zones import (
    EAST_AGENCY, WEST_AGENCY, ZonesData, _scan_for_roster_section,
    _scan_for_zone_sections, lookup_agency_for_address,
)
from collections_v3.steps.step0_invoices import (
    Step0Result, _assign, run, write_xlsx,
)


def _synthetic_invoices() -> pd.DataFrame:
    return pd.DataFrame([
        # TSA rider — should be tagged TSA + TSAC
        dict(invoice_id="A1", invoice_number="INV-A1", customer_id_zoho="ZID1",
             rider_id="CUS-1", rider_name="Eric Amewuga Aheto",
             invoice_date="2026-05-01", due_date="2026-05-07",
             status="overdue", amount=420.0, amount_due=420.0,
             fleet_zoho="Wahu",  # wrong on purpose — TSA roster overrides
             source_file="x.csv"),
        # Wahu rider whose Address is in the EAST zone -> TSAC
        dict(invoice_id="A2", invoice_number="INV-A2", customer_id_zoho="ZID2",
             rider_id="CUS-2", rider_name="Felix Adom",
             invoice_date="2026-05-02", due_date="2026-05-09",
             status="open", amount=300.0, amount_due=300.0,
             fleet_zoho="Wahu", source_file="x.csv"),
        # Wahu rider whose Address is in the WEST zone -> Hortta
        dict(invoice_id="A3", invoice_number="INV-A3", customer_id_zoho="ZID3",
             rider_id="CUS-3", rider_name="Frederick Barths",
             invoice_date="2026-05-03", due_date="2026-05-10",
             status="closed", amount=300.0, amount_due=0.0,
             fleet_zoho="Wahu", source_file="x.csv"),
        # Wahu rider with NO address record -> Unassigned + flag
        dict(invoice_id="A4", invoice_number="INV-A4", customer_id_zoho="ZID4",
             rider_id="CUS-4", rider_name="Unknown Person",
             invoice_date="2026-05-04", due_date="2026-05-11",
             status="overdue", amount=300.0, amount_due=300.0,
             fleet_zoho="Wahu", source_file="x.csv"),
    ])


def _synthetic_tsa() -> TSAFleet:
    raw = ["Eric Amewuga Aheto"]
    return TSAFleet(
        sheet_name="TSA (Tel Solutions Africa)",
        rider_count=len(raw),
        riders={normalize_name(n) for n in raw},
        raw_assigned=raw,
    )


def _synthetic_zones() -> ZonesData:
    z = ZonesData()
    z.addresses = {
        normalize_name("Felix Adom"): "Madina,Ghana",
        normalize_name("Frederick Barths"): "Odokor,Ghana",
        # 'Unknown Person' deliberately absent
    }
    z.raw_addresses = {n: a for n, a in z.addresses.items()}
    # Mimic the real sheet: East = TSAC, West = Hortta. Longest first.
    z.neighborhood_to_agency = sorted([
        ("madina", EAST_AGENCY),
        ("odorkor", WEST_AGENCY),
        ("odokor", WEST_AGENCY),  # spelling variant
    ], key=lambda kv: len(kv[0]), reverse=True)
    return z


def test_assignment_rules():
    tsa = _synthetic_tsa()
    z = _synthetic_zones()
    a_tsa = _assign("Eric Amewuga Aheto", tsa, z)
    a_east = _assign("Felix Adom", tsa, z)
    a_west = _assign("Frederick Barths", tsa, z)
    a_unknown = _assign("Unknown Person", tsa, z)
    assert (a_tsa.fleet, a_tsa.agency) == ("TSA", "TSAC")
    assert (a_east.fleet, a_east.agency) == ("Wahu", "TSAC")
    assert (a_west.fleet, a_west.agency) == ("Wahu", "Hortta")
    assert (a_unknown.fleet, a_unknown.agency) == ("Wahu", "Unassigned")
    assert "no_address" in a_unknown.flags


def test_zones_parser_handles_split_columns():
    """The real Zones sheet has a `# | Neighborhood | # | Neighborhood` layout.
    Make sure the scanner picks up neighborhoods from both halves."""
    df = pd.DataFrame([
        ["West Zone — assigned to Horta/Neighborhood", "", "", ""],
        ["#", "Neighborhood", "#", "Neighborhood"],
        ["1", "Dansoman", "13", "Santa Maria"],
        ["2", "Mamprobi", "14", "Awoshie"],
        ["", "", "", ""],
        ["East Zone — assigned to TSA", "", "", ""],
        ["#", "Neighborhood", "#", "Neighborhood"],
        ["1", "Osu", "18", "Spintex"],
    ])
    pairs = _scan_for_zone_sections(df)
    names = {n for n, _ in pairs}
    assert {"dansoman", "santa maria", "mamprobi", "awoshie"}.issubset(names)
    assert {"osu", "spintex"}.issubset(names)
    # West gets Hortta, East gets TSAC.
    by_n = dict(pairs)
    assert by_n["dansoman"] == WEST_AGENCY
    assert by_n["osu"] == EAST_AGENCY


def test_roster_parser_finds_name_address_pairs():
    df = pd.DataFrame([
        ["Customer Name", "Plan Name", "Status", "Customer Address", "Organization"],
        ["Felix Adom", "70 Weeks", "live", "Madina,Ghana", "Wahu"],
        ["Frederick Barths", "24 Months - NEW", "paused", "Odokor,Ghana", "Wahu"],
    ])
    pairs = _scan_for_roster_section(df)
    assert ("Felix Adom", "Madina,Ghana") in pairs
    assert ("Frederick Barths", "Odokor,Ghana") in pairs


def test_address_longest_neighborhood_wins():
    # If the address mentions both "Achimota" and a more-specific variant,
    # the longer entry should match first.
    nta = sorted([
        ("achimota", WEST_AGENCY),
        ("achimota (east side)", EAST_AGENCY),
    ], key=lambda kv: len(kv[0]), reverse=True)
    assert lookup_agency_for_address("Achimota (east side), Ghana", nta) == EAST_AGENCY
    assert lookup_agency_for_address("Achimota Cemetery", nta) == WEST_AGENCY


def test_end_to_end_offline(monkeypatch):
    """Patch the three loaders so `run()` produces a Step0Result from
    synthetic data, then check the four output tabs are well-formed."""
    monkeypatch.setattr(
        "collections_v3.steps.step0_invoices.load_billed_invoices",
        lambda **kw: _synthetic_invoices(),
    )
    monkeypatch.setattr(
        "collections_v3.steps.step0_invoices.load_tsa_roster",
        lambda **kw: _synthetic_tsa(),
    )
    monkeypatch.setattr(
        "collections_v3.steps.step0_invoices.load_zones",
        lambda **kw: _synthetic_zones(),
    )
    # Skip the real Drive client.
    monkeypatch.setattr(
        "collections_v3.steps.step0_invoices.get_drive_client",
        lambda: object(),
    )

    result = run(client=object())
    assert isinstance(result, Step0Result)
    assert result.total_billed == 4
    assert result.split_total == 4
    assert len(result.invoices_tsa) == 1
    assert len(result.invoices_wahu) == 3
    # Every TSA row has agency TSAC.
    assert (result.invoices_tsa["agency"] == "TSAC").all()
    # No Wahu row has blank agency.
    assert (result.invoices_wahu["agency"].str.strip() != "").all()
    # Summary covers exactly (TSA, TSAC), (Wahu, TSAC), (Wahu, Hortta), (Wahu, Unassigned)
    pairs = {tuple(r) for r in result.by_agency_summary[["fleet", "agency"]].values.tolist()}
    assert pairs == {("TSA", "TSAC"), ("Wahu", "TSAC"), ("Wahu", "Hortta"), ("Wahu", "Unassigned")}
    # Flags must cite the unknown-address rider.
    assert (result.flags["flag_type"] == "no_address").any()

    # XLSX writer round-trip.
    payload = write_xlsx(result)
    book = pd.read_excel(io.BytesIO(payload), sheet_name=None, engine="openpyxl")
    assert set(book.keys()) == {"invoices_Wahu", "invoices_TSA", "by_agency_summary", "flags"}
