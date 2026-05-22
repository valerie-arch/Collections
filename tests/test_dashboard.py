"""Prompt 10 acceptance: dashboard endpoints + activity log.

Spec acceptance:
  1. All endpoints honour the same fleet/agency/period filter triple as
     the CLI.
  2. Engagement % = engaged_today / active_customer_base, rounded to 1dp.
  3. A `payment_received` row for today is counted in `collected_today`
     for that agency.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from collections_v3.dashboard import activity_log, readers
from collections_v3.dashboard.activity_log import log_activity


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Redirect both the activity log and artifacts/ to tmp paths so tests
    don't read or write production-ish files."""
    log_path = tmp_path / "agency_activity.json"
    monkeypatch.setattr(activity_log, "STORE_PATH", log_path)
    monkeypatch.setattr(readers, "ARTIFACTS_DIR", tmp_path)
    return tmp_path


def _seed_outstanding(artifacts_dir: Path) -> Path:
    """Write a tiny rider_outstanding XLSX so readers find some riders."""
    df = pd.DataFrame([
        dict(rider_id="R1", rider_name="Felix Adom", fleet="Wahu", agency="TSAC",
             opening_outstanding=400.0, applied_this_run=0.0,
             prior_credit=0.0, prior_credit_consumed=0.0, new_credit_this_run=0.0,
             closing_outstanding=400.0, closing_credit=0.0, open_invoice_count=1),
        dict(rider_id="R2", rider_name="Eric Aheto", fleet="TSA", agency="TSAC",
             opening_outstanding=300.0, applied_this_run=0.0,
             prior_credit=0.0, prior_credit_consumed=0.0, new_credit_this_run=0.0,
             closing_outstanding=300.0, closing_credit=0.0, open_invoice_count=1),
        dict(rider_id="R3", rider_name="Frederick Barths", fleet="Wahu", agency="Hortta",
             opening_outstanding=200.0, applied_this_run=0.0,
             prior_credit=0.0, prior_credit_consumed=0.0, new_credit_this_run=0.0,
             closing_outstanding=200.0, closing_credit=0.0, open_invoice_count=1),
        dict(rider_id="R4", rider_name="Mystery", fleet="Wahu", agency="Unassigned",
             opening_outstanding=100.0, applied_this_run=0.0,
             prior_credit=0.0, prior_credit_consumed=0.0, new_credit_this_run=0.0,
             closing_outstanding=100.0, closing_credit=0.0, open_invoice_count=1),
    ])
    p = artifacts_dir / "rider_outstanding_All_All_wk20.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="rider_outstanding", index=False)
    return p


def _client() -> TestClient:
    # Import inside so module-level FastAPI app construction doesn't run
    # at collection time on machines without all DB env vars set.
    from api.main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Acceptance #1: every endpoint honours the filter triple
# ---------------------------------------------------------------------------

def test_acceptance_1_all_endpoints_accept_filter_triple(isolated_paths):
    _seed_outstanding(isolated_paths)
    client = _client()
    today = date.today().isoformat()

    # Common filter combo to exercise: --fleet TSA --agency TSAC.
    common = {"fleet": "TSA", "agency": "TSAC"}

    for path, extras in [
        ("/dashboard/overview",     {"date": today}),
        ("/dashboard/activities",   {"date": today}),
        ("/dashboard/performance",  {"period": "MTD"}),
        ("/dashboard/suspense",     {}),
        ("/dashboard/riders",       {"q": ""}),
    ]:
        params = {**common, **extras}
        r = client.get(path, params=params)
        assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text}"
        body = r.json()
        # Filters echoed back so the consumer can confirm what was applied.
        assert body["filters"]["fleet"] == "TSA"
        assert body["filters"]["agency"] == "TSAC"


# ---------------------------------------------------------------------------
# Acceptance #2: engagement % = engaged / base, 1dp
# ---------------------------------------------------------------------------

def test_acceptance_2_engagement_pct_formula(isolated_paths):
    """4 riders in base; 1 unique engaged today across multiple actions -> 25.0%."""
    _seed_outstanding(isolated_paths)
    today_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Multiple actions, but only ONE unique rider.
    for _ in range(3):
        log_activity(agency="TSAC", collector_id="C-1", rider_id="R1",
                     action_type="call_placed", outcome="connected",
                     timestamp=today_iso)

    client = _client()
    body = client.get(
        "/dashboard/overview", params={"date": date.today().isoformat()}
    ).json()
    assert body["active_customer_base"]["total"] == 4
    assert body["engagement"]["engaged_today"] == 1
    assert body["engagement"]["engagement_pct"] == 25.0   # 1/4 = 25.0%, 1dp


def test_engagement_pct_handles_zero_base(isolated_paths):
    # No outstanding artifact at all -> base = 0; pct must not divide by zero.
    client = _client()
    body = client.get(
        "/dashboard/overview", params={"date": date.today().isoformat()}
    ).json()
    assert body["active_customer_base"]["total"] == 0
    assert body["engagement"]["engagement_pct"] == 0.0


# ---------------------------------------------------------------------------
# Acceptance #3: payment_received today counted in collected_today by agency
# ---------------------------------------------------------------------------

def test_acceptance_3_payment_received_counted_in_collected_today(isolated_paths):
    _seed_outstanding(isolated_paths)
    today_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Two payment_received rows for TSAC + one other action that must not count.
    log_activity(agency="TSAC", collector_id="C-1", rider_id="R1",
                 action_type="payment_received", amount_ghs=150.0,
                 timestamp=today_iso)
    log_activity(agency="TSAC", collector_id="C-2", rider_id="R2",
                 action_type="payment_received", amount_ghs=275.50,
                 timestamp=today_iso)
    # Non-payment action: should NOT contribute to collected.
    log_activity(agency="TSAC", collector_id="C-1", rider_id="R3",
                 action_type="call_placed", outcome="connected",
                 timestamp=today_iso)
    # Different agency: filtered out when agency=TSAC.
    log_activity(agency="Hortta", collector_id="C-3", rider_id="R3",
                 action_type="payment_received", amount_ghs=999.0,
                 timestamp=today_iso)

    client = _client()
    body = client.get(
        "/dashboard/overview",
        params={"agency": "TSAC", "date": date.today().isoformat()},
    ).json()
    assert body["collected"]["today_ghs"] == 425.5

    # And the unfiltered (agency=All) view sees everyone.
    body_all = client.get(
        "/dashboard/overview", params={"date": date.today().isoformat()},
    ).json()
    assert body_all["collected"]["today_ghs"] == 425.5 + 999.0


# ---------------------------------------------------------------------------
# Activity log persistence + validation
# ---------------------------------------------------------------------------

def test_log_activity_rejects_unknown_action_type(isolated_paths):
    with pytest.raises(ValueError, match="action_type"):
        log_activity(agency="TSAC", collector_id="C-1", rider_id="R1",
                     action_type="not_a_real_thing")


def test_post_dashboard_activities_persists_one_row(isolated_paths):
    client = _client()
    r = client.post("/dashboard/activities", json={
        "agency": "TSAC", "collector_id": "C-1", "rider_id": "R1",
        "action_type": "in_person_visit", "outcome": "met", "notes": "all good",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["action_type"] == "in_person_visit"
    assert body["outcome"] == "met"

    # The audit endpoint reflects it.
    audit = client.get("/dashboard/activities/raw").json()
    assert audit["count"] == 1


def test_riders_endpoint_supports_q_search(isolated_paths):
    _seed_outstanding(isolated_paths)
    client = _client()
    r = client.get("/dashboard/riders", params={"q": "Felix"})
    body = r.json()
    assert body["count"] == 1
    assert body["rows"][0]["rider_name"] == "Felix Adom"


def test_suspense_endpoint_returns_aging_buckets_when_present(isolated_paths):
    df = pd.DataFrame([
        dict(txn_id="T1", channel="bank", date="2026-05-14", amount=200.0,
             sender_name="x", sender_phone_canonical="", reference="",
             narration="", source_file="s.csv",
             first_seen_at="2026-05-10", days_in_suspense=4, aging_bucket="0_7",
             candidate_1="", candidate_2="", candidate_3="",
             assigned_rider_id="", notes=""),
    ])
    p = isolated_paths / "suspense_All_All_wk20.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as xw:
        df.to_excel(xw, index=False)
    client = _client()
    body = client.get("/dashboard/suspense").json()
    assert body["total_pending"] == 1
    assert body["buckets"]["0_7"] == 1
