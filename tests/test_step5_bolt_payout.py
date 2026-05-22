"""Prompt 8 acceptance: weekly Bolt payout matrix + two-fleet output.

Spec acceptance:
  1. outstanding=500, earnings=600 → deduction=420, payout=180.
  2. outstanding=300, earnings=600 → deduction=300, payout=300.
  3. outstanding=500, earnings=200 → deduction=200, payout=0.
  4. outstanding=0,   earnings=600 → deduction=0,   payout=600.
  5. `--fleet All` still produces exactly two payout files (one Wahu, one TSA).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.steps import step5_bolt_payout
from collections_v3.util.bolt_matrix import compute_deduction


# ---------------------------------------------------------------------------
# Matrix (Acceptance #1 - #4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("outstanding,earnings,expected", [
    (500, 600, (420.0, 180.0)),   # cap binds, rider keeps 180
    (300, 600, (300.0, 300.0)),   # full clearance: outstanding < earnings
    (500, 200, (200.0, 0.0)),     # low earnings: deduct all 200
    (0,   600, (0.0,   600.0)),   # pass-through, no debt
])
def test_matrix_spec_cases(outstanding, earnings, expected):
    assert compute_deduction(outstanding, earnings) == expected


@pytest.mark.parametrize("outstanding,earnings,expected", [
    (1000, 420, (420.0, 0.0)),  # exactly cap
    (1000, 419, (419.0, 0.0)),  # one below cap
    (1000, 421, (420.0, 1.0)),  # one above cap, rider keeps 1
    (50,   500, (50.0,  450.0)),# clear all 50, rider keeps rest
    (0,    0,   (0.0,   0.0)),  # nothing happens
])
def test_matrix_edge_cases(outstanding, earnings, expected):
    assert compute_deduction(outstanding, earnings) == expected


# ---------------------------------------------------------------------------
# Two-file output (Acceptance #5)
# ---------------------------------------------------------------------------

def _outstanding_df() -> pd.DataFrame:
    return pd.DataFrame([
        # Wahu/TSAC rider with 500 outstanding
        dict(rider_id="R1", rider_name="Felix Adom", fleet="Wahu", agency="TSAC",
             closing_outstanding=500.0),
        # TSA rider with 300 outstanding
        dict(rider_id="R2", rider_name="Eric Aheto", fleet="TSA", agency="TSAC",
             closing_outstanding=300.0),
        # Wahu/Hortta rider with 0 outstanding (pass-through)
        dict(rider_id="R3", rider_name="Frederick Barths", fleet="Wahu", agency="Hortta",
             closing_outstanding=0.0),
    ])


def _bolt_df() -> pd.DataFrame:
    return pd.DataFrame([
        dict(rider_id="R1", rider_name="Felix Adom",
             week_start=date(2026, 5, 11), week_end=date(2026, 5, 17),
             bolt_payout=600.0, momo_account="244111111"),
        dict(rider_id="R2", rider_name="Eric Aheto",
             week_start=date(2026, 5, 11), week_end=date(2026, 5, 17),
             bolt_payout=600.0, momo_account="245326779"),
        dict(rider_id="R3", rider_name="Frederick Barths",
             week_start=date(2026, 5, 11), week_end=date(2026, 5, 17),
             bolt_payout=600.0, momo_account="244222222"),
    ])


def _invoices_df() -> pd.DataFrame:
    # Sufficient open invoices to absorb each deduction.
    return pd.DataFrame([
        dict(invoice_id="i1", invoice_number="INV-1", rider_id="R1",
             invoice_date=date(2026, 5, 1), amount_due=500.0),
        dict(invoice_id="i2", invoice_number="INV-2", rider_id="R2",
             invoice_date=date(2026, 5, 1), amount_due=300.0),
    ])


def test_compute_always_produces_two_fleet_blocks():
    """Acceptance #5: under any input we expose exactly Wahu and TSA fleets."""
    result = step5_bolt_payout.compute(
        bolt_earnings=_bolt_df(),
        outstanding_df=_outstanding_df(),
        invoices_all=_invoices_df(),
    )
    assert set(result.fleets) == {"Wahu", "TSA"}


def test_compute_routes_riders_to_correct_fleet_file():
    result = step5_bolt_payout.compute(
        bolt_earnings=_bolt_df(),
        outstanding_df=_outstanding_df(),
        invoices_all=_invoices_df(),
    )
    wahu_riders = set(result.fleets["Wahu"].payouts["rider_id"])
    tsa_riders = set(result.fleets["TSA"].payouts["rider_id"])
    assert wahu_riders == {"R1", "R3"}
    assert tsa_riders == {"R2"}


def test_compute_applies_matrix_per_rider():
    result = step5_bolt_payout.compute(
        bolt_earnings=_bolt_df(),
        outstanding_df=_outstanding_df(),
        invoices_all=_invoices_df(),
    )
    wahu = result.fleets["Wahu"].payouts.set_index("rider_id")
    tsa = result.fleets["TSA"].payouts.set_index("rider_id")
    # R1: 500 outstanding, 600 earnings -> ded 420, payout 180
    assert wahu.loc["R1", "deduction"] == 420.0
    assert wahu.loc["R1", "net_payout_to_rider"] == 180.0
    assert wahu.loc["R1", "outstanding_after"] == 80.0
    # R2: 300 outstanding, 600 earnings -> ded 300, payout 300, full clearance
    assert tsa.loc["R2", "deduction"] == 300.0
    assert tsa.loc["R2", "net_payout_to_rider"] == 300.0
    assert tsa.loc["R2", "outstanding_after"] == 0.0
    # R3: 0 outstanding, 600 earnings -> ded 0, payout 600
    assert wahu.loc["R3", "deduction"] == 0.0
    assert wahu.loc["R3", "net_payout_to_rider"] == 600.0


def test_compute_records_invoices_settled_for_fifo_deduction():
    result = step5_bolt_payout.compute(
        bolt_earnings=_bolt_df(),
        outstanding_df=_outstanding_df(),
        invoices_all=_invoices_df(),
    )
    r1 = result.fleets["Wahu"].payouts.set_index("rider_id").loc["R1"]
    # Deduction 420 against one 500 invoice -> 420 applied to i1.
    assert r1["invoices_settled"] == "i1"
    assert "i1=420.00" in r1["applications_detail"]


def test_compute_subtotals_by_agency():
    """Each fleet file carries a by-agency subtotal block."""
    result = step5_bolt_payout.compute(
        bolt_earnings=_bolt_df(),
        outstanding_df=_outstanding_df(),
        invoices_all=_invoices_df(),
    )
    sub = result.fleets["Wahu"].by_agency_subtotals.set_index("agency")
    # Wahu file has TSAC (R1) and Hortta (R3) rows.
    assert set(sub.index) == {"TSAC", "Hortta"}
    assert sub.loc["TSAC", "rider_count"] == 1
    assert sub.loc["TSAC", "deduction"] == 420.0
    assert sub.loc["Hortta", "deduction"] == 0.0
    # Grand totals.
    gt = result.fleets["Wahu"].grand_totals
    assert gt["rider_count"] == 2
    assert gt["bolt_earnings_total"] == 1200.0
    assert gt["deduction_total"] == 420.0
    assert gt["net_payout_to_rider_total"] == 780.0


def test_compute_skips_riders_with_zero_earnings():
    bolt = pd.DataFrame([
        dict(rider_id="R1", rider_name="Felix Adom",
             week_start=date(2026, 5, 11), week_end=date(2026, 5, 17),
             bolt_payout=0.0, momo_account="244111111"),
    ])
    result = step5_bolt_payout.compute(
        bolt_earnings=bolt,
        outstanding_df=_outstanding_df(),
        invoices_all=_invoices_df(),
    )
    assert result.fleets["Wahu"].payouts.empty
    assert result.fleets["TSA"].payouts.empty


def test_compute_skips_riders_not_in_outstanding_lookup(caplog):
    """A rider with bolt earnings but no fleet info (not in outstanding_df)
    should be skipped rather than misrouted."""
    bolt = pd.DataFrame([
        dict(rider_id="R-ghost", rider_name="Ghost",
             week_start=date(2026, 5, 11), week_end=date(2026, 5, 17),
             bolt_payout=600.0, momo_account=""),
    ])
    result = step5_bolt_payout.compute(
        bolt_earnings=bolt,
        outstanding_df=pd.DataFrame(),     # no outstanding info anywhere
        invoices_all=pd.DataFrame(),
    )
    assert result.fleets["Wahu"].payouts.empty
    assert result.fleets["TSA"].payouts.empty


def test_write_xlsx_emits_three_sheets():
    """Each fleet file must have payouts + by_agency_subtotals + grand_totals."""
    import io as _io
    result = step5_bolt_payout.compute(
        bolt_earnings=_bolt_df(),
        outstanding_df=_outstanding_df(),
        invoices_all=_invoices_df(),
    )
    payload = step5_bolt_payout.write_xlsx(result.fleets["Wahu"])
    book = pd.read_excel(_io.BytesIO(payload), sheet_name=None, engine="openpyxl")
    assert set(book.keys()) == {"payouts", "by_agency_subtotals", "grand_totals"}
