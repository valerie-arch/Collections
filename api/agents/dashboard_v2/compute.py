"""Compute functions for the 10-KPI Portfolio Dashboard.

Three layers (Behavioral / Financial / Portfolio). Each KPI is a self-
contained pure function over the invoice corpus + supporting data
(subscription map, write-off ledger). KPIs that depend on data we don't
have yet (daily snapshots) return `available=False` with a reason.

Data sources reused from elsewhere:
  * Zoho invoice corpus  — api/agents/collections_report/parsers.py
  * Subscription status  — load_subscription_status_map, load_subscription_status_dates
  * Aging bucket labels  — api/agents/collections_report/engine._ageing_label
  * Write-off ledger     — collections_v3/io_/write_offs.load_write_off_ledger

A "payment event" here is derived from the invoice corpus's
`last_payment_date` field — that is the only payment signal in the data
the page reads. Once the v3 reconciliation pipeline's `matched_payments`
artifact becomes the read source, KPIs 1, 2, 3 will become more precise.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from api.agents.collections_report.engine import InvoiceRow, _ageing_label
from collections_v3.io_.write_offs import WriteOffLedger, net_charge_off


# ---------------------------------------------------------------------------
# Window / period helpers
# ---------------------------------------------------------------------------

@dataclass
class Window:
    period: str       # daily | weekly | monthly | lifetime | custom
    start: date
    end: date
    label: str        # human-readable, e.g. "May 2026", "Week of 18 May"


def resolve_window(period: str, as_of: date,
                   start: Optional[date] = None,
                   end: Optional[date] = None) -> Window:
    """Map a period selector to a concrete (start, end, label) window.

    Supported periods: MTD, Lifetime, Custom. MTD = first of current month
    through `as_of` (i.e. month-to-date, NOT the full calendar month).
    Lifetime is a wide window so the same compute paths apply.
    """
    p = (period or "mtd").lower()
    if p == "mtd":
        first = as_of.replace(day=1)
        return Window("mtd", first, as_of,
                      f"{first.strftime('%B %Y')} (MTD through {as_of.strftime('%d %b')})")
    if p == "lifetime":
        return Window("lifetime", date(2000, 1, 1), as_of, "Lifetime")
    if p == "custom":
        s = start or as_of.replace(day=1)
        e = end or as_of
        return Window("custom", s, e,
                      f"{s.strftime('%d %b %Y')} – {e.strftime('%d %b %Y')}")
    # Fallback: treat unknown as MTD.
    return resolve_window("mtd", as_of)


# ---------------------------------------------------------------------------
# KPI 1 — Active Payer Rate (30-day, segmented by tenure)
# ---------------------------------------------------------------------------

TENURE_BUCKETS = [
    ("0-3m", 0, 90),
    ("3-6m", 91, 180),
    ("6-12m", 181, 365),
    ("12m+", 366, 10_000),
]


@dataclass
class TenureSegment:
    tenure: str
    active_riders: int
    paying_riders: int
    rate_pct: float


@dataclass
class ActivePayerRate:
    overall_rate_pct: float
    overall_paying: int
    overall_active: int
    by_tenure: list[TenureSegment]
    lookback_days: int = 30


def compute_active_payer_rate(
    invoices: list[InvoiceRow], *,
    as_of: date, lookback_days: int = 30,
    subscription_status_map: Optional[dict[str, tuple[str, bool]]] = None,
) -> ActivePayerRate:
    """A rider is "active" iff their subscription status is "active" (not
    recovery / completed) per the Zoho subscriptions map. A rider is
    "paying" if they had any last_payment_date in the last `lookback_days`.

    Tenure = MIN(invoice_date) per rider.
    """
    cutoff = as_of - timedelta(days=lookback_days)
    sub_map = subscription_status_map or {}
    first_invoice: dict[str, date] = {}
    has_recent_payment: set[str] = set()

    for inv in invoices:
        cid = inv.customer_id
        if not cid:
            continue
        prev = first_invoice.get(cid)
        if prev is None or inv.invoice_date < prev:
            first_invoice[cid] = inv.invoice_date
        if inv.last_payment_date and inv.last_payment_date >= cutoff:
            has_recent_payment.add(cid)

    # Active set: subscription status == "active". Fall back to "has any
    # invoice on record" only if the sub map is empty (preserves usefulness
    # in dev environments without subscription data).
    if sub_map:
        active_riders = {
            cid for cid, (status, _is_tsa) in sub_map.items() if status == "active"
        }
    else:
        active_riders = set(first_invoice.keys())

    # Bucket riders by tenure.
    by_bucket: dict[str, list[str]] = defaultdict(list)
    for cid in active_riders:
        fi = first_invoice.get(cid)
        if not fi:
            # Active rider per subs but no invoice on record — bucket as 0-3m.
            by_bucket["0-3m"].append(cid)
            continue
        days = (as_of - fi).days
        for label, lo, hi in TENURE_BUCKETS:
            if lo <= days <= hi:
                by_bucket[label].append(cid)
                break

    segments: list[TenureSegment] = []
    for label, _, _ in TENURE_BUCKETS:
        riders = by_bucket.get(label, [])
        paying = sum(1 for cid in riders if cid in has_recent_payment)
        rate = round(100 * paying / len(riders), 1) if riders else 0.0
        segments.append(TenureSegment(
            tenure=label, active_riders=len(riders),
            paying_riders=paying, rate_pct=rate,
        ))

    overall_active = len(active_riders)
    overall_paying = len(active_riders & has_recent_payment)
    overall_rate = round(100 * overall_paying / overall_active, 1) if overall_active else 0.0

    return ActivePayerRate(
        overall_rate_pct=overall_rate,
        overall_paying=overall_paying,
        overall_active=overall_active,
        by_tenure=segments,
        lookback_days=lookback_days,
    )


# ---------------------------------------------------------------------------
# KPI 3 — On-Time Payment Rate (vs invoice due_date)
# ---------------------------------------------------------------------------

@dataclass
class OnTimeRate:
    on_time_pct: float
    on_time_count: int
    total_paid_count: int
    note: str


def compute_on_time_rate(
    invoices: list[InvoiceRow], *, window: Window,
) -> OnTimeRate:
    """% of invoices paid by their due_date, restricted to invoices whose
    `last_payment_date` falls inside `window`. NOTE: the GHS 70 daily-debit
    framing requires a daily billing schedule we don't have yet; this is a
    proxy."""
    on_time = 0
    total = 0
    for inv in invoices:
        if not inv.last_payment_date:
            continue
        if inv.last_payment_date < window.start or inv.last_payment_date > window.end:
            continue
        total += 1
        if inv.due_date and inv.last_payment_date <= inv.due_date:
            on_time += 1
    pct = round(100 * on_time / total, 1) if total else 0.0
    return OnTimeRate(
        on_time_pct=pct, on_time_count=on_time, total_paid_count=total,
        note="vs invoice due_date — daily-schedule data not yet wired",
    )


# ---------------------------------------------------------------------------
# KPI 6 — Roll Rates (BLOCKED — needs daily snapshots)
# ---------------------------------------------------------------------------

@dataclass
class BlockedKpi:
    available: bool = False
    reason: str = ""


def blocked_roll_rates() -> BlockedKpi:
    return BlockedKpi(
        reason=(
            "Roll Rates compare DPD buckets between two points in time. "
            "Needs the daily snapshot writer (artifacts/snapshots/"
            "rider_state_YYYY-MM-DD.parquet) to be enabled first."
        ),
    )


def blocked_cure_rate() -> BlockedKpi:
    return BlockedKpi(
        reason=(
            "Cure Rate requires daily snapshots so we can tell whether a "
            "rider in 31+ DPD at t-T is back to Current today. Snapshot "
            "writer not yet enabled."
        ),
    )


# ---------------------------------------------------------------------------
# KPI 2 — Monthly Collections Rate (gross + net, with rider classification)
# ---------------------------------------------------------------------------

@dataclass
class CollectionSplits:
    fully_paid_riders: int
    partial_riders: int
    no_pay_riders: int


@dataclass
class MonthlyCollectionsRate:
    invoiced_ghs: float
    collected_ghs: float
    gross_rate_pct: float
    write_offs_ghs: float
    net_rate_pct: float
    splits: CollectionSplits


def compute_monthly_collections(
    invoices: list[InvoiceRow], *, window: Window,
    write_off_ledger: Optional[WriteOffLedger] = None,
) -> MonthlyCollectionsRate:
    invoiced = Decimal("0")
    collected = Decimal("0")
    per_rider_invoiced: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    per_rider_collected: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for inv in invoices:
        # An invoice contributes to "invoiced" if it was issued in window.
        if window.start <= inv.invoice_date <= window.end:
            invoiced += inv.total
            if inv.customer_id:
                per_rider_invoiced[inv.customer_id] += inv.total
        # Collected = paid amount on invoices whose last_payment_date is in
        # window (proxy: total - balance assumed paid on that date).
        if inv.last_payment_date and window.start <= inv.last_payment_date <= window.end:
            paid = inv.total - inv.balance
            if paid > 0:
                collected += paid
                if inv.customer_id:
                    per_rider_collected[inv.customer_id] += paid

    gross_rate = (
        round(float(collected / invoiced) * 100, 1) if invoiced > 0 else 0.0
    )

    # Write-offs inside window net against collections.
    write_offs_ghs = 0.0
    if write_off_ledger is not None:
        nco = net_charge_off(write_off_ledger, start=window.start, end=window.end)
        write_offs_ghs = nco["charge_offs_ghs"]

    effective_invoiced = float(invoiced) - write_offs_ghs
    net_rate = (
        round(float(collected) / effective_invoiced * 100, 1)
        if effective_invoiced > 0 else 0.0
    )

    # Rider classification — anyone with invoiced > 0 in window.
    fully_paid = partial = no_pay = 0
    for cid, inv_amt in per_rider_invoiced.items():
        paid = per_rider_collected.get(cid, Decimal("0"))
        if paid >= inv_amt and inv_amt > 0:
            fully_paid += 1
        elif paid > 0:
            partial += 1
        else:
            no_pay += 1

    return MonthlyCollectionsRate(
        invoiced_ghs=round(float(invoiced), 2),
        collected_ghs=round(float(collected), 2),
        gross_rate_pct=gross_rate,
        write_offs_ghs=round(write_offs_ghs, 2),
        net_rate_pct=net_rate,
        splits=CollectionSplits(
            fully_paid_riders=fully_paid,
            partial_riders=partial,
            no_pay_riders=no_pay,
        ),
    )


# ---------------------------------------------------------------------------
# KPI 4 — Current MRR & Movement (New / Churned / Reactivated / Net New)
# ---------------------------------------------------------------------------

@dataclass
class MrrSnapshot:
    current_ghs: float
    new_ghs: float
    churned_ghs: float
    reactivated_ghs: float
    net_new_ghs: float
    active_riders: int
    new_riders: int
    churned_riders: int


def compute_mrr(
    invoices: list[InvoiceRow], *, as_of: date, window: Window,
    subscription_status_map: Optional[dict[str, tuple[str, bool]]] = None,
    subscription_status_dates: Optional[dict[str, date]] = None,
) -> MrrSnapshot:
    """MRR proxied as the sum of one representative monthly invoice amount
    per active rider this month. Movement is detected by:
      * `new`        — first-ever invoice date inside window.
      * `churned`    — rider transitioned to recovery/completed inside window
                       (subscription_status_dates carries the change date).
      * `reactivated` — rider has an invoice in window AND a status change
                        before the window (i.e. previously churned).
    """
    sub_map = subscription_status_map or {}
    sub_dates = subscription_status_dates or {}

    # "Active" = subscription status == "active" (consistent with the
    # platform-wide definition). MRR sums invoices issued in window only
    # for riders who are NOT explicitly churned (recovery/completed) per
    # the subscription map. Riders absent from the map are treated as
    # unknown-status and included by default — otherwise the MRR collapses
    # to zero whenever the sub map is partial.
    rider_first_invoice: dict[str, date] = {}
    rider_window_total: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    explicitly_churned_ids = {
        cid for cid, (status, _t) in sub_map.items()
        if status in {"recovery", "completed"}
    }
    for inv in invoices:
        cid = inv.customer_id
        if not cid:
            continue
        prev = rider_first_invoice.get(cid)
        if prev is None or inv.invoice_date < prev:
            rider_first_invoice[cid] = inv.invoice_date
        if window.start <= inv.invoice_date <= window.end:
            if cid not in explicitly_churned_ids:
                rider_window_total[cid] += inv.total

    active_rider_ids = set(rider_window_total.keys())
    current_mrr = sum(rider_window_total.values(), Decimal("0"))

    # New MRR: riders whose first-ever invoice is inside window.
    new_riders = {
        cid for cid in active_rider_ids
        if rider_first_invoice.get(cid)
        and window.start <= rider_first_invoice[cid] <= window.end
    }
    new_mrr = sum(rider_window_total[cid] for cid in new_riders)

    # Churned MRR: subs whose status changed to recovery/completed inside
    # window. Estimate per-rider value as their last observed invoice total.
    rider_last_invoice_amount: dict[str, Decimal] = {}
    for inv in invoices:
        if inv.customer_id:
            cur = rider_last_invoice_amount.get(inv.customer_id)
            if cur is None or inv.invoice_date > cur[0]:
                rider_last_invoice_amount[inv.customer_id] = (inv.invoice_date, inv.total)
    churned_riders: set[str] = set()
    churned_mrr = Decimal("0")
    for cid, change_date in sub_dates.items():
        status = (sub_map.get(cid) or ("", False))[0]
        if status not in {"recovery", "completed"}:
            continue
        if window.start <= change_date <= window.end:
            churned_riders.add(cid)
            last = rider_last_invoice_amount.get(cid)
            if last:
                churned_mrr += last[1]

    # Reactivated MRR: riders active this window whose status had previously
    # flipped to recovery/completed (i.e. status change date < window.start).
    reactivated_mrr = Decimal("0")
    for cid in active_rider_ids:
        change_date = sub_dates.get(cid)
        if change_date and change_date < window.start:
            status = (sub_map.get(cid) or ("", False))[0]
            if status in {"recovery", "completed"}:
                reactivated_mrr += rider_window_total[cid]

    net_new = new_mrr + reactivated_mrr - churned_mrr

    return MrrSnapshot(
        current_ghs=round(float(current_mrr), 2),
        new_ghs=round(float(new_mrr), 2),
        churned_ghs=round(float(churned_mrr), 2),
        reactivated_ghs=round(float(reactivated_mrr), 2),
        net_new_ghs=round(float(net_new), 2),
        active_riders=len(active_rider_ids),
        new_riders=len(new_riders),
        churned_riders=len(churned_riders),
    )


# ---------------------------------------------------------------------------
# KPI 5 — Aging Distribution
# ---------------------------------------------------------------------------

@dataclass
class AgingBucket:
    label: str
    rider_count: int
    open_invoice_count: int
    ghs: float
    pct_of_ghs: float


@dataclass
class AgingDistribution:
    as_of: date
    buckets: list[AgingBucket]
    total_outstanding_ghs: float
    total_riders_with_balance: int


def compute_aging(invoices: list[InvoiceRow], *, as_of: date) -> AgingDistribution:
    by_bucket_ghs: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_bucket_invoices: dict[str, int] = defaultdict(int)
    by_bucket_riders: dict[str, set[str]] = defaultdict(set)
    riders_with_balance: set[str] = set()

    for inv in invoices:
        if inv.balance <= 0:
            continue
        days = (as_of - inv.invoice_date).days
        if days < 0:
            continue
        label = _ageing_label(days)
        by_bucket_ghs[label] += inv.balance
        by_bucket_invoices[label] += 1
        if inv.customer_id:
            by_bucket_riders[label].add(inv.customer_id)
            riders_with_balance.add(inv.customer_id)

    total_ghs = sum(by_bucket_ghs.values(), Decimal("0"))
    # Preserve a canonical order so the UI doesn't re-shuffle.
    order = [
        "Current (0–30d)", "31–60d", "61–90d", "91–180d",
        "181–365d", "365d+",
    ]
    seen = set()
    buckets: list[AgingBucket] = []
    for label in order:
        if label not in by_bucket_ghs:
            continue
        seen.add(label)
        g = float(by_bucket_ghs[label])
        buckets.append(AgingBucket(
            label=label,
            rider_count=len(by_bucket_riders[label]),
            open_invoice_count=by_bucket_invoices[label],
            ghs=round(g, 2),
            pct_of_ghs=round(100 * g / float(total_ghs), 1) if total_ghs > 0 else 0.0,
        ))
    # Surface any bucket labels we didn't anticipate (defensive).
    for label, g in by_bucket_ghs.items():
        if label in seen:
            continue
        gf = float(g)
        buckets.append(AgingBucket(
            label=label, rider_count=len(by_bucket_riders[label]),
            open_invoice_count=by_bucket_invoices[label],
            ghs=round(gf, 2),
            pct_of_ghs=round(100 * gf / float(total_ghs), 1) if total_ghs > 0 else 0.0,
        ))

    return AgingDistribution(
        as_of=as_of,
        buckets=buckets,
        total_outstanding_ghs=round(float(total_ghs), 2),
        total_riders_with_balance=len(riders_with_balance),
    )


# ---------------------------------------------------------------------------
# KPI 7 — Lifetime Outstanding vs Cash Collected
# ---------------------------------------------------------------------------

@dataclass
class LifetimeEfficiency:
    invoiced_ghs: float
    collected_ghs: float
    outstanding_ghs: float
    efficiency_pct: float


def compute_lifetime_efficiency(invoices: list[InvoiceRow]) -> LifetimeEfficiency:
    invoiced = sum((inv.total for inv in invoices), Decimal("0"))
    outstanding = sum((inv.balance for inv in invoices if inv.balance > 0), Decimal("0"))
    collected = invoiced - outstanding
    eff = round(float(collected / invoiced) * 100, 1) if invoiced > 0 else 0.0
    return LifetimeEfficiency(
        invoiced_ghs=round(float(invoiced), 2),
        collected_ghs=round(float(collected), 2),
        outstanding_ghs=round(float(outstanding), 2),
        efficiency_pct=eff,
    )


# ---------------------------------------------------------------------------
# KPI 9 — Net Charge-Off Rate (annualized)
# ---------------------------------------------------------------------------

@dataclass
class NetChargeOff:
    available: bool
    charge_offs_ghs: float = 0.0
    recoveries_ghs: float = 0.0
    net_ghs: float = 0.0
    avg_outstanding_ghs: float = 0.0
    annualized_pct: float = 0.0
    window_days: int = 0
    reason: str = ""


def compute_net_charge_off(
    write_off_ledger: Optional[WriteOffLedger], *, window: Window,
    avg_outstanding_ghs: float,
) -> NetChargeOff:
    if write_off_ledger is None or (
        write_off_ledger.write_offs.empty and write_off_ledger.recoveries.empty
    ):
        return NetChargeOff(
            available=False,
            reason=(
                "Write-off ledger is empty. Populate "
                "collections_v3/io_/templates/write_off_ledger_template.xlsx "
                "(or set WRITE_OFFS_SHEET_ID) for KPI 9 to light up."
            ),
        )
    nco = net_charge_off(write_off_ledger, start=window.start, end=window.end)
    days = max((window.end - window.start).days + 1, 1)
    annualized = 0.0
    if avg_outstanding_ghs > 0:
        annualized = round(
            (nco["net_charge_off_ghs"] / avg_outstanding_ghs) * (365 / days) * 100,
            2,
        )
    return NetChargeOff(
        available=True,
        charge_offs_ghs=nco["charge_offs_ghs"],
        recoveries_ghs=nco["recoveries_ghs"],
        net_ghs=nco["net_charge_off_ghs"],
        avg_outstanding_ghs=round(avg_outstanding_ghs, 2),
        annualized_pct=annualized,
        window_days=days,
    )


# ---------------------------------------------------------------------------
# KPI 10 — Recovery Rate on Churned Riders
# ---------------------------------------------------------------------------

POST_CHURN_BUCKETS = [
    ("0-30d", 0, 30),
    ("31-60d", 31, 60),
    ("61-90d", 61, 90),
    ("91-180d", 91, 180),
    ("181-365d", 181, 365),
    ("365d+", 366, 100_000),
]


@dataclass
class RecoveryByDays:
    bucket: str
    ghs: float


@dataclass
class RecoveryOnChurned:
    cohort_size: int
    cohort_outstanding_at_churn_ghs: float
    recovered_ghs: float
    recovery_rate_pct: float
    by_days_post_churn: list[RecoveryByDays]
    note: str = ""


def compute_recovery_on_churned(
    invoices: list[InvoiceRow], *, window: Window,
    subscription_status_map: dict[str, tuple[str, bool]],
    subscription_status_dates: dict[str, date],
) -> RecoveryOnChurned:
    """Cohort = riders who churned (status flipped to recovery/completed)
    inside `window`. Outstanding-at-churn approximated by today's open
    balance for that rider (we don't have point-in-time snapshots). Each
    rider's post-churn recovery = sum of `last_payment_date - churn_date`
    bucketized per invoice that was paid AFTER its rider's churn date.
    """
    cohort: dict[str, date] = {}
    for cid, change_date in subscription_status_dates.items():
        status = (subscription_status_map.get(cid) or ("", False))[0]
        if status not in {"recovery", "completed"}:
            continue
        if window.start <= change_date <= window.end:
            cohort[cid] = change_date
    if not cohort:
        return RecoveryOnChurned(
            cohort_size=0, cohort_outstanding_at_churn_ghs=0.0,
            recovered_ghs=0.0, recovery_rate_pct=0.0,
            by_days_post_churn=[RecoveryByDays(b, 0.0) for b, _, _ in POST_CHURN_BUCKETS],
            note="No riders churned in window.",
        )

    cohort_outstanding = Decimal("0")
    recovered_total = Decimal("0")
    by_bucket: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for inv in invoices:
        cid = inv.customer_id
        if cid not in cohort:
            continue
        if inv.balance > 0:
            cohort_outstanding += inv.balance
        if inv.last_payment_date and inv.last_payment_date > cohort[cid]:
            paid = inv.total - inv.balance
            if paid > 0:
                recovered_total += paid
                gap = (inv.last_payment_date - cohort[cid]).days
                for label, lo, hi in POST_CHURN_BUCKETS:
                    if lo <= gap <= hi:
                        by_bucket[label] += paid
                        break

    total_basis = cohort_outstanding + recovered_total
    rate = (
        round(float(recovered_total / total_basis) * 100, 1)
        if total_basis > 0 else 0.0
    )

    return RecoveryOnChurned(
        cohort_size=len(cohort),
        cohort_outstanding_at_churn_ghs=round(float(cohort_outstanding), 2),
        recovered_ghs=round(float(recovered_total), 2),
        recovery_rate_pct=rate,
        by_days_post_churn=[
            RecoveryByDays(b, round(float(by_bucket.get(b, Decimal("0"))), 2))
            for b, _, _ in POST_CHURN_BUCKETS
        ],
        note=(
            "Outstanding-at-churn is approximated by current open balance "
            "(point-in-time snapshots would tighten this)."
        ),
    )
