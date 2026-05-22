"""Prompt 3 acceptance: filename + drive_target for all 13 artifacts, plus
_v{n} versioning behaviour and singleton bypass."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from api.integrations.google_drive import DriveFile
from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.util import artifacts as artifact_registry
from collections_v3.util.drive_writer import (
    FOLDER_MIME, next_versioned_filename, upload_artifact,
)
from collections_v3.util.paths import build_filename, drive_target


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _ctx(**overrides) -> RunContext:
    base = dict(
        fleet=Fleet.All, agency=Agency.All, period=Period.Week,
        start=date(2026, 5, 11), end=date(2026, 5, 17),
    )
    base.update(overrides)
    return RunContext(**base)


class FakeClient:
    """Minimal stand-in for DriveClient — only the methods drive_writer uses."""

    def __init__(self, *, existing_names: set[str] | None = None):
        self._existing = existing_names or set()
        self.uploaded: list[dict] = []
        self.created_folders: list[tuple[str, str]] = []  # (parent_id, name)
        self._folder_id_counter = 1000

    # list_folder(parent_id, name_contains=...) -> [DriveFile]
    def list_folder(self, folder_id, *, name_contains=None):
        return [
            DriveFile(id=f"file-{i}", name=name, mime_type="",
                      modified_time="2026-05-21T00:00:00Z", size_bytes=0)
            for i, name in enumerate(self._existing)
            if (name_contains is None or name_contains.lower() in name.lower())
        ]

    def upload_file(self, *, folder_id, filename, data, mime_type):
        self.uploaded.append(
            dict(folder_id=folder_id, filename=filename, size=len(data), mime=mime_type)
        )
        return dict(id=f"new-{filename}", name=filename, webViewLink=f"http://drive/{filename}")

    # Used by drive_writer for find-or-create folders. We don't simulate
    # nested-folder discovery here; tests that exercise ensure_subfolder
    # pass a mock implementation through monkeypatch.
    class _Service:
        def files(self):
            return self
        def create(self, **kw):
            return self
        def execute(self):
            return dict(id="folder-id", name="folder")
    _service = _Service()


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------

def test_registry_has_all_13_artifacts():
    assert len(artifact_registry.REGISTRY) == 13
    expected = {
        "billed_invoices_by_fleet_agency", "matched_payments", "suspense",
        "rider_outstanding", "rider_payout_Wahu", "rider_payout_TSA",
        "agency_performance", "run_summary", "rider_agency_history",
        "data_quality", "qb_invoices", "qb_payments", "qb_upload_log",
    }
    assert set(artifact_registry.REGISTRY) == expected


def test_registry_singletons_and_week_partitions():
    R = artifact_registry.REGISTRY
    assert R["rider_agency_history"].singleton is True
    assert R["qb_upload_log"].singleton is True
    # Nothing else is a singleton.
    others = [n for n, s in R.items() if s.singleton]
    assert sorted(others) == ["qb_upload_log", "rider_agency_history"]
    # qb_invoices + qb_payments are week-partitioned.
    assert R["qb_invoices"].week_partition is True
    assert R["qb_payments"].week_partition is True
    # Nothing else is.
    wp = [n for n, s in R.items() if s.week_partition]
    assert sorted(wp) == ["qb_invoices", "qb_payments"]


# ---------------------------------------------------------------------------
# Filename builder: all 13 × representative ctxs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("artifact,fleet,agency,period_kw,expected", [
    # Week period -> wk20 (the prior ISO week for 2026-05-17 is W20).
    ("billed_invoices_by_fleet_agency", Fleet.All, Agency.All,
     dict(period=Period.Week, start=date(2026, 5, 11), end=date(2026, 5, 17)),
     "billed_invoices_by_fleet_agency_All_All_wk20.xlsx"),
    ("matched_payments", Fleet.Wahu, Agency.TSAC,
     dict(period=Period.MTD, start=date(2026, 5, 1), end=date(2026, 5, 21)),
     "matched_payments_Wahu_TSAC_mtd202605.xlsx"),
    ("suspense", Fleet.Wahu, Agency.Hortta,
     dict(period=Period.MTD, start=date(2026, 5, 1), end=date(2026, 5, 21)),
     "suspense_Wahu_Hortta_mtd202605.xlsx"),
    ("rider_outstanding", Fleet.TSA, Agency.TSAC,
     dict(period=Period.Custom, start=date(2026, 5, 1), end=date(2026, 5, 20)),
     "rider_outstanding_TSA_TSAC_20260501-20260520.xlsx"),
    ("rider_payout_Wahu", Fleet.Wahu, Agency.All,
     dict(period=Period.Week, start=date(2026, 5, 11), end=date(2026, 5, 17)),
     "rider_payout_Wahu_Wahu_All_wk20.xlsx"),
    ("rider_payout_TSA", Fleet.TSA, Agency.TSAC,
     dict(period=Period.Week, start=date(2026, 5, 11), end=date(2026, 5, 17)),
     "rider_payout_TSA_TSA_TSAC_wk20.xlsx"),
    ("agency_performance", Fleet.All, Agency.Hortta,
     dict(period=Period.MTD, start=date(2026, 5, 1), end=date(2026, 5, 21)),
     "agency_performance_All_Hortta_mtd202605.xlsx"),
    ("rider_agency_history", Fleet.All, Agency.All,
     dict(period=Period.Lifetime),
     "rider_agency_history_All_All_lifetime.xlsx"),
    ("data_quality", Fleet.All, Agency.All,
     dict(period=Period.Week, start=date(2026, 5, 11), end=date(2026, 5, 17)),
     "data_quality_All_All_wk20.xlsx"),
    ("qb_upload_log", Fleet.All, Agency.All,
     dict(period=Period.Lifetime),
     "qb_upload_log_All_All_lifetime.xlsx"),
])
def test_build_filename_single_ext(artifact, fleet, agency, period_kw, expected):
    ctx = _ctx(fleet=fleet, agency=agency, **period_kw)
    assert build_filename(artifact, ctx) == expected


@pytest.mark.parametrize("artifact,ext,expected", [
    ("run_summary", "md", "run_summary_All_All_wk20.md"),
    ("run_summary", "pdf", "run_summary_All_All_wk20.pdf"),
    ("qb_invoices", "iif", "qb_invoices_All_All_wk20.iif"),
    ("qb_invoices", "csv", "qb_invoices_All_All_wk20.csv"),
    ("qb_payments", "iif", "qb_payments_All_All_wk20.iif"),
    ("qb_payments", "csv", "qb_payments_All_All_wk20.csv"),
])
def test_build_filename_multi_ext(artifact, ext, expected):
    ctx = _ctx()
    assert build_filename(artifact, ctx, ext=ext) == expected


def test_build_filename_multi_ext_requires_ext():
    ctx = _ctx()
    with pytest.raises(ValueError, match="multiple extensions"):
        build_filename("run_summary", ctx)


def test_build_filename_rejects_unknown_ext():
    ctx = _ctx()
    with pytest.raises(ValueError, match="does not support ext"):
        build_filename("billed_invoices_by_fleet_agency", ctx, ext="pdf")


# ---------------------------------------------------------------------------
# Drive target subfolder
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("artifact,expected", [
    ("billed_invoices_by_fleet_agency", "Invoice Snapshots"),
    ("matched_payments", "Monthly Matched Payments"),
    ("suspense", "Monthly Matched Payments"),
    ("rider_outstanding", "Monthly Matched Payments"),
    ("rider_payout_Wahu", "Weekly Rider Payouts/Wahu"),
    ("rider_payout_TSA", "Weekly Rider Payouts/TSA"),
    ("agency_performance", "Agency Performance"),
    ("run_summary", "Weekly Rider Payouts"),
    ("rider_agency_history", "Monthly Matched Payments"),
    ("data_quality", "Weekly Rider Payouts"),
    ("qb_upload_log", "QuickBooks Exports"),
])
def test_drive_target_basic(artifact, expected):
    ctx = _ctx()
    assert drive_target(artifact, ctx) == expected


def test_drive_target_week_partition_for_qb():
    # end=2026-05-17 -> ISO week 2026-W20
    ctx = _ctx(period=Period.Week, start=date(2026, 5, 11), end=date(2026, 5, 17))
    assert drive_target("qb_invoices", ctx) == "QuickBooks Exports/2026-W20"
    assert drive_target("qb_payments", ctx) == "QuickBooks Exports/2026-W20"


# ---------------------------------------------------------------------------
# Versioning: _v{n} collision behavior
# ---------------------------------------------------------------------------

def test_no_collision_returns_base_name():
    client = FakeClient(existing_names={"other_file.xlsx"})
    out = next_versioned_filename("folder-1", "matched_payments_All_All_wk20.xlsx", client=client)
    assert out == "matched_payments_All_All_wk20.xlsx"


def test_first_collision_returns_v2():
    base = "matched_payments_All_All_wk20.xlsx"
    client = FakeClient(existing_names={base})
    out = next_versioned_filename("folder-1", base, client=client)
    assert out == "matched_payments_All_All_wk20_v2.xlsx"


def test_second_collision_returns_v3():
    base = "matched_payments_All_All_wk20.xlsx"
    existing = {base, "matched_payments_All_All_wk20_v2.xlsx"}
    client = FakeClient(existing_names=existing)
    out = next_versioned_filename("folder-1", base, client=client)
    assert out == "matched_payments_All_All_wk20_v3.xlsx"


def test_versioning_only_considers_same_extension():
    base = "data_quality_All_All_wk20.xlsx"
    # A pdf with a similar stem must NOT bump the xlsx counter.
    existing = {"data_quality_All_All_wk20_v7.pdf"}
    client = FakeClient(existing_names=existing)
    out = next_versioned_filename("folder-1", base, client=client)
    assert out == base  # no .xlsx collision


# ---------------------------------------------------------------------------
# Singleton bypass
# ---------------------------------------------------------------------------

def test_upload_artifact_rejects_singletons(monkeypatch):
    ctx = _ctx(period=Period.Lifetime)
    # ensure_subfolder must not be reached.
    monkeypatch.setattr(
        "collections_v3.util.drive_writer.ensure_subfolder",
        lambda *a, **kw: pytest.fail("ensure_subfolder must not run for singletons"),
    )
    with pytest.raises(ValueError, match="singleton"):
        upload_artifact("rider_agency_history", ctx, b"x", client=FakeClient())
    with pytest.raises(ValueError, match="singleton"):
        upload_artifact("qb_upload_log", ctx, b"x", client=FakeClient())


# ---------------------------------------------------------------------------
# End-to-end upload (mocked Drive) — produces _v2 on second call
# ---------------------------------------------------------------------------

def test_upload_artifact_produces_v2_on_second_call(monkeypatch):
    ctx = _ctx(period=Period.MTD, start=date(2026, 5, 1), end=date(2026, 5, 21))
    base = "matched_payments_All_All_mtd202605.xlsx"

    # State shared across the two uploads.
    state = {"existing": set()}

    client = FakeClient()

    def fake_list(folder_id, *, name_contains=None):
        return [
            DriveFile(id=f"f-{i}", name=name, mime_type="",
                      modified_time="x", size_bytes=0)
            for i, name in enumerate(state["existing"])
            if (name_contains is None or name_contains.lower() in name.lower())
        ]

    def fake_upload(*, folder_id, filename, data, mime_type):
        state["existing"].add(filename)
        return dict(id=f"new-{filename}", name=filename, webViewLink=f"link-{filename}")

    client.list_folder = fake_list  # type: ignore[assignment]
    client.upload_file = fake_upload  # type: ignore[assignment]

    monkeypatch.setattr(
        "collections_v3.util.drive_writer.ensure_subfolder",
        lambda parent_id, path, **kw: "target-folder-id",
    )

    first = upload_artifact("matched_payments", ctx, b"v1-bytes", client=client)
    second = upload_artifact("matched_payments", ctx, b"v2-bytes", client=client)

    assert first["name"] == base
    assert second["name"] == f"matched_payments_All_All_mtd202605_v2.xlsx"
