"""Prompt 11 — unit tests for the six operator rules."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.util.agency_history import agency_at_date, append_changes
from collections_v3.util.fifo import apply_fifo
from collections_v3.util.operator_rules import (
    SOFT_MATCH_AMOUNT_THRESHOLD_GHS,
    check_name_only_soft_match, check_never_overwrite, check_unfiltered_first,
)


def _ctx(**overrides) -> RunContext:
    base = dict(
        fleet=Fleet.All, agency=Agency.All, period=Period.MTD,
        start=date(2026, 5, 1), end=date(2026, 5, 21),
    )
    base.update(overrides)
    return RunContext(**base)


# ---------------------------------------------------------------------------
# Rule 1
# ---------------------------------------------------------------------------

def test_rule1_passes_for_unfiltered_run(tmp_path):
    res = check_unfiltered_first(_ctx(), artifacts_dir=tmp_path)
    assert res.passed
    assert res.rule == "unfiltered_first"


def test_rule1_blocks_filtered_run_with_no_universe(tmp_path):
    res = check_unfiltered_first(
        _ctx(fleet=Fleet.Wahu), artifacts_dir=tmp_path,
    )
    assert not res.passed
    assert "refused" in res.reason


def test_rule1_passes_when_universe_marker_exists(tmp_path):
    # Drop the marker file in artifacts/.
    marker = tmp_path / "billed_invoices_by_fleet_agency_All_All_mtd202605.xlsx"
    marker.write_bytes(b"stub")
    res = check_unfiltered_first(
        _ctx(fleet=Fleet.Wahu, agency=Agency.TSAC), artifacts_dir=tmp_path,
    )
    assert res.passed


def test_rule1_override_bypasses_the_check(tmp_path):
    res = check_unfiltered_first(
        _ctx(fleet=Fleet.Wahu), artifacts_dir=tmp_path,
        allow_override=True,
    )
    assert res.passed
    assert res.details and res.details.get("override") is True


# ---------------------------------------------------------------------------
# Rule 2
# ---------------------------------------------------------------------------

def test_rule2_blocks_high_value_name_only():
    res = check_name_only_soft_match(
        tier="NAME", amount=700.0, sender_phone="", reference="",
    )
    assert not res.passed
    assert "soft" in res.rule


def test_rule2_allows_high_value_when_phone_present():
    res = check_name_only_soft_match(
        tier="NAME", amount=700.0, sender_phone="244123456", reference="",
    )
    assert res.passed


def test_rule2_allows_high_value_when_reference_present():
    res = check_name_only_soft_match(
        tier="NAME", amount=700.0, sender_phone="", reference="CUS-1",
    )
    assert res.passed


def test_rule2_allows_low_value_even_without_anything():
    res = check_name_only_soft_match(
        tier="NAME", amount=SOFT_MATCH_AMOUNT_THRESHOLD_GHS,
        sender_phone="", reference="",
    )
    assert res.passed


def test_rule2_skipped_for_non_name_tiers():
    for tier in ["PHONE", "REF", "ACCOUNT", ""]:
        res = check_name_only_soft_match(
            tier=tier, amount=10_000.0, sender_phone="", reference="",
        )
        assert res.passed, f"tier {tier!r} should not trigger Rule 2"


# ---------------------------------------------------------------------------
# Rule 3 — apply_fifo overpayment becomes rider_credit (regression check)
# ---------------------------------------------------------------------------

def test_rule3_overpayment_becomes_credit_not_refund():
    invs = [dict(invoice_id="i1", invoice_date=date(2026, 5, 1), amount_due=300.0)]
    res = apply_fifo(500.0, invs)
    assert res.credit == 200.0
    assert res.applications == [("i1", 300.0)]


# ---------------------------------------------------------------------------
# Rule 4 — never overwrite (hard guard)
# ---------------------------------------------------------------------------

def test_rule4_refuses_existing_filename():
    res = check_never_overwrite(
        filename="rider_outstanding_All_All_mtd202605.xlsx",
        existing_names={"rider_outstanding_All_All_mtd202605.xlsx"},
    )
    assert not res.passed
    assert res.rule == "never_overwrite"


def test_rule4_passes_when_filename_not_colliding():
    res = check_never_overwrite(
        filename="rider_outstanding_All_All_mtd202605_v2.xlsx",
        existing_names={"rider_outstanding_All_All_mtd202605.xlsx"},
    )
    assert res.passed


# ---------------------------------------------------------------------------
# Rule 5 — agency_at_date lookup
# ---------------------------------------------------------------------------

def test_rule5_agency_at_date_returns_current_for_open_row(tmp_path):
    p = tmp_path / "history.xlsx"
    append_changes({"CUS-1": "TSAC"}, today=date(2026, 5, 1), path=p)
    assert agency_at_date("CUS-1", date(2026, 5, 10), path=p) == "TSAC"


def test_rule5_agency_at_date_returns_closed_agency_for_past_date(tmp_path):
    p = tmp_path / "history.xlsx"
    append_changes({"CUS-1": "Hortta"}, today=date(2026, 5, 1), path=p)
    # Switch on 2026-05-15.
    append_changes({"CUS-1": "TSAC"}, today=date(2026, 5, 15), path=p)
    # Pre-switch lookup -> Hortta. Post-switch -> TSAC.
    assert agency_at_date("CUS-1", date(2026, 5, 10), path=p) == "Hortta"
    assert agency_at_date("CUS-1", date(2026, 5, 16), path=p) == "TSAC"


def test_rule5_agency_at_date_returns_none_for_unknown_rider(tmp_path):
    p = tmp_path / "history.xlsx"
    append_changes({"CUS-1": "TSAC"}, today=date(2026, 5, 1), path=p)
    assert agency_at_date("CUS-ghost", date(2026, 5, 10), path=p) is None


# ---------------------------------------------------------------------------
# Rule 6 — apply_fifo without silent rounding (regression check)
# ---------------------------------------------------------------------------

def test_rule6_no_silent_rounding_in_fifo():
    invs = [dict(invoice_id="i1", invoice_date=date(2026, 5, 1), amount_due=33.33),
            dict(invoice_id="i2", invoice_date=date(2026, 5, 2), amount_due=33.33),
            dict(invoice_id="i3", invoice_date=date(2026, 5, 3), amount_due=33.34)]
    res = apply_fifo(100.0, invs)
    # Sum of applications must equal the input exactly.
    assert sum(amt for _, amt in res.applications) == 100.0
    assert res.credit == 0.0
