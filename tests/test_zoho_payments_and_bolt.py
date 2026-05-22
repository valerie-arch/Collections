"""Acceptance tests for the new Zoho-payments and Bolt-earnings loaders."""

from __future__ import annotations

import io
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from api.integrations.google_drive import DriveFile
from collections_v3.io_ import bolt_earnings, zoho_payments
from collections_v3.io_.bolt_earnings import (
    _normalize_bolt_sheet, _parse_filename_date, _payout_monday_for,
    _week_window_from_filename,
)
from collections_v3.io_.drive_resolver import ResolvedFile
from collections_v3.io_.zoho_payments import _normalize_one
from collections_v3.schemas import Agency, Fleet, Period, RunContext


# ---------------------------------------------------------------------------
# Bolt: date / week-window math
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Bolt Food Payout Workings -  [ 18/05/2026]", date(2026, 5, 18)),
    ("Bolt Food Payout Workings -  [ 04/05/2026]", date(2026, 5, 4)),
    ("Bolt Food Payout Workings -  [ 11/05/2026]", date(2026, 5, 11)),
    ("Bolt Food Payout Workings -  [1/1/2026]", date(2026, 1, 1)),
    ("Some Other Name", None),
])
def test_parse_filename_date(name, expected):
    assert _parse_filename_date(name) == expected


def test_payout_monday_is_day_after_sunday_end():
    # Sun May 17 2026 -> payout Mon May 18
    assert _payout_monday_for(date(2026, 5, 17)) == date(2026, 5, 18)


def test_week_window_from_filename_inverts_payout_monday():
    # filename 18/05/2026 reports Mon May 11 .. Sun May 17
    start, end = _week_window_from_filename(date(2026, 5, 18))
    assert (start, end) == (date(2026, 5, 11), date(2026, 5, 17))


# ---------------------------------------------------------------------------
# Bolt: sheet normalizer (the actual column-alias logic, in isolation)
# ---------------------------------------------------------------------------

def _bolt_sheet_csv() -> bytes:
    # Real exports come through Drive's CSV export which quotes any number
    # that contains a comma — so tests use unquoted numbers without commas
    # to keep the parser path deterministic.
    rows = [
        "#,Customer Name,TSA ?,Amount Owing,Current Debt,Bolt Payout,5%,Payout After Commission,Approved Deduction For Overdue Invoice,Net Payout To Rider,Momo Account,Status,Fee Incurred,Comments",
        "1,Eric Aheto,0,0,0,673.00,33.65,639.34,0,639.34,245326779,Paid,,",
        "2,Stephen Sackey,420,420,500,1448.90,72.44,1376.45,420,956.45,233544707547,Paid,66,Processed - Hubtel",
        "3,Bismark Kojo Okor,419.2,419.2,401.7,200.00,20.09,381.64,381.64,0.00,546036960,No Payout,,",
    ]
    return "\n".join(rows).encode("utf-8")


def test_normalize_bolt_sheet_extracts_canonical_columns():
    rf = ResolvedFile(
        drive_file=None,
        content=_bolt_sheet_csv(),
        effective_name="Bolt Food Payout Workings -  [ 18/05/2026].csv",
        effective_mime="text/csv",
    )
    df = _normalize_bolt_sheet(rf, filename_date=date(2026, 5, 18))
    assert len(df) == 3
    assert set(df["rider_name"]) == {"Eric Aheto", "Stephen Sackey", "Bismark Kojo Okor"}
    # Week window: Mon May 11 .. Sun May 17
    assert (df["week_start"].iloc[0], df["week_end"].iloc[0]) == (date(2026, 5, 11), date(2026, 5, 17))
    # Bolt Payout was parsed correctly (commas stripped).
    by_name = dict(zip(df["rider_name"], df["bolt_payout"]))
    assert by_name["Eric Aheto"] == 673.0
    assert by_name["Stephen Sackey"] == 1448.90
    # MoMo account preserved exactly.
    by_momo = dict(zip(df["rider_name"], df["momo_account"]))
    assert by_momo["Eric Aheto"] == "245326779"


def test_normalize_bolt_sheet_drops_header_leftovers():
    rows = [
        "#,Customer Name,Bolt Payout",
        "1,Eric Aheto,500",
        "2,Customer Name,0",  # header repeated mid-data — should be dropped
        "3,Total,12345",      # totals row — drop
        ",,",                  # blank — drop
    ]
    rf = ResolvedFile(
        drive_file=None,
        content="\n".join(rows).encode("utf-8"),
        effective_name="x.csv", effective_mime="text/csv",
    )
    df = _normalize_bolt_sheet(rf, filename_date=date(2026, 5, 18))
    assert list(df["rider_name"]) == ["Eric Aheto"]


def test_normalize_bolt_sheet_missing_required_returns_empty(caplog):
    rows = ["Foo,Bar", "1,2"]
    rf = ResolvedFile(
        drive_file=None,
        content="\n".join(rows).encode("utf-8"),
        effective_name="x.csv", effective_mime="text/csv",
    )
    df = _normalize_bolt_sheet(rf, filename_date=date(2026, 5, 18))
    assert df.empty


# ---------------------------------------------------------------------------
# Bolt: end-to-end with mocked Drive
# ---------------------------------------------------------------------------

class _BoltFakeClient:
    """Minimal Drive client for bolt_earnings.* tests.

    Tree:
        root
          ├── '05/2026 - May 2026'  (folder)
          │     └── 'Bolt Food Payout Workings -  [ 18/05/2026]'  (Sheet)
          └── '04/2026 - April 2026'  (folder)
                └── 'Bolt Food Payout Workings -  [ 27/04/2026]'  (Sheet)
    """

    ROOT = "root-folder"
    MAY_FOLDER = "may-folder"
    APR_FOLDER = "apr-folder"
    MAY_SHEET = "may-sheet"
    APR_SHEET = "apr-sheet"

    def list_folder(self, folder_id, *, name_contains=None):
        if folder_id == self.ROOT:
            return [
                DriveFile(id=self.MAY_FOLDER, name="05/2026 - May 2026",
                          mime_type=bolt_earnings.FOLDER_MIME,
                          modified_time="x", size_bytes=0),
                DriveFile(id=self.APR_FOLDER, name="04/2026 - April 2026",
                          mime_type=bolt_earnings.FOLDER_MIME,
                          modified_time="x", size_bytes=0),
            ]
        if folder_id == self.MAY_FOLDER:
            return [DriveFile(
                id=self.MAY_SHEET,
                name="Bolt Food Payout Workings -  [ 18/05/2026]",
                mime_type="application/vnd.google-apps.spreadsheet",
                modified_time="x", size_bytes=0,
            )]
        if folder_id == self.APR_FOLDER:
            return [DriveFile(
                id=self.APR_SHEET,
                name="Bolt Food Payout Workings -  [ 27/04/2026]",
                mime_type="application/vnd.google-apps.spreadsheet",
                modified_time="x", size_bytes=0,
            )]
        return []

    def download_file(self, file_id, *, export_mime=None):
        return _bolt_sheet_csv()


def test_load_bolt_for_week_picks_correct_sheet(monkeypatch):
    client = _BoltFakeClient()
    monkeypatch.setattr(
        "collections_v3.io_.bolt_earnings.settings.BOLT_DRIVE_FOLDER_ID",
        client.ROOT,
    )
    ctx = RunContext(
        fleet=Fleet.All, agency=Agency.All, period=Period.Week,
        start=date(2026, 5, 11), end=date(2026, 5, 17),
    )
    df = bolt_earnings.load_bolt_for_week(ctx, client=client)
    assert not df.empty
    assert (df["week_start"].iloc[0], df["week_end"].iloc[0]) == (date(2026, 5, 11), date(2026, 5, 17))


def test_load_bolt_latest_when_no_ctx(monkeypatch):
    client = _BoltFakeClient()
    monkeypatch.setattr(
        "collections_v3.io_.bolt_earnings.settings.BOLT_DRIVE_FOLDER_ID",
        client.ROOT,
    )
    df = bolt_earnings.load_bolt_earnings(client=client)
    # Latest sheet: 18/05/2026 -> Mon May 11 .. Sun May 17
    assert (df["week_start"].iloc[0], df["week_end"].iloc[0]) == (date(2026, 5, 11), date(2026, 5, 17))


# ---------------------------------------------------------------------------
# Zoho payments normalizer
# ---------------------------------------------------------------------------

def _zoho_payments_csv() -> bytes:
    rows = [
        "payment_id,payment_number,invoice_number,date,payment_mode,amount,unused_amount,reference_number,customer_id,customer_name,company_name,outstanding_receivable_amount",
        "4344318000006724201,25584,,2026-04-30,Vodafone,140.00,0.00,0000012872595969,4344318000006336175,Emmanuel Tackie Bentum,,70.00",
        "4344318000006724412,25593,,2026-04-30,MTN,423.00,0.00,80328091813,4344318000005520241,Emmanuel Ganyo,TSA,1860.00",
    ]
    return "\n".join(rows).encode("utf-8")


def test_zoho_payments_normalizer_extracts_canonical_columns():
    rf = ResolvedFile(
        drive_file=None, content=_zoho_payments_csv(),
        effective_name="Payments Received (22).csv", effective_mime="text/csv",
    )
    df = _normalize_one(rf)
    assert len(df) == 2
    row = df[df["payment_id"] == "4344318000006724412"].iloc[0]
    assert row["amount"] == 423.0
    assert row["reference_number"] == "80328091813"
    assert row["customer_name"] == "Emmanuel Ganyo"
    assert row["company_name"] == "TSA"
    assert row["payment_mode"] == "MTN"


def test_zoho_payments_normalizer_raises_on_missing_required():
    rows = ["payment_number,date", "1,2026-04-30"]
    rf = ResolvedFile(
        drive_file=None,
        content="\n".join(rows).encode("utf-8"),
        effective_name="bad.csv", effective_mime="text/csv",
    )
    with pytest.raises(ValueError, match="missing required columns"):
        _normalize_one(rf)
