"""Prompt 2 acceptance: CLI defaults, period resolution, filename builder."""

from __future__ import annotations

import re
from datetime import date

import pytest
from typer.testing import CliRunner

from collections_v3.cli import app, resolve_window
from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.util.paths import build_filename
from collections_v3.util.phone import normalize_phone


runner = CliRunner()


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_help_prints_all_three_filters_with_enums():
    """typer may wrap enum brackets mid-word when long flag descriptions
    widen the left column — e.g. `unassigned` becomes `unassigne` + `d|all`
    spanning two lines, with the option description text wedged between.
    Test on prefixes that survive the wrap so the assertion stays stable
    even when typer's rendering changes."""
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    flat = re.sub(r"[│\n\s]+", "", result.stdout.lower())

    assert "--fleet" in flat and "--period" in flat and "--agency" in flat
    # Fleet + agency enum stems (short, never wrapped).
    for v in ("wahu", "tsa", "all", "tsac", "hortta"):
        assert v in flat, f"expected enum value {v!r} in help"
    # Long values may wrap — match the prefix that always appears.
    for prefix in ("lifetime", "cus", "unassign"):
        assert prefix in flat, f"expected enum prefix {prefix!r} in help"


def test_defaults_resolve_to_all_week_all(monkeypatch):
    """Omitted filters must default to --fleet All / --period Week / --agency All."""
    captured: dict = {}

    def fake_run_and_publish(*, upload: bool = True, ctx=None):
        return {
            "filename": "x.xlsx", "local_path": "x", "drive_id": None,
            "drive_link": None, "total_billed": 0, "split_total": 0,
            "wahu_count": 0, "tsa_count": 0, "flag_count": 0,
        }

    # Patch step0 so the test doesn't hit Drive.
    import collections_v3.cli as cli_mod

    real_build = cli_mod._build_ctx

    def spy_build(**kw):
        captured.update(kw)
        return real_build(**kw)

    monkeypatch.setattr(cli_mod.step0_invoices, "run_and_publish", fake_run_and_publish)
    monkeypatch.setattr(cli_mod, "_build_ctx", spy_build)

    result = runner.invoke(app, ["run", "--no-upload"])
    assert result.exit_code == 0, result.stdout
    assert captured["fleet"] == Fleet.All
    assert captured["agency"] == Agency.All
    assert captured["period"] == Period.Week


def test_custom_period_requires_start_and_end():
    result = runner.invoke(app, ["run", "--period", "Custom", "--no-upload"])
    assert result.exit_code != 0
    assert "Custom" in result.stdout or "Custom" in (result.stderr or "")


# ---------------------------------------------------------------------------
# resolve_window
# ---------------------------------------------------------------------------

def test_resolve_week_returns_prior_iso_week():
    # 2026-05-21 is a Thursday. Prior week = 2026-05-11 (Mon) .. 2026-05-17 (Sun).
    s, e = resolve_window(Period.Week, None, None, today=date(2026, 5, 21))
    assert s == date(2026, 5, 11)
    assert e == date(2026, 5, 17)


def test_resolve_mtd_first_of_month_to_today():
    s, e = resolve_window(Period.MTD, None, None, today=date(2026, 5, 21))
    assert s == date(2026, 5, 1)
    assert e == date(2026, 5, 21)


def test_resolve_lifetime_returns_none_none():
    s, e = resolve_window(Period.Lifetime, None, None, today=date(2026, 5, 21))
    assert s is None and e is None


# ---------------------------------------------------------------------------
# Filename builder (Prompt 3 expands this; Prompt 2 needs the basics)
# ---------------------------------------------------------------------------

def test_filename_mtd_format():
    ctx = RunContext(
        fleet=Fleet.Wahu, agency=Agency.TSAC, period=Period.MTD,
        start=date(2026, 5, 1), end=date(2026, 5, 21),
    )
    assert build_filename("rider_outstanding", ctx) == "rider_outstanding_Wahu_TSAC_mtd202605.xlsx"


def test_filename_week_format():
    ctx = RunContext(
        fleet=Fleet.All, agency=Agency.All, period=Period.Week,
        start=date(2026, 5, 11), end=date(2026, 5, 17),
    )
    assert build_filename("rider_payout_Wahu", ctx) == "rider_payout_Wahu_All_All_wk20.xlsx"


def test_filename_custom_format():
    ctx = RunContext(
        fleet=Fleet.TSA, agency=Agency.Hortta, period=Period.Custom,
        start=date(2026, 5, 1), end=date(2026, 5, 20),
    )
    assert build_filename("matched_payments", ctx) == "matched_payments_TSA_Hortta_20260501-20260520.xlsx"


def test_filename_lifetime_format():
    ctx = RunContext(fleet=Fleet.Wahu, agency=Agency.All, period=Period.Lifetime)
    assert build_filename("rider_outstanding", ctx) == "rider_outstanding_Wahu_All_lifetime.xlsx"


# ---------------------------------------------------------------------------
# Phone normalisation (used in Prompt 5, defined now)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("+233244123456", "244123456"),
    ("0244123456", "244123456"),
    ("00233244123456", "244123456"),
    ("233244123456", "244123456"),
    ("244 123 456", "244123456"),
    (" 244-123-456 ", "244123456"),
    ("", ""),
    (None, ""),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected
