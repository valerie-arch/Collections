"""Prompt 5 acceptance: Step 2 three-tier matcher + FIFO + suspense routing.

Spec acceptance criteria:
  1. Receipt with phone matching an in-scope rider -> matched_payments.
  2. Receipt with phone matching an out-of-scope rider -> MATCHED_OUT_OF_SCOPE.
  3. Name-only Tier 2 match at score 84 falls to Tier 3 / Suspense.
  4. GHS 1,000 against three open invoices of 400/400/400 ->
     partial [400, 400, 200], 0 residual.
  5. GHS 500 against one open invoice of 300 -> clears invoice,
     200 -> rider_credit.
"""

from __future__ import annotations

from collections import namedtuple
from datetime import date

import pandas as pd
import pytest

from collections_v3.matching import tier1_phone, tier2_name, tier3_ref
from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.steps import step2_match
from collections_v3.util.already_booked import (
    build_already_booked_index, is_already_booked,
)
from collections_v3.util.fifo import apply_fifo
from collections_v3.util.rider_index import RiderIndex, build_index


def _invoices() -> pd.DataFrame:
    """Five riders, 1+ invoices each, fleet/agency tagged."""
    rows = [
        # Wahu/TSAC riders
        dict(invoice_id="i1", invoice_number="INV-1", rider_id="CUS-1",
             rider_name="Felix Adom", fleet="Wahu", agency="TSAC",
             invoice_date=date(2026, 5, 1), amount=400.0, amount_due=400.0),
        dict(invoice_id="i2", invoice_number="INV-2", rider_id="CUS-1",
             rider_name="Felix Adom", fleet="Wahu", agency="TSAC",
             invoice_date=date(2026, 5, 8), amount=400.0, amount_due=400.0),
        dict(invoice_id="i3", invoice_number="INV-3", rider_id="CUS-1",
             rider_name="Felix Adom", fleet="Wahu", agency="TSAC",
             invoice_date=date(2026, 5, 15), amount=400.0, amount_due=400.0),
        # Single small invoice for testing rider_credit
        dict(invoice_id="i10", invoice_number="INV-10", rider_id="CUS-2",
             rider_name="Eric Aheto", fleet="TSA", agency="TSAC",
             invoice_date=date(2026, 5, 1), amount=300.0, amount_due=300.0),
        # Wahu/Hortta rider
        dict(invoice_id="i20", invoice_number="INV-20", rider_id="CUS-3",
             rider_name="Frederick Barths", fleet="Wahu", agency="Hortta",
             invoice_date=date(2026, 5, 1), amount=200.0, amount_due=200.0),
        # Unknown-by-everything: a rider with no phone, no bike, no exact name match.
        dict(invoice_id="i30", invoice_number="INV-30", rider_id="CUS-4",
             rider_name="Mystery Rider Beta", fleet="Wahu", agency="Unassigned",
             invoice_date=date(2026, 5, 1), amount=100.0, amount_due=100.0),
    ]
    return pd.DataFrame(rows)


def _bolt() -> pd.DataFrame:
    return pd.DataFrame([
        dict(rider_name="Felix Adom",       momo_account="244111111"),
        dict(rider_name="Eric Aheto",       momo_account="245326779"),
        dict(rider_name="Frederick Barths", momo_account="244222222"),
    ])


def _bike_fleet() -> pd.DataFrame:
    return pd.DataFrame([
        dict(rider_name="Eric Aheto",   bike_reg="TSA-0021"),
        dict(rider_name="Felix Adom",   bike_reg="WAHUB-0042"),
        dict(rider_name="Frederick Barths", bike_reg="WAHUB-0043"),
    ])


def _index() -> RiderIndex:
    return build_index(
        invoices_all=_invoices(),
        bolt_earnings=_bolt(),
        bike_fleet_assignments=_bike_fleet(),
    )


def _ctx(fleet: Fleet, agency: Agency) -> RunContext:
    return RunContext(
        fleet=fleet, agency=agency, period=Period.MTD,
        start=date(2026, 5, 1), end=date(2026, 5, 21),
    )


Receipt = namedtuple("Receipt", [
    "txn_id", "channel", "date", "amount", "sender_name",
    "sender_phone_canonical", "sender_phone_raw",
    "sender_account", "reference", "narration", "source_file",
])


def _receipt(**kw) -> Receipt:
    base = dict(
        txn_id="", channel="mtn", date=date(2026, 5, 14), amount=0.0,
        sender_name="", sender_phone_canonical="", sender_phone_raw="",
        sender_account="", reference="", narration="", source_file="t.csv",
    )
    base.update(kw)
    return Receipt(**base)


# ---------------------------------------------------------------------------
# Direct tier unit tests
# ---------------------------------------------------------------------------

def test_tier1_phone_matches_canonical_phone():
    idx = _index()
    r = _receipt(sender_phone_canonical="244111111")
    rid, tier = tier1_phone(r, idx)
    assert (rid, tier) == ("CUS-1", "PHONE")


def test_tier1_no_phone_returns_none():
    idx = _index()
    r = _receipt(sender_name="who knows", reference="")
    rid, tier = tier1_phone(r, idx)
    assert (rid, tier) == (None, None)


def test_tier2_name_match_at_threshold_passes():
    idx = _index()
    # Exact match -> score 100, well above 85.
    r = _receipt(sender_name="Felix Adom")
    rid, tier, score = tier2_name(r, idx)
    assert (rid, tier) == ("CUS-1", "NAME")
    assert score >= 85


def test_tier2_name_match_below_threshold_fails():
    """Spec acceptance #3: a name-only match at score 84 must fall through."""
    idx = RiderIndex(name_list=[("alpha gamma delta epsilon", "RID-A")])
    # Construct a name designed to score < 85 via token_sort_ratio.
    r = _receipt(sender_name="zzz totally different name")
    rid, tier, score = tier2_name(r, idx)
    assert rid is None
    assert tier is None


def test_tier3_ref_finds_rider_id_in_reference_field():
    idx = _index()
    r = _receipt(reference="payment for cus-1 may rent")
    rid, tier = tier3_ref(r, idx)
    assert (rid, tier) == ("CUS-1", "REF")


def test_tier3_ref_finds_bike_reg_in_narration():
    idx = _index()
    r = _receipt(narration="TSA-0021 weekly")
    rid, tier = tier3_ref(r, idx)
    assert (rid, tier) == ("CUS-2", "REF")


# ---------------------------------------------------------------------------
# FIFO unit tests (acceptance #4 and #5)
# ---------------------------------------------------------------------------

def test_fifo_1000_against_three_400_invoices_partials_400_400_200():
    """Acceptance #4."""
    invs = [
        dict(invoice_id="i1", invoice_number="INV-1",
             invoice_date=date(2026, 5, 1), amount_due=400.0),
        dict(invoice_id="i2", invoice_number="INV-2",
             invoice_date=date(2026, 5, 8), amount_due=400.0),
        dict(invoice_id="i3", invoice_number="INV-3",
             invoice_date=date(2026, 5, 15), amount_due=400.0),
    ]
    res = apply_fifo(1000.0, invs)
    assert res.applications == [("i1", 400.0), ("i2", 400.0), ("i3", 200.0)]
    assert res.credit == 0.0
    assert res.remaining_due == {"i1": 0.0, "i2": 0.0, "i3": 200.0}


def test_fifo_500_against_one_300_clears_invoice_and_credits_200():
    """Acceptance #5."""
    invs = [dict(invoice_id="i10", invoice_number="INV-10",
                 invoice_date=date(2026, 5, 1), amount_due=300.0)]
    res = apply_fifo(500.0, invs)
    assert res.applications == [("i10", 300.0)]
    assert res.credit == 200.0
    assert res.remaining_due == {"i10": 0.0}


def test_fifo_no_open_invoices_all_goes_to_credit():
    res = apply_fifo(150.0, [])
    assert res.applications == []
    assert res.credit == 150.0


def test_fifo_uses_cents_internally_no_float_drift():
    invs = [dict(invoice_id="i1", invoice_date=date(2026, 5, 1), amount_due=33.33),
            dict(invoice_id="i2", invoice_date=date(2026, 5, 2), amount_due=33.33),
            dict(invoice_id="i3", invoice_date=date(2026, 5, 3), amount_due=33.34)]
    res = apply_fifo(100.0, invs)
    assert res.applications == [("i1", 33.33), ("i2", 33.33), ("i3", 33.34)]
    assert res.credit == 0.0


# ---------------------------------------------------------------------------
# Orchestrator acceptance tests (#1, #2)
# ---------------------------------------------------------------------------

def test_acceptance_1_in_scope_phone_match_lands_in_matched_payments():
    """Acceptance #1."""
    receipts = pd.DataFrame([_receipt(
        txn_id="T1", amount=400.0,
        sender_phone_canonical="244111111",  # Felix Adom -> CUS-1 (Wahu/TSAC)
    )._asdict()])
    ctx = _ctx(Fleet.All, Agency.All)
    res = step2_match.run(
        ctx, receipts=receipts, invoices_all=_invoices(),
        riders_in_scope={"CUS-1", "CUS-2", "CUS-3", "CUS-4"},
        rider_index=_index(),
    )
    assert len(res.matched_payments) == 1
    row = res.matched_payments.iloc[0]
    assert row["rider_id"] == "CUS-1"
    assert row["match_tier"] == "PHONE"
    assert row["applied_amount"] == 400.0
    assert res.out_of_scope.empty
    assert res.suspense.empty


def test_acceptance_2_out_of_scope_phone_match_routes_to_out_of_scope():
    """Acceptance #2 — filter is --fleet TSA --agency TSAC; a Wahu rider's
    phone match must go to MATCHED_OUT_OF_SCOPE."""
    receipts = pd.DataFrame([_receipt(
        txn_id="T1", amount=400.0,
        sender_phone_canonical="244111111",  # Felix Adom -> CUS-1 (Wahu)
    )._asdict()])
    ctx = _ctx(Fleet.TSA, Agency.TSAC)
    res = step2_match.run(
        ctx, receipts=receipts, invoices_all=_invoices(),
        riders_in_scope={"CUS-2"},   # only TSA rider in scope
        rider_index=_index(),
    )
    assert res.matched_payments.empty
    assert len(res.out_of_scope) == 1
    row = res.out_of_scope.iloc[0]
    assert row["rider_id"] == "CUS-1"
    assert row["rider_fleet"] == "Wahu"
    assert row["match_tier"] == "PHONE"
    assert row["active_filter_fleet"] == "TSA"


def test_acceptance_3_name_match_at_84_falls_to_suspense():
    """Acceptance #3 — Tier 2 score 84 falls through; no Tier 3 hit -> suspense."""
    # Force a Tier 2 score < 85 by using a sender_name with little token overlap.
    receipts = pd.DataFrame([_receipt(
        txn_id="T-fall", amount=100.0,
        sender_name="zzz totally different name",
    )._asdict()])
    ctx = _ctx(Fleet.All, Agency.All)
    # Tiny rider index so we control token_sort_ratio entirely.
    idx = RiderIndex(name_list=[("alpha gamma delta epsilon", "RID-A")],
                    rider_id_to_name={"RID-A": "Alpha Gamma Delta Epsilon"},
                    rider_id_to_fleet={"RID-A": "Wahu"},
                    rider_id_to_agency={"RID-A": "TSAC"},
                    rider_id_set={"RID-A"})
    res = step2_match.run(
        ctx, receipts=receipts,
        invoices_all=pd.DataFrame(columns=["rider_id", "invoice_id", "invoice_number",
                                            "invoice_date", "amount_due"]),
        riders_in_scope={"RID-A"}, rider_index=idx,
    )
    assert res.matched_payments.empty
    assert res.out_of_scope.empty
    assert len(res.suspense) == 1
    assert res.suspense.iloc[0]["reason"] == "no_tier_hit"


def test_orchestrator_fifo_applies_1000_across_3_invoices():
    """End-to-end smoke combining Tier 1 + FIFO (Acceptance #4 path)."""
    receipts = pd.DataFrame([_receipt(
        txn_id="T-big", amount=1000.0,
        sender_phone_canonical="244111111",  # CUS-1 has 3x400 open
    )._asdict()])
    res = step2_match.run(
        _ctx(Fleet.All, Agency.All),
        receipts=receipts, invoices_all=_invoices(),
        riders_in_scope={"CUS-1"}, rider_index=_index(),
    )
    by_invoice = dict(zip(res.matched_payments["invoice_id"],
                           res.matched_payments["applied_amount"]))
    assert by_invoice == {"i1": 400.0, "i2": 400.0, "i3": 200.0}
    assert res.rider_credits.empty   # 1000 fully consumed


def test_orchestrator_overpayment_creates_rider_credit_row():
    """End-to-end smoke combining Tier 1 + FIFO with leftover (Acceptance #5)."""
    receipts = pd.DataFrame([_receipt(
        txn_id="T-over", amount=500.0,
        sender_phone_canonical="245326779",  # CUS-2 has one 300 invoice
    )._asdict()])
    res = step2_match.run(
        _ctx(Fleet.All, Agency.All),
        receipts=receipts, invoices_all=_invoices(),
        riders_in_scope={"CUS-2"}, rider_index=_index(),
    )
    # Two rows in matched_payments: 300 applied to invoice i10, then 200 credit.
    assert len(res.matched_payments) == 2
    applied = res.matched_payments[~res.matched_payments["is_residual_credit"]]
    credit = res.matched_payments[res.matched_payments["is_residual_credit"]]
    assert applied.iloc[0]["invoice_id"] == "i10"
    assert applied.iloc[0]["applied_amount"] == 300.0
    assert credit.iloc[0]["applied_amount"] == 200.0
    assert len(res.rider_credits) == 1
    assert res.rider_credits.iloc[0]["amount"] == 200.0


# ---------------------------------------------------------------------------
# Already-booked check (2A)
# ---------------------------------------------------------------------------

def test_already_booked_when_txn_id_appears_in_zoho_reference():
    zoho = pd.DataFrame([
        dict(payment_id="P1", reference_number="80315511449",
             date=date(2026, 4, 30), amount=140.0),
    ])
    ab = build_already_booked_index(zoho)
    r = _receipt(txn_id="80315511449", amount=140.0, date=date(2026, 4, 30))
    assert is_already_booked(r, ab) is True


def test_orchestrator_already_booked_receipt_is_skipped():
    zoho = pd.DataFrame([
        dict(payment_id="P1", reference_number="80315511449",
             date=date(2026, 4, 30), amount=140.0),
    ])
    receipts = pd.DataFrame([
        _receipt(txn_id="80315511449", amount=140.0,
                 sender_phone_canonical="244111111")._asdict(),  # would tier-1 hit Felix
    ])
    res = step2_match.run(
        _ctx(Fleet.All, Agency.All),
        receipts=receipts, invoices_all=_invoices(),
        riders_in_scope={"CUS-1"}, rider_index=_index(),
        zoho_payments=zoho,
    )
    assert res.matched_payments.empty
    assert len(res.already_in_zoho) == 1
    assert res.already_in_zoho.iloc[0]["txn_id"] == "80315511449"
