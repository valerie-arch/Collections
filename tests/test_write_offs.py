"""Tests for the write-off ledger loader.

Covers: schema conformance, validation drops, recovery FK integrity,
and the net_charge_off window helper. Uses the bundled local template
so no Drive credentials are needed.
"""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook

from collections_v3.io_ import write_offs as wo_mod
from collections_v3.io_.write_offs import (
    WRITE_OFFS_COLUMNS,
    RECOVERIES_COLUMNS,
    load_write_off_ledger,
    net_charge_off,
)


def _make_xlsx_bytes(write_off_rows, recovery_rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "WriteOffs"
    ws.append(WRITE_OFFS_COLUMNS)
    for r in write_off_rows:
        ws.append([r.get(c, "") for c in WRITE_OFFS_COLUMNS])
    ws2 = wb.create_sheet("Recoveries")
    ws2.append(RECOVERIES_COLUMNS)
    for r in recovery_rows:
        ws2.append([r.get(c, "") for c in RECOVERIES_COLUMNS])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_local_template_loads_with_expected_columns():
    """Bundled XLSX template parses cleanly and produces canonical columns."""
    ledger = load_write_off_ledger()
    assert list(ledger.write_offs.columns) == WRITE_OFFS_COLUMNS
    assert list(ledger.recoveries.columns) == RECOVERIES_COLUMNS
    assert ledger.source.startswith("local:")
    # Template has one of each.
    assert len(ledger.write_offs) >= 1
    assert len(ledger.recoveries) >= 1


def test_drops_rows_missing_required_fields(monkeypatch):
    good_wo = {
        "write_off_id": "WO-1", "rider_id": "R1", "rider_name": "Ama",
        "write_off_date": "2026-04-01", "amount_ghs": 500.0,
        "reason": "vehicle_returned", "approved_by": "V", "notes": "",
    }
    bad_wo_no_id = {**good_wo, "write_off_id": ""}
    bad_wo_zero_amount = {**good_wo, "write_off_id": "WO-2", "amount_ghs": 0}
    bad_wo_bad_date = {**good_wo, "write_off_id": "WO-3", "write_off_date": "not a date"}

    xlsx = _make_xlsx_bytes(
        [good_wo, bad_wo_no_id, bad_wo_zero_amount, bad_wo_bad_date], [],
    )
    monkeypatch.setattr(wo_mod, "_resolve_bytes", lambda **_: (xlsx, "test"))

    ledger = load_write_off_ledger()
    assert len(ledger.write_offs) == 1
    assert ledger.write_offs.iloc[0]["write_off_id"] == "WO-1"
    assert ledger.dropped_write_off_rows == 3


def test_recovery_referencing_unknown_write_off_is_dropped(monkeypatch):
    good_wo = {
        "write_off_id": "WO-1", "rider_id": "R1", "rider_name": "Ama",
        "write_off_date": "2026-04-01", "amount_ghs": 500.0,
        "reason": "long_term_default", "approved_by": "V", "notes": "",
    }
    good_rc = {
        "recovery_id": "RC-1", "write_off_id": "WO-1",
        "recovery_date": "2026-05-01", "amount_ghs": 120.0,
        "source": "mtn", "source_txn_id": "T123", "notes": "",
    }
    orphan_rc = {**good_rc, "recovery_id": "RC-2", "write_off_id": "WO-DOES-NOT-EXIST"}

    xlsx = _make_xlsx_bytes([good_wo], [good_rc, orphan_rc])
    monkeypatch.setattr(wo_mod, "_resolve_bytes", lambda **_: (xlsx, "test"))

    ledger = load_write_off_ledger()
    assert len(ledger.recoveries) == 1
    assert ledger.recoveries.iloc[0]["recovery_id"] == "RC-1"
    assert ledger.dropped_recovery_rows == 1


def test_unknown_reason_coerced_to_other(monkeypatch):
    wo = {
        "write_off_id": "WO-1", "rider_id": "R1", "rider_name": "Ama",
        "write_off_date": "2026-04-01", "amount_ghs": 500.0,
        "reason": "alien_abduction", "approved_by": "V", "notes": "",
    }
    xlsx = _make_xlsx_bytes([wo], [])
    monkeypatch.setattr(wo_mod, "_resolve_bytes", lambda **_: (xlsx, "test"))
    ledger = load_write_off_ledger()
    assert ledger.write_offs.iloc[0]["reason"] == "other"


def test_net_charge_off_windowed(monkeypatch):
    """Charge-offs counted by write_off_date, recoveries by recovery_date."""
    wos = [
        {"write_off_id": "WO-1", "rider_id": "R1", "rider_name": "A",
         "write_off_date": "2026-03-15", "amount_ghs": 1000.0,
         "reason": "long_term_default", "approved_by": "V", "notes": ""},
        {"write_off_id": "WO-2", "rider_id": "R2", "rider_name": "B",
         "write_off_date": "2026-04-20", "amount_ghs": 500.0,
         "reason": "vehicle_returned", "approved_by": "V", "notes": ""},
        # Outside window (after end)
        {"write_off_id": "WO-3", "rider_id": "R3", "rider_name": "C",
         "write_off_date": "2026-06-01", "amount_ghs": 800.0,
         "reason": "other", "approved_by": "V", "notes": ""},
    ]
    rcs = [
        # Recovery for WO-1 inside the window — counts.
        {"recovery_id": "RC-1", "write_off_id": "WO-1",
         "recovery_date": "2026-04-25", "amount_ghs": 300.0,
         "source": "mtn", "source_txn_id": "", "notes": ""},
        # Recovery for WO-2 outside window — does NOT count.
        {"recovery_id": "RC-2", "write_off_id": "WO-2",
         "recovery_date": "2026-07-01", "amount_ghs": 200.0,
         "source": "bank", "source_txn_id": "", "notes": ""},
    ]
    xlsx = _make_xlsx_bytes(wos, rcs)
    monkeypatch.setattr(wo_mod, "_resolve_bytes", lambda **_: (xlsx, "test"))

    ledger = load_write_off_ledger()
    out = net_charge_off(ledger, start=date(2026, 3, 1), end=date(2026, 5, 31))
    assert out["charge_offs_ghs"] == 1500.0     # WO-1 + WO-2
    assert out["recoveries_ghs"] == 300.0       # only RC-1
    assert out["net_charge_off_ghs"] == 1200.0


def test_empty_sheets_yield_empty_frames(monkeypatch):
    xlsx = _make_xlsx_bytes([], [])
    monkeypatch.setattr(wo_mod, "_resolve_bytes", lambda **_: (xlsx, "test"))
    ledger = load_write_off_ledger()
    assert ledger.write_offs.empty
    assert ledger.recoveries.empty
    assert list(ledger.write_offs.columns) == WRITE_OFFS_COLUMNS
    assert list(ledger.recoveries.columns) == RECOVERIES_COLUMNS
