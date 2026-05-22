"""Prompt 4 acceptance tests for Step 1 (load, filter, normalise).

Acceptance criteria from the spec:
  1. Unit tests for phone normaliser (cover +233244..., 0244..., 00233244...,
     233244...).
  2. TSA rider always lands in TSAC regardless of area.
  3. Wahu rider with area not in map lands in Unassigned and emits a flag row.
  4. `--fleet TSA --agency TSAC` filters invoices but NOT MoMo/bank receipts.
"""

from __future__ import annotations

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from collections_v3.io_.bike_fleet import TSAFleet, normalize_name
from collections_v3.io_.zones import EAST_AGENCY, WEST_AGENCY, ZonesData
from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.steps import step1_load
from collections_v3.util.agency import (
    FLAG_ADDRESS_NOT_IN_ZONES, FLAG_NO_ADDRESS, assign,
)
from collections_v3.util.agency_history import append_changes
from collections_v3.util.outstanding import opening_outstanding
from collections_v3.util.phone import normalize_phone
from collections_v3.util.scope import apply_scope


# ---------------------------------------------------------------------------
# Acceptance #1: phone normaliser — the four spec-cited forms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("+233244123456", "244123456"),
    ("0244123456", "244123456"),
    ("00233244123456", "244123456"),
    ("233244123456", "244123456"),
])
def test_normalize_phone_spec_cases(raw, expected):
    assert normalize_phone(raw) == expected


# ---------------------------------------------------------------------------
# Acceptance #2: TSA rider always lands in TSAC, regardless of area
# ---------------------------------------------------------------------------

def _tsa_with(name: str) -> TSAFleet:
    return TSAFleet(
        sheet_name="TSA",
        rider_count=1,
        riders={normalize_name(name)},
        raw_assigned=[name],
    )


def _zones_with(name: str, address: str, area: str, agency: str) -> ZonesData:
    z = ZonesData()
    z.addresses = {normalize_name(name): address}
    z.neighborhood_to_agency = [(area.lower(), agency)]
    return z


def test_tsa_always_lands_in_tsac_even_with_west_address():
    """A TSA rider whose address would otherwise route to Hortta still gets TSAC."""
    tsa = _tsa_with("Eric Aheto")
    # Even with a Dansoman (West Zone -> Hortta) address, TSA fleet wins.
    zones = _zones_with("Eric Aheto", "Dansoman,Ghana", "dansoman", WEST_AGENCY)
    out = assign("Eric Aheto", tsa, zones)
    assert out.fleet == "TSA"
    assert out.agency == "TSAC"
    assert out.flags == []


def test_tsa_lands_in_tsac_with_no_address():
    tsa = _tsa_with("Eric Aheto")
    out = assign("Eric Aheto", tsa, ZonesData())
    assert (out.fleet, out.agency) == ("TSA", "TSAC")


# ---------------------------------------------------------------------------
# Acceptance #3: Wahu rider with no matching area -> Unassigned + flag
# ---------------------------------------------------------------------------

def test_wahu_with_address_not_in_zones_flags_unassigned():
    # Address present, but no zone matches it.
    tsa = TSAFleet(sheet_name="TSA", rider_count=0, riders=set(), raw_assigned=[])
    zones = ZonesData()
    zones.addresses = {normalize_name("John Doe"): "Some Outer Suburb"}
    zones.neighborhood_to_agency = [("osu", EAST_AGENCY), ("dansoman", WEST_AGENCY)]
    out = assign("John Doe", tsa, zones)
    assert out.fleet == "Wahu"
    assert out.agency == "Unassigned"
    assert FLAG_ADDRESS_NOT_IN_ZONES in out.flags


def test_wahu_with_no_address_flags_unassigned():
    tsa = TSAFleet(sheet_name="TSA", rider_count=0, riders=set(), raw_assigned=[])
    out = assign("John Doe", tsa, ZonesData())
    assert (out.fleet, out.agency) == ("Wahu", "Unassigned")
    assert FLAG_NO_ADDRESS in out.flags


# ---------------------------------------------------------------------------
# Acceptance #4: --fleet TSA --agency TSAC filters invoices, NOT receipts
# ---------------------------------------------------------------------------

def _tagged_invoices() -> pd.DataFrame:
    rows = [
        # TSA / TSAC
        dict(invoice_id="A1", invoice_number="INV-A1", rider_id="CUS-1",
             rider_name="Tsa Rider", amount=400.0, amount_due=400.0,
             fleet="TSA", agency="TSAC", status="open"),
        # Wahu / TSAC (East Zone)
        dict(invoice_id="A2", invoice_number="INV-A2", rider_id="CUS-2",
             rider_name="East Wahu", amount=300.0, amount_due=300.0,
             fleet="Wahu", agency="TSAC", status="open"),
        # Wahu / Hortta (West Zone)
        dict(invoice_id="A3", invoice_number="INV-A3", rider_id="CUS-3",
             rider_name="West Wahu", amount=300.0, amount_due=300.0,
             fleet="Wahu", agency="Hortta", status="open"),
    ]
    return pd.DataFrame(rows)


def test_scope_filter_tsa_tsac_keeps_only_tsa_invoices():
    df = _tagged_invoices()
    ctx = RunContext(fleet=Fleet.TSA, agency=Agency.TSAC, period=Period.Lifetime)
    res = apply_scope(df, ctx)
    assert len(res.invoices) == 1
    assert set(res.invoices["fleet"]) == {"TSA"}
    assert res.riders_in_scope == {"CUS-1"}


def test_scope_filter_wahu_hortta_keeps_only_wahu_hortta():
    df = _tagged_invoices()
    ctx = RunContext(fleet=Fleet.Wahu, agency=Agency.Hortta, period=Period.Lifetime)
    res = apply_scope(df, ctx)
    assert len(res.invoices) == 1
    assert res.invoices.iloc[0]["rider_name"] == "West Wahu"


def test_scope_filter_all_keeps_everything():
    df = _tagged_invoices()
    ctx = RunContext(fleet=Fleet.All, agency=Agency.All, period=Period.Lifetime)
    res = apply_scope(df, ctx)
    assert len(res.invoices) == 3
    assert res.riders_in_scope == {"CUS-1", "CUS-2", "CUS-3"}


def test_receipts_not_filtered_by_scope(monkeypatch):
    """The whole point of acceptance #4: even with --fleet TSA --agency TSAC,
    the receipts DataFrame in Step1Result has all rows (not just TSA riders').
    """
    tagged = _tagged_invoices()
    # Patch every loader so the test doesn't hit Drive.
    monkeypatch.setattr(step1_load, "load_billed_invoices", lambda **kw: tagged.copy())
    monkeypatch.setattr(step1_load, "load_tsa_roster", lambda **kw: TSAFleet(
        sheet_name="TSA", rider_count=0, riders=set(), raw_assigned=[],
    ))
    monkeypatch.setattr(step1_load, "load_zones", lambda **kw: ZonesData())
    monkeypatch.setattr(step1_load, "load_zoho_payments", lambda **kw: pd.DataFrame())
    monkeypatch.setattr(step1_load, "load_bolt_earnings", lambda **kw: pd.DataFrame())
    monkeypatch.setattr(step1_load, "_tag_invoices", lambda inv, t, z: (inv, []))
    monkeypatch.setattr(step1_load, "get_drive_client", lambda: object())

    receipts_df = pd.DataFrame([
        # A receipt from a TSA rider (in-scope)
        dict(txn_id="T1", channel="mtn", date=date(2026, 5, 14), amount=400.0,
             sender_name="Tsa Rider", sender_phone_canonical="244111111",
             sender_phone_raw="", reference="T1", narration="", source_file="m.csv"),
        # A receipt from a Wahu rider (out of scope under --fleet TSA)
        dict(txn_id="T2", channel="bank", date=date(2026, 5, 14), amount=300.0,
             sender_name="West Wahu", sender_phone_canonical="",
             sender_phone_raw="", reference="T2", narration="", source_file="b.csv"),
    ])
    from collections_v3.io_.receipts import ReceiptsResult
    monkeypatch.setattr(
        step1_load, "load_receipts",
        lambda **kw: ReceiptsResult(receipts=receipts_df, sources=["m.csv", "b.csv"], duplicates_removed=0),
    )

    # Use a temp file for the singleton so the test doesn't write into the repo.
    with tempfile.TemporaryDirectory() as td:
        from collections_v3.util import agency_history as ah
        monkeypatch.setattr(ah, "LOCAL_PATH", Path(td) / "history.xlsx")

        ctx = RunContext(fleet=Fleet.TSA, agency=Agency.TSAC, period=Period.Lifetime)
        result = step1_load.run(ctx, client=object())

    # Invoices got scoped (only TSA -> 1 row)
    assert len(result.invoices_in_scope) == 1
    assert set(result.invoices_in_scope["fleet"]) == {"TSA"}
    # Receipts stayed whole — BOTH txns present.
    assert len(result.receipts) == 2
    assert set(result.receipts["txn_id"]) == {"T1", "T2"}


# ---------------------------------------------------------------------------
# Opening outstanding + history helpers
# ---------------------------------------------------------------------------

def test_opening_outstanding_sums_per_rider():
    df = pd.DataFrame([
        dict(rider_id="R1", rider_name="A", fleet="Wahu", agency="TSAC",
             amount_due=400.0),
        dict(rider_id="R1", rider_name="A", fleet="Wahu", agency="TSAC",
             amount_due=200.0),
        dict(rider_id="R1", rider_name="A", fleet="Wahu", agency="TSAC",
             amount_due=0.0),
        dict(rider_id="R2", rider_name="B", fleet="TSA", agency="TSAC",
             amount_due=300.0),
    ])
    out = opening_outstanding(df)
    by_rider = dict(zip(out["rider_id"], out["opening_outstanding"]))
    by_open = dict(zip(out["rider_id"], out["open_invoice_count"]))
    assert by_rider["R1"] == 600.0
    assert by_rider["R2"] == 300.0
    # The amount_due == 0 row is "settled" — count of open invoices excludes it.
    assert by_open["R1"] == 2
    assert by_open["R2"] == 1


def test_agency_history_appends_only_on_change(tmp_path):
    p = tmp_path / "hist.xlsx"
    # First run.
    df1 = append_changes({"CUS-1": "TSAC", "CUS-2": "Hortta"},
                         today=date(2026, 5, 1), path=p)
    assert len(df1) == 2
    # Second run — same agencies, no new rows.
    df2 = append_changes({"CUS-1": "TSAC", "CUS-2": "Hortta"},
                         today=date(2026, 5, 8), path=p)
    assert len(df2) == 2
    # Third run — CUS-2 switches Hortta -> TSAC: prior row closes, new row opens.
    df3 = append_changes({"CUS-1": "TSAC", "CUS-2": "TSAC"},
                         today=date(2026, 5, 15), path=p)
    assert len(df3) == 3
    closed = df3[(df3["rider_id"] == "CUS-2") & (df3["end"] != "")]
    open_after = df3[(df3["rider_id"] == "CUS-2") & (df3["end"] == "")]
    assert len(closed) == 1 and closed.iloc[0]["agency"] == "Hortta"
    assert closed.iloc[0]["end"] == "2026-05-15"
    assert len(open_after) == 1 and open_after.iloc[0]["agency"] == "TSAC"
    assert open_after.iloc[0]["start"] == "2026-05-15"
