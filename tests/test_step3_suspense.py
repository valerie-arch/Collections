"""Prompt 6 acceptance: suspense XLSX export / re-import / aging / guardrail.

Spec acceptance:
  1. Operator-edited file with one row assigned, one row blank →
     assigned row appears in `accepted` (ready for FIFO); blank row
     carries forward with `days_in_suspense + 1`.
  2. A GHS 700 name-only row with no phone/ref is rejected even when
     the operator assigns it.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from collections_v3.io_.suspense_persistence import (
    SUSPENSE_COLUMNS, read_suspense_xlsx, write_suspense_xlsx, SuspenseRow,
)
from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.steps import step3_suspense
from collections_v3.util.decision_aids import score_candidates
from collections_v3.util.rider_index import RiderIndex
from collections_v3.util.soft_match_guardrail import check_assignment
from collections_v3.util.suspense_aging import aging_bucket, days_in_suspense


# ---------------------------------------------------------------------------
# Aging
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("days,expected", [
    (0, "0_7"), (7, "0_7"),
    (8, "8_30"), (30, "8_30"),
    (31, "31_60"), (60, "31_60"),
    (61, "60+"), (365, "60+"),
])
def test_aging_buckets(days, expected):
    assert aging_bucket(days) == expected


def test_days_in_suspense_floor_zero():
    today = date(2026, 5, 21)
    # Future first_seen -> floor at 0, never negative.
    assert days_in_suspense(date(2026, 6, 1), today=today) == 0
    assert days_in_suspense(date(2026, 5, 14), today=today) == 7
    assert days_in_suspense(None, today=today) == 0


# ---------------------------------------------------------------------------
# Decision-aid scoring
# ---------------------------------------------------------------------------

def _two_rider_index() -> RiderIndex:
    idx = RiderIndex(
        name_list=[("felix adom", "CUS-1"), ("frederick barths", "CUS-3")],
        rider_id_to_name={"CUS-1": "Felix Adom", "CUS-3": "Frederick Barths"},
        rider_id_to_fleet={"CUS-1": "Wahu", "CUS-3": "Wahu"},
        rider_id_to_agency={"CUS-1": "TSAC", "CUS-3": "Hortta"},
        rider_id_set={"CUS-1", "CUS-3"},
        phone_to_rider={"244111111": "CUS-1"},
    )
    return idx


def _two_rider_invoices() -> pd.DataFrame:
    return pd.DataFrame([
        dict(invoice_id="i1", rider_id="CUS-1", amount_due=400.0,
             invoice_date=date(2026, 5, 1), invoice_number="INV-1"),
        dict(invoice_id="i2", rider_id="CUS-1", amount_due=400.0,
             invoice_date=date(2026, 5, 8), invoice_number="INV-2"),
        dict(invoice_id="i3", rider_id="CUS-3", amount_due=200.0,
             invoice_date=date(2026, 5, 1), invoice_number="INV-3"),
    ])


def test_decision_aids_top_match_includes_name_phone_amount():
    idx = _two_rider_index()
    invs = _two_rider_invoices()
    # Receipt matches Felix on name + phone + amount.
    cands = score_candidates(
        sender_name="Felix Adom", sender_phone="244111111",
        receipt_amount=400.0, index=idx, invoices_all=invs,
    )
    assert cands[0].rider_id == "CUS-1"
    assert cands[0].name_score >= 95
    assert cands[0].phone_partial >= 90
    assert cands[0].amount_match == 100
    # Composite: 100*0.5 + 100*0.3 + 100*0.2 = 100.
    assert cands[0].composite_score >= 95


def test_decision_aids_open_invoices_inlined():
    idx = _two_rider_index()
    invs = _two_rider_invoices()
    cands = score_candidates(
        sender_name="Felix Adom", sender_phone="",
        receipt_amount=0.0, index=idx, invoices_all=invs,
    )
    felix = next(c for c in cands if c.rider_id == "CUS-1")
    assert ("i1", 400.0) in felix.open_invoices
    assert ("i2", 400.0) in felix.open_invoices


# ---------------------------------------------------------------------------
# Soft-match guardrail (Acceptance #2)
# ---------------------------------------------------------------------------

def test_guardrail_rejects_700_name_only_no_phone_no_ref():
    """Acceptance #2."""
    gr = check_assignment(amount=700.0, sender_phone="", reference="", narration="")
    assert gr.accepted is False
    assert "name_only" in gr.reason


def test_guardrail_accepts_700_when_phone_present():
    gr = check_assignment(amount=700.0, sender_phone="244111111", reference="")
    assert gr.accepted is True


def test_guardrail_accepts_700_when_reference_present():
    gr = check_assignment(amount=700.0, sender_phone="", reference="CUS-1")
    assert gr.accepted is True


def test_guardrail_accepts_400_even_without_phone_or_ref():
    gr = check_assignment(amount=400.0, sender_phone="", reference="")
    assert gr.accepted is True


def test_reimport_rejects_700_name_only_assignment(tmp_path):
    """Acceptance #2, end-to-end through the orchestrator."""
    # Build a suspense file with one row: GHS 700, no phone, no ref.
    rows = [SuspenseRow(
        txn_id="T1", channel="bank", date=date(2026, 5, 14), amount=700.0,
        sender_name="Felix Adom", sender_phone_canonical="", reference="",
        narration="", source_file="s.csv",
        first_seen_at=date(2026, 5, 10), days_in_suspense=4, aging_bucket="0_7",
        candidates=[], assigned_rider_id="CUS-1", notes="",
    )]
    p = tmp_path / "sus.xlsx"
    write_suspense_xlsx(rows, p)

    idx = _two_rider_index()
    out = step3_suspense.reimport(p, rider_index=idx, today=date(2026, 5, 14))
    assert len(out["accepted"]) == 0
    assert len(out["rejected"]) == 1
    assert "name_only" in out["rejected"][0]["reject_reason"]


# ---------------------------------------------------------------------------
# Reimport happy path (Acceptance #1)
# ---------------------------------------------------------------------------

def test_reimport_one_assigned_one_blank(tmp_path):
    """Acceptance #1, part 1: assigned row → accepted, blank row → still_pending."""
    rows = [
        # Row 1: operator assigned, has phone -> guardrail won't block.
        SuspenseRow(
            txn_id="T1", channel="mtn", date=date(2026, 5, 14), amount=400.0,
            sender_name="Felix Adom", sender_phone_canonical="244111111",
            reference="", narration="", source_file="s.csv",
            first_seen_at=date(2026, 5, 14), days_in_suspense=0, aging_bucket="0_7",
            candidates=[], assigned_rider_id="CUS-1", notes="",
        ),
        # Row 2: operator left blank — stays pending.
        SuspenseRow(
            txn_id="T2", channel="bank", date=date(2026, 5, 14), amount=200.0,
            sender_name="unknown", sender_phone_canonical="", reference="",
            narration="", source_file="s.csv",
            first_seen_at=date(2026, 5, 14), days_in_suspense=0, aging_bucket="0_7",
            candidates=[], assigned_rider_id="", notes="",
        ),
    ]
    p = tmp_path / "sus.xlsx"
    write_suspense_xlsx(rows, p)
    idx = _two_rider_index()
    out = step3_suspense.reimport(p, rider_index=idx, today=date(2026, 5, 14))
    assert len(out["accepted"]) == 1
    assert out["accepted"][0]["txn_id"] == "T1"
    assert len(out["still_pending"]) == 1
    assert out["still_pending"][0]["txn_id"] == "T2"


def test_carry_forward_increments_days_in_suspense(tmp_path):
    """Acceptance #1, part 2: a blank row carries to the next run with +N days."""
    # Run 1: row first appears on 2026-05-14.
    rows_v1 = [SuspenseRow(
        txn_id="T2", channel="bank", date=date(2026, 5, 14), amount=200.0,
        sender_name="unknown", sender_phone_canonical="", reference="",
        narration="", source_file="s.csv",
        first_seen_at=date(2026, 5, 14), days_in_suspense=0, aging_bucket="0_7",
        candidates=[], assigned_rider_id="", notes="",
    )]
    p_prev = tmp_path / "prev.xlsx"
    write_suspense_xlsx(rows_v1, p_prev)
    prev_df = read_suspense_xlsx(p_prev)

    # Run 2: same row still in Step 2 suspense, two days later.
    step2_suspense = pd.DataFrame([{
        "txn_id": "T2", "channel": "bank", "date": date(2026, 5, 14),
        "amount": 200.0, "sender_name": "unknown",
        "sender_phone_canonical": "", "reference": "", "narration": "",
        "source_file": "s.csv", "reason": "no_tier_hit",
    }])

    idx = _two_rider_index()
    ctx = RunContext(
        fleet=Fleet.All, agency=Agency.All, period=Period.MTD,
        start=date(2026, 5, 1), end=date(2026, 5, 16),
    )
    out_path = tmp_path / "new.xlsx"
    written = step3_suspense.export(
        ctx,
        step2_suspense=step2_suspense, previous_suspense=prev_df,
        rider_index=idx, invoices_all=_two_rider_invoices(),
        out_path=out_path, today=date(2026, 5, 16),
    )
    # Row should now have first_seen_at = 2026-05-14 (preserved) and
    # days_in_suspense = 2.
    assert len(written) == 1
    r = written[0]
    assert r.first_seen_at == date(2026, 5, 14)
    assert r.days_in_suspense == 2
    assert r.aging_bucket == "0_7"


def test_carry_forward_old_row_advances_aging_bucket(tmp_path):
    """A row that's been pending 35 days should now bucket as 31_60."""
    rows_v1 = [SuspenseRow(
        txn_id="T_old", channel="mtn", date=date(2026, 4, 11), amount=50.0,
        sender_name="zzz", sender_phone_canonical="", reference="",
        narration="", source_file="s.csv",
        first_seen_at=date(2026, 4, 11), days_in_suspense=0, aging_bucket="0_7",
        candidates=[], assigned_rider_id="", notes="",
    )]
    p_prev = tmp_path / "prev.xlsx"
    write_suspense_xlsx(rows_v1, p_prev)
    prev_df = read_suspense_xlsx(p_prev)

    # Same row still in Step 2 suspense 35 days later.
    step2_suspense = pd.DataFrame([{
        "txn_id": "T_old", "channel": "mtn", "date": date(2026, 4, 11),
        "amount": 50.0, "sender_name": "zzz",
        "sender_phone_canonical": "", "reference": "", "narration": "",
        "source_file": "s.csv", "reason": "no_tier_hit",
    }])
    out_path = tmp_path / "new.xlsx"
    ctx = RunContext(fleet=Fleet.All, agency=Agency.All, period=Period.MTD,
                     start=date(2026, 4, 1), end=date(2026, 5, 16))
    written = step3_suspense.export(
        ctx, step2_suspense=step2_suspense, previous_suspense=prev_df,
        rider_index=_two_rider_index(), invoices_all=_two_rider_invoices(),
        out_path=out_path, today=date(2026, 5, 16),
    )
    assert written[0].days_in_suspense == 35
    assert written[0].aging_bucket == "31_60"
