"""Prompt 7 acceptance: rider_outstanding compute + carry-forward credit.

Spec acceptance:
  1. Rider with 3 open invoices [400, 400, 400] and one matched 1,000 payment
     → outstanding = 200, credit = 0.
  2. Rider with 1 open invoice [300] and a 500 matched payment
     → outstanding = 0, rider_credit = 200.
  3. Filename for --fleet Wahu --agency TSAC --period MTD in May 2026
     → rider_outstanding_Wahu_TSAC_mtd202605.xlsx.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.steps import step4_outstanding
from collections_v3.util.credits import load_balances, write_balances
from collections_v3.util.paths import build_filename


def _opening(rider_id: str, amount: float, *, open_count: int = 1, name="X", fleet="Wahu", agency="TSAC") -> pd.DataFrame:
    return pd.DataFrame([{
        "rider_id": rider_id, "rider_name": name, "fleet": fleet, "agency": agency,
        "opening_outstanding": amount, "open_invoice_count": open_count,
    }])


def _matched(rider_id: str, applied: float) -> pd.DataFrame:
    return pd.DataFrame([{
        "txn_id": "T1", "channel": "mtn", "date": date(2026, 5, 14),
        "receipt_amount": applied, "rider_id": rider_id, "rider_name": "X",
        "match_tier": "PHONE", "match_score": None,
        "invoice_id": "i1", "applied_amount": applied,
        "is_residual_credit": False, "source_file": "x.csv",
    }])


def _credit(rider_id: str, amount: float) -> pd.DataFrame:
    return pd.DataFrame([{
        "rider_id": rider_id, "rider_name": "X", "amount": amount,
        "source_txn_id": "T1", "source_file": "x.csv", "date": date(2026, 5, 14),
    }])


# ---------------------------------------------------------------------------
# Acceptance #1: 3x400 invoices + 1000 payment -> outstanding=200, credit=0
# ---------------------------------------------------------------------------

def test_acceptance_1_partial_clears_three_400s_leaves_200():
    opening = _opening("R1", 1200.0, open_count=3)
    matched = pd.DataFrame([
        # FIFO applied 1000 across three invoices (400 + 400 + 200), no residual.
        {"rider_id": "R1", "applied_amount": 400.0, "is_residual_credit": False},
        {"rider_id": "R1", "applied_amount": 400.0, "is_residual_credit": False},
        {"rider_id": "R1", "applied_amount": 200.0, "is_residual_credit": False},
    ])
    res = step4_outstanding.compute(
        opening_outstanding=opening,
        matched_payments=matched,
        rider_credits_this_run=pd.DataFrame(),
    )
    row = res.outstanding.iloc[0]
    assert row["rider_id"] == "R1"
    assert row["closing_outstanding"] == 200.0
    assert row["closing_credit"] == 0.0
    assert res.closing_credits == {}   # no credit persisted next run


# ---------------------------------------------------------------------------
# Acceptance #2: 1x300 invoice + 500 payment -> outstanding=0, credit=200
# ---------------------------------------------------------------------------

def test_acceptance_2_overpayment_clears_and_credits_200():
    opening = _opening("R2", 300.0, open_count=1)
    matched = pd.DataFrame([
        # FIFO applied 300 to the only invoice, residual 200 became a credit row.
        {"rider_id": "R2", "applied_amount": 300.0, "is_residual_credit": False},
        {"rider_id": "R2", "applied_amount": 200.0, "is_residual_credit": True},
    ])
    credits = _credit("R2", 200.0)
    res = step4_outstanding.compute(
        opening_outstanding=opening,
        matched_payments=matched,
        rider_credits_this_run=credits,
    )
    row = res.outstanding.iloc[0]
    assert row["rider_id"] == "R2"
    assert row["closing_outstanding"] == 0.0
    assert row["closing_credit"] == 200.0
    assert res.closing_credits == {"R2": 200.0}


# ---------------------------------------------------------------------------
# Acceptance #3: filename pattern
# ---------------------------------------------------------------------------

def test_acceptance_3_filename_format():
    ctx = RunContext(
        fleet=Fleet.Wahu, agency=Agency.TSAC, period=Period.MTD,
        start=date(2026, 5, 1), end=date(2026, 5, 21),
    )
    assert build_filename("rider_outstanding", ctx) == "rider_outstanding_Wahu_TSAC_mtd202605.xlsx"


# ---------------------------------------------------------------------------
# Carry-forward credit between runs
# ---------------------------------------------------------------------------

def test_prior_credit_offsets_opening_then_persists_remainder(tmp_path):
    """Run A: rider over-pays 200 -> credit persisted.
    Run B: new opening 150, no payment -> credit eats it; closing_credit=50."""
    credits_path = tmp_path / "credits.xlsx"

    # Persist a prior credit balance directly.
    write_balances({"R3": 200.0}, rider_id_to_name={"R3": "Test Rider"}, path=credits_path)
    assert load_balances(credits_path)["R3"] == 200.0

    opening = _opening("R3", 150.0, open_count=2)
    res = step4_outstanding.run(
        ctx=RunContext(fleet=Fleet.All, agency=Agency.All, period=Period.MTD,
                       start=date(2026, 5, 1), end=date(2026, 5, 21)),
        opening_outstanding=opening,
        matched_payments=pd.DataFrame(),
        rider_credits_this_run=pd.DataFrame(),
        prior_credits_path=credits_path,
    )
    row = res.outstanding.iloc[0]
    assert row["prior_credit"] == 200.0
    assert row["prior_credit_consumed"] == 150.0
    assert row["closing_outstanding"] == 0.0
    assert row["closing_credit"] == 50.0
    # Persisted balance for next run = 50.
    assert load_balances(credits_path) == {"R3": 50.0}


def test_zero_credit_is_dropped_from_persistence(tmp_path):
    """Closing credit of 0 must not pollute the credits file."""
    credits_path = tmp_path / "credits.xlsx"
    opening = _opening("R4", 1200.0, open_count=3)
    matched = pd.DataFrame([
        {"rider_id": "R4", "applied_amount": 1000.0, "is_residual_credit": False},
    ])
    step4_outstanding.run(
        ctx=RunContext(fleet=Fleet.All, agency=Agency.All, period=Period.MTD,
                       start=date(2026, 5, 1), end=date(2026, 5, 21)),
        opening_outstanding=opening,
        matched_payments=matched,
        rider_credits_this_run=pd.DataFrame(),
        prior_credits_path=credits_path,
    )
    # Closing outstanding 200, closing credit 0 -> file written, but rider absent.
    assert load_balances(credits_path) == {}


def test_rider_only_in_credits_still_gets_a_row():
    """A rider with no opening row but a prior credit should appear (covers
    riders fully settled but holding a credit)."""
    res = step4_outstanding.compute(
        opening_outstanding=pd.DataFrame(columns=[
            "rider_id", "rider_name", "fleet", "agency",
            "opening_outstanding", "open_invoice_count"]),
        matched_payments=pd.DataFrame(),
        rider_credits_this_run=pd.DataFrame(),
        prior_credits={"R-ghost": 75.0},
    )
    assert len(res.outstanding) == 1
    row = res.outstanding.iloc[0]
    assert row["rider_id"] == "R-ghost"
    assert row["prior_credit"] == 75.0
    assert row["closing_outstanding"] == 0.0
    assert row["closing_credit"] == 75.0


def test_totals_summary_aggregates_correctly():
    opening = pd.concat([
        _opening("R1", 1200.0, open_count=3, name="A"),
        _opening("R2", 300.0, open_count=1, name="B"),
    ], ignore_index=True)
    matched = pd.DataFrame([
        {"rider_id": "R1", "applied_amount": 1000.0, "is_residual_credit": False},
        {"rider_id": "R2", "applied_amount": 300.0, "is_residual_credit": False},
    ])
    credits = _credit("R2", 200.0)
    res = step4_outstanding.compute(
        opening_outstanding=opening,
        matched_payments=matched,
        rider_credits_this_run=credits,
    )
    t = res.totals
    assert t["riders"] == 2
    assert t["opening_total"] == 1500.0
    assert t["applied_total"] == 1300.0
    assert t["closing_outstanding_total"] == 200.0
    assert t["closing_credit_total"] == 200.0
    assert t["riders_with_open_balance"] == 1
    assert t["riders_with_credit"] == 1
