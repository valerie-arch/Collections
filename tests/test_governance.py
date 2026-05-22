"""Prompt 12 acceptance: governance loader + include_bolt_weekly toggle
+ CLI banner.

Spec acceptance:
  1. Flipping `agency_scoring.include_bolt_weekly` from true to false
     changes Step 6's `collection_rate_pct` for a fixture agency.
  2. CLI prints a one-line banner on startup:
     `governance: defaults in effect for [Q1, Q2, Q3]` until those values
     are explicitly set in governance.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from collections_v3 import governance
from collections_v3.cli import app
from collections_v3.util import agency_performance


runner = CliRunner()


# ---------------------------------------------------------------------------
# Loader behaviour
# ---------------------------------------------------------------------------

def test_load_returns_all_defaults_when_file_missing(tmp_path):
    loaded = governance.load(tmp_path / "missing.yaml")
    assert loaded.defaults_in_effect == ["Q1", "Q2", "Q3"]
    assert loaded.source_path is None
    assert loaded.config.commission.midweek_switch_attribution == "week_end"
    assert loaded.config.commission.basis == "total_applied"
    assert loaded.config.agency_scoring.include_bolt_weekly is True


def test_load_returns_all_defaults_when_file_empty(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    loaded = governance.load(p)
    assert loaded.defaults_in_effect == ["Q1", "Q2", "Q3"]


def test_load_marks_only_unset_qs_as_default(tmp_path):
    p = tmp_path / "partial.yaml"
    p.write_text(yaml.safe_dump({
        "agency_scoring": {"include_bolt_weekly": False},
    }))
    loaded = governance.load(p)
    assert "Q3" not in loaded.defaults_in_effect    # explicitly set
    assert "Q1" in loaded.defaults_in_effect
    assert "Q2" in loaded.defaults_in_effect
    assert loaded.config.agency_scoring.include_bolt_weekly is False


def test_load_returns_no_defaults_when_every_q_is_set(tmp_path):
    p = tmp_path / "full.yaml"
    p.write_text(yaml.safe_dump({
        "commission": {
            "midweek_switch_attribution": "prorated",
            "basis": "momo_bank_only",
        },
        "agency_scoring": {"include_bolt_weekly": False},
    }))
    loaded = governance.load(p)
    assert loaded.defaults_in_effect == []
    assert governance.banner_text(loaded) is None


def test_load_rejects_unknown_enum_value(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump({
        "commission": {"basis": "not_a_real_basis"},
    }))
    with pytest.raises(Exception):
        governance.load(p)


# ---------------------------------------------------------------------------
# Acceptance #1 — flipping include_bolt_weekly changes collection_rate_pct
# ---------------------------------------------------------------------------

@dataclass
class _FakeFleetPayout:
    by_agency_subtotals: pd.DataFrame


def _fixture_outstanding_and_bolt():
    """One agency (TSAC), opening 1000, Step 2 applied 200, Bolt deducted 500.
    With Bolt:    rate = (200 + 500) / 1000 = 70.0%
    Without Bolt: rate = 200 / 1000 = 20.0%"""
    outstanding = pd.DataFrame([
        dict(rider_id="R1", rider_name="X", fleet="Wahu", agency="TSAC",
             opening_outstanding=1000.0, applied_this_run=200.0,
             prior_credit=0.0, prior_credit_consumed=0.0, new_credit_this_run=0.0,
             closing_outstanding=800.0, closing_credit=0.0, open_invoice_count=1),
    ])
    bolt_fleets = {
        "Wahu": _FakeFleetPayout(by_agency_subtotals=pd.DataFrame([
            dict(agency="TSAC", rider_count=1, bolt_earnings=600.0,
                 deduction=500.0, net_payout_to_rider=100.0),
        ])),
        "TSA": _FakeFleetPayout(by_agency_subtotals=pd.DataFrame()),
    }
    return outstanding, bolt_fleets


def test_acceptance_1_include_bolt_weekly_toggle_changes_rate():
    outstanding, bolt_fleets = _fixture_outstanding_and_bolt()

    with_bolt = agency_performance.compute(
        outstanding_df=outstanding,
        matched_payments=pd.DataFrame(),
        total_receipts=1, suspense_count=0,
        bolt_fleets=bolt_fleets, include_bolt_weekly=True,
    )
    without_bolt = agency_performance.compute(
        outstanding_df=outstanding,
        matched_payments=pd.DataFrame(),
        total_receipts=1, suspense_count=0,
        bolt_fleets=bolt_fleets, include_bolt_weekly=False,
    )
    assert float(with_bolt.iloc[0]["collection_rate_pct"]) == 70.0
    assert float(without_bolt.iloc[0]["collection_rate_pct"]) == 20.0
    # And the toggle moved the needle.
    assert with_bolt.iloc[0]["collection_rate_pct"] != without_bolt.iloc[0]["collection_rate_pct"]


# ---------------------------------------------------------------------------
# Acceptance #2 — CLI banner
# ---------------------------------------------------------------------------

def test_banner_lists_qs_using_defaults(tmp_path):
    """Direct banner_text() check — the formatted string."""
    loaded = governance.load(tmp_path / "missing.yaml")
    text = governance.banner_text(loaded)
    assert text is not None
    assert "defaults in effect" in text
    assert "Q1" in text and "Q2" in text and "Q3" in text


def test_cli_emits_banner_when_governance_yaml_uses_defaults(tmp_path, monkeypatch):
    """End-to-end: run the CLI in an empty working directory (so the local
    governance.yaml is absent) — the banner must appear on stdout before
    Rule 1 fires."""
    monkeypatch.chdir(tmp_path)
    # The CLI eventually fails because there's no Drive client etc., but the
    # banner is printed BEFORE any of that machinery is reached.
    result = runner.invoke(app, [
        "run", "--fleet", "All", "--agency", "All", "--period", "MTD",
        "--start", "2026-05-01", "--end", "2026-05-21", "--no-upload",
    ])
    combined = (result.output or "") + (result.stderr or "")
    assert "governance: defaults in effect for" in combined
    assert "Q1" in combined and "Q2" in combined and "Q3" in combined


def test_cli_skips_banner_when_governance_yaml_overrides_every_q(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "governance.yaml").write_text(yaml.safe_dump({
        "commission": {
            "midweek_switch_attribution": "week_end",
            "basis": "total_applied",
        },
        "agency_scoring": {"include_bolt_weekly": True},
    }))
    result = runner.invoke(app, [
        "run", "--fleet", "All", "--agency", "All", "--period", "MTD",
        "--start", "2026-05-01", "--end", "2026-05-21", "--no-upload",
    ])
    combined = (result.output or "") + (result.stderr or "")
    assert "governance: defaults in effect" not in combined
