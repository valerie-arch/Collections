"""Tests for the 10-KPI Portfolio Dashboard compute layer.

Covers: window resolution, the eight derivable KPIs, and the blocked
placeholders. Uses synthetic InvoiceRow fixtures so the tests don't
depend on any sample CSV being on disk.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from api.agents.collections_report.engine import InvoiceRow
from api.agents.dashboard_v2.compute import (
    blocked_cure_rate, blocked_roll_rates,
    compute_active_payer_rate, compute_aging, compute_lifetime_efficiency,
    compute_monthly_collections, compute_mrr, compute_net_charge_off,
    compute_on_time_rate, compute_recovery_on_churned, resolve_window,
)
from collections_v3.io_.write_offs import load_write_off_ledger


def _inv(
    cid: str, name: str, idate: date, total: float, balance: float,
    last_payment_date=None, due_date=None, invoice_id="auto",
) -> InvoiceRow:
    return InvoiceRow(
        invoice_id=invoice_id if invoice_id != "auto" else f"INV-{cid}-{idate.isoformat()}",
        customer_id=cid,
        customer_name=name,
        invoice_date=idate,
        due_date=due_date,
        status="overdue" if balance > 0 else "paid",
        total=Decimal(str(total)),
        balance=Decimal(str(balance)),
        last_payment_date=last_payment_date,
        is_completed=False,
        is_churned=False,
        is_tsa=False,
    )


# ---------------------------------------------------------------------------
# resolve_window
# ---------------------------------------------------------------------------

def test_resolve_window_monthly_returns_calendar_month():
    w = resolve_window("monthly", date(2026, 5, 23))
    assert w.start == date(2026, 5, 1)
    assert w.end == date(2026, 5, 31)
    assert w.label == "May 2026"


def test_resolve_window_weekly_returns_iso_week():
    # Sunday May 24 2026 → ISO week is Mon May 18 – Sun May 24.
    w = resolve_window("weekly", date(2026, 5, 24))
    assert w.start == date(2026, 5, 18)
    assert w.end == date(2026, 5, 24)


def test_resolve_window_lifetime_spans_history():
    w = resolve_window("lifetime", date(2026, 5, 24))
    assert w.start == date(2000, 1, 1)
    assert w.end == date(2026, 5, 24)
    assert w.label == "Lifetime"


def test_resolve_window_custom_uses_given_dates():
    w = resolve_window(
        "custom", date(2026, 5, 24),
        start=date(2026, 3, 1), end=date(2026, 4, 30),
    )
    assert (w.start, w.end) == (date(2026, 3, 1), date(2026, 4, 30))


# ---------------------------------------------------------------------------
# KPI 1 — Active Payer Rate
# ---------------------------------------------------------------------------

def test_active_payer_rate_segments_by_tenure_and_counts_recent_payers():
    """Active = open balance OR an invoice in the last 30 days. Tenure =
    MIN(invoice_date) per rider. To keep each rider 'active' while varying
    tenure, we attach both an old (tenure-defining) and a recent (activity-
    defining) invoice per rider."""
    as_of = date(2026, 5, 24)
    invs = [
        # R1: tenure 10 months, paid recently, no balance — 6-12m, paying.
        _inv("R1", "Alpha", date(2025, 7, 24), 100, 0,
             last_payment_date=date(2025, 8, 1), invoice_id="R1-old"),
        _inv("R1", "Alpha", date(2026, 5, 1), 100, 0,
             last_payment_date=date(2026, 5, 10), invoice_id="R1-new"),
        # R2: brand-new rider with a recent invoice — 0-3m, paying.
        _inv("R2", "Beta", date(2026, 4, 5), 100, 0,
             last_payment_date=date(2026, 5, 23)),
        # R3: brand-new rider with an open balance, no recent payment — 0-3m, NOT paying.
        _inv("R3", "Gamma", date(2026, 5, 1), 100, 100),
        # R4: tenure 18 months, recent invoice + payment — 12m+, paying.
        _inv("R4", "Delta", date(2024, 11, 1), 100, 0,
             last_payment_date=date(2024, 11, 15), invoice_id="R4-old"),
        _inv("R4", "Delta", date(2026, 5, 1), 100, 0,
             last_payment_date=date(2026, 5, 1), invoice_id="R4-new"),
    ]
    out = compute_active_payer_rate(invs, as_of=as_of)
    assert out.overall_active == 4
    assert out.overall_paying == 3
    assert out.overall_rate_pct == 75.0
    bucket = {s.tenure: s for s in out.by_tenure}
    assert bucket["0-3m"].active_riders == 2
    assert bucket["0-3m"].paying_riders == 1
    assert bucket["12m+"].active_riders == 1
    assert bucket["12m+"].paying_riders == 1


def test_active_payer_rate_empty_returns_zeros():
    out = compute_active_payer_rate([], as_of=date(2026, 5, 24))
    assert out.overall_active == 0
    assert out.overall_rate_pct == 0.0


# ---------------------------------------------------------------------------
# KPI 3 — On-Time Rate
# ---------------------------------------------------------------------------

def test_on_time_rate_counts_payments_inside_window_only():
    window = resolve_window("monthly", date(2026, 5, 23))
    invs = [
        # On-time, in window.
        _inv("R1", "A", date(2026, 5, 1), 100, 0,
             due_date=date(2026, 5, 14), last_payment_date=date(2026, 5, 10)),
        # Late, in window.
        _inv("R2", "B", date(2026, 5, 1), 100, 0,
             due_date=date(2026, 5, 14), last_payment_date=date(2026, 5, 20)),
        # Outside window (paid in April) — ignored.
        _inv("R3", "C", date(2026, 4, 1), 100, 0,
             due_date=date(2026, 4, 14), last_payment_date=date(2026, 4, 10)),
    ]
    out = compute_on_time_rate(invs, window=window)
    assert out.total_paid_count == 2
    assert out.on_time_count == 1
    assert out.on_time_pct == 50.0


# ---------------------------------------------------------------------------
# KPI 2 — Monthly Collections Rate
# ---------------------------------------------------------------------------

def test_monthly_collections_gross_rate_and_rider_splits():
    window = resolve_window("monthly", date(2026, 5, 23))
    invs = [
        # R1: fully paid in window (invoiced 100, paid 100).
        _inv("R1", "A", date(2026, 5, 5), 100, 0, last_payment_date=date(2026, 5, 10)),
        # R2: partial (invoiced 200, paid 80).
        _inv("R2", "B", date(2026, 5, 5), 200, 120, last_payment_date=date(2026, 5, 10)),
        # R3: invoiced, no payment.
        _inv("R3", "C", date(2026, 5, 5), 100, 100),
        # Outside window — ignored.
        _inv("R4", "D", date(2026, 4, 5), 100, 0, last_payment_date=date(2026, 4, 10)),
    ]
    out = compute_monthly_collections(invs, window=window, write_off_ledger=None)
    assert out.invoiced_ghs == 400.0
    assert out.collected_ghs == 180.0
    assert out.gross_rate_pct == 45.0
    assert out.write_offs_ghs == 0.0
    # Without a ledger, net == gross.
    assert out.net_rate_pct == 45.0
    assert out.splits.fully_paid_riders == 1
    assert out.splits.partial_riders == 1
    assert out.splits.no_pay_riders == 1


# ---------------------------------------------------------------------------
# KPI 4 — MRR
# ---------------------------------------------------------------------------

def test_mrr_computes_current_new_and_churned():
    window = resolve_window("monthly", date(2026, 5, 23))
    invs = [
        # Returning rider invoiced 500 this month.
        _inv("R1", "Old", date(2025, 1, 5), 500, 0),  # first-ever invoice in Jan 2025
        _inv("R1", "Old", date(2026, 5, 5), 500, 0),
        # New rider — first invoice ever in window.
        _inv("R2", "New", date(2026, 5, 12), 300, 300),
        # Churned rider — had old invoices, no invoice this month.
        _inv("R3", "Churn", date(2025, 8, 1), 400, 0),
    ]
    sub_map = {"R3": ("recovery", False)}
    sub_dates = {"R3": date(2026, 5, 15)}  # churned mid-window
    out = compute_mrr(
        invs, as_of=date(2026, 5, 23), window=window,
        subscription_status_map=sub_map, subscription_status_dates=sub_dates,
    )
    assert out.current_ghs == 800.0  # R1 (500) + R2 (300)
    assert out.new_riders == 1
    assert out.new_ghs == 300.0
    assert out.churned_riders == 1
    assert out.churned_ghs == 400.0  # R3's last invoice total
    assert out.net_new_ghs == -100.0  # 300 + 0 reactivated - 400


# ---------------------------------------------------------------------------
# KPI 5 — Aging Distribution
# ---------------------------------------------------------------------------

def test_aging_buckets_classified_by_dpd():
    as_of = date(2026, 5, 24)
    invs = [
        _inv("R1", "A", date(2026, 5, 10), 100, 100),  # 14 days  → Current
        _inv("R2", "B", date(2026, 4, 10), 200, 200),  # 44 days  → 31-60
        _inv("R3", "C", date(2026, 1, 1), 300, 300),   # 143 days → 91-180
        _inv("R4", "D", date(2025, 11, 1), 50, 0),     # paid     → excluded
    ]
    out = compute_aging(invs, as_of=as_of)
    assert out.total_outstanding_ghs == 600.0
    assert out.total_riders_with_balance == 3
    labels = {b.label for b in out.buckets}
    assert any("Current" in lab for lab in labels)
    assert "31–60d" in labels
    assert "91–180d" in labels


# ---------------------------------------------------------------------------
# KPI 7 — Lifetime Efficiency
# ---------------------------------------------------------------------------

def test_lifetime_efficiency_total_minus_balance():
    invs = [
        _inv("R1", "A", date(2026, 3, 1), 1000, 200),  # 800 collected
        _inv("R2", "B", date(2026, 4, 1), 500, 0),     # 500 collected
        _inv("R3", "C", date(2026, 5, 1), 300, 300),   # 0 collected
    ]
    out = compute_lifetime_efficiency(invs)
    assert out.invoiced_ghs == 1800.0
    assert out.collected_ghs == 1300.0
    assert out.outstanding_ghs == 500.0
    assert out.efficiency_pct == round(1300 / 1800 * 100, 1)


# ---------------------------------------------------------------------------
# KPI 9 — Net Charge-Off
# ---------------------------------------------------------------------------

def test_net_charge_off_unavailable_when_ledger_empty():
    window = resolve_window("monthly", date(2026, 5, 23))
    out = compute_net_charge_off(
        write_off_ledger=None, window=window, avg_outstanding_ghs=10_000,
    )
    assert out.available is False
    assert "ledger" in out.reason.lower() or "write-off" in out.reason.lower()


def test_net_charge_off_annualizes_correctly():
    """With a real (template-shipped) ledger and a window covering the
    template's example write-off, KPI 9 returns a non-zero rate."""
    ledger = load_write_off_ledger()
    if ledger.write_offs.empty:
        pytest.skip("Local ledger template is empty.")
    window = resolve_window("custom", date(2026, 5, 24),
                            start=date(2026, 1, 1), end=date(2026, 12, 31))
    out = compute_net_charge_off(ledger, window=window, avg_outstanding_ghs=100_000)
    assert out.available is True
    assert out.window_days >= 360
    assert out.charge_offs_ghs >= 0


# ---------------------------------------------------------------------------
# KPI 10 — Recovery on Churned
# ---------------------------------------------------------------------------

def test_recovery_on_churned_buckets_by_days_post_churn():
    window = resolve_window("custom", date(2026, 5, 24),
                            start=date(2026, 1, 1), end=date(2026, 12, 31))
    # Rider churned 2026-02-15, paid 2026-03-01 (14d) and 2026-05-01 (75d).
    invs = [
        _inv("R1", "Churned", date(2026, 1, 5), 200, 50,
             last_payment_date=date(2026, 3, 1)),
        _inv("R1", "Churned", date(2026, 4, 5), 200, 0,
             last_payment_date=date(2026, 5, 1)),
    ]
    sub_map = {"R1": ("recovery", False)}
    sub_dates = {"R1": date(2026, 2, 15)}
    out = compute_recovery_on_churned(
        invs, window=window,
        subscription_status_map=sub_map, subscription_status_dates=sub_dates,
    )
    assert out.cohort_size == 1
    assert out.recovered_ghs == 350.0  # (200-50) + (200-0)
    by_bucket = {b.bucket: b.ghs for b in out.by_days_post_churn}
    assert by_bucket["0-30d"] == 150.0   # 14 days post churn
    assert by_bucket["61-90d"] == 200.0  # 75 days


def test_recovery_on_churned_empty_cohort_returns_zero():
    window = resolve_window("monthly", date(2026, 5, 23))
    out = compute_recovery_on_churned(
        [], window=window, subscription_status_map={}, subscription_status_dates={},
    )
    assert out.cohort_size == 0
    assert out.recovered_ghs == 0.0


# ---------------------------------------------------------------------------
# Blocked KPIs (6, 8)
# ---------------------------------------------------------------------------

def test_blocked_kpis_carry_explanation():
    roll = blocked_roll_rates()
    cure = blocked_cure_rate()
    assert roll.available is False and "snapshot" in roll.reason.lower()
    assert cure.available is False and "snapshot" in cure.reason.lower()
