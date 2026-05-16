"""Monthly trends — month-over-month portfolio view.

Computes per-month aggregates from the invoice corpus:
  - invoiced (sum of invoices issued that month)
  - collected (sum of payments received that month, by Last Payment Date)
  - outstanding (point-in-time balance on invoices issued ≤ month end)
  - active riders (with at least one invoice that month)
  - completed riders (subscription expired by month end, per sub map)
  - churned riders (subscription cancelled by month end)
  - mrr proxy (sum of distinct rider monthly invoice value)
  - ageing snapshot (open invoice distribution at month end)

Plus the top 10 / bottom 10 riders for the most recent month.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from api.agents.collections_report.engine import InvoiceRow


@dataclass
class MonthPoint:
    year: int
    month: int
    label: str  # "2026-05"
    invoiced_ghs: Decimal = Decimal("0")
    collected_ghs: Decimal = Decimal("0")
    outstanding_ghs: Decimal = Decimal("0")  # point-in-time at month end
    active_riders: int = 0
    new_riders: int = 0
    invoices_issued: int = 0
    mrr_ghs: Decimal = Decimal("0")


@dataclass
class RiderRanking:
    customer_id: str
    customer_name: str
    lifetime_invoiced_ghs: Decimal
    lifetime_collected_ghs: Decimal
    lifetime_outstanding_ghs: Decimal
    collection_ratio: float


@dataclass
class TrendsReport:
    as_of: date
    months: list[MonthPoint] = field(default_factory=list)
    top_10_outstanding: list[RiderRanking] = field(default_factory=list)
    bottom_10_ratio: list[RiderRanking] = field(default_factory=list)
    top_10_collected_lifetime: list[RiderRanking] = field(default_factory=list)
    cumulative_active: int = 0
    cumulative_completed: int = 0
    cumulative_recovery: int = 0


def _month_key(d: date) -> tuple[int, int]:
    return (d.year, d.month)


def _last_day_of_month(yr: int, mo: int) -> date:
    if mo == 12:
        return date(yr + 1, 1, 1).replace(day=1)
    return date(yr, mo + 1, 1)


def build_trends(
    invoices: Iterable[InvoiceRow],
    *,
    as_of: Optional[date] = None,
    subscription_status_map: Optional[dict[str, tuple[str, bool]]] = None,
    months_back: int = 24,
) -> TrendsReport:
    invoices = list(invoices)
    as_of = as_of or date.today()
    sub_map = subscription_status_map or {}

    # Build the month axis: last N months ending in as_of's month.
    months: list[tuple[int, int]] = []
    yr, mo = as_of.year, as_of.month
    for _ in range(months_back):
        months.append((yr, mo))
        mo -= 1
        if mo == 0:
            mo = 12
            yr -= 1
    months.reverse()

    by_month: dict[tuple[int, int], MonthPoint] = {
        (y, m): MonthPoint(year=y, month=m, label=f"{y}-{m:02d}") for y, m in months
    }

    # Track first-invoice month per rider so we can compute "new" rider counts.
    rider_first_seen: dict[str, tuple[int, int]] = {}
    rider_active_in_month: dict[tuple[int, int], set[str]] = defaultdict(set)
    rider_amount_in_month: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )

    for inv in invoices:
        key = _month_key(inv.invoice_date)
        if inv.customer_id:
            prev = rider_first_seen.get(inv.customer_id)
            if prev is None or key < prev:
                rider_first_seen[inv.customer_id] = key
            rider_active_in_month[key].add(inv.customer_id)
            rider_amount_in_month[key][inv.customer_id] += inv.total

        if key in by_month:
            mp = by_month[key]
            mp.invoiced_ghs += inv.total
            mp.invoices_issued += 1

        # Cash in window: payments where Last Payment Date falls in the month
        if inv.last_payment_date:
            pkey = _month_key(inv.last_payment_date)
            if pkey in by_month:
                by_month[pkey].collected_ghs += inv.total - inv.balance

    # Outstanding at month-end: sum balance of invoices issued <= last day.
    # Approximation: invoices issued in or before that month, with current balance.
    # This counts current balance against the month they were issued, summed cumulatively.
    sorted_keys = sorted(by_month.keys())
    invoices_sorted = sorted(invoices, key=lambda i: i.invoice_date)
    inv_idx = 0
    running_open: dict[str, Decimal] = {}  # invoice_id -> balance
    for key in sorted_keys:
        y, m = key
        end_of_month = _last_day_of_month(y, m) - __import__("datetime").timedelta(days=1) \
            if False else date(y + (m // 12), 1 if m == 12 else m + 1, 1)
        # Cleaner: iterate cutoff
        cutoff = date(y, m, 28)
        # find true last day
        if m == 12:
            cutoff = date(y, 12, 31)
        else:
            cutoff = date(y, m + 1, 1).fromordinal(date(y, m + 1, 1).toordinal() - 1)
        while inv_idx < len(invoices_sorted) and invoices_sorted[inv_idx].invoice_date <= cutoff:
            inv = invoices_sorted[inv_idx]
            if inv.invoice_id and inv.balance >= 0:
                running_open[inv.invoice_id] = inv.balance
            inv_idx += 1
        by_month[key].outstanding_ghs = sum(running_open.values(), Decimal("0"))

    # Active riders + new riders + MRR proxy per month
    for key, mp in by_month.items():
        actives = rider_active_in_month.get(key, set())
        mp.active_riders = len(actives)
        mp.new_riders = sum(
            1 for cid in actives if rider_first_seen.get(cid) == key
        )
        # MRR proxy: average monthly invoiced per active rider this month
        amounts = rider_amount_in_month.get(key, {})
        mp.mrr_ghs = sum(amounts.values(), Decimal("0"))

    # ---- Top/bottom rider rankings (lifetime) ----
    per_rider_invoiced: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    per_rider_balance_invoice_seen: dict[str, dict[str, Decimal]] = defaultdict(dict)
    per_rider_name: dict[str, str] = {}

    for inv in invoices:
        if not inv.customer_id:
            continue
        per_rider_invoiced[inv.customer_id] += inv.total
        per_rider_name[inv.customer_id] = inv.customer_name
        if inv.invoice_id:
            per_rider_balance_invoice_seen[inv.customer_id][inv.invoice_id] = inv.balance

    rankings: list[RiderRanking] = []
    for cid, invoiced in per_rider_invoiced.items():
        outstanding = sum(
            per_rider_balance_invoice_seen[cid].values(), Decimal("0")
        )
        collected = invoiced - outstanding
        ratio = float(collected / invoiced) if invoiced > 0 else 0.0
        rankings.append(
            RiderRanking(
                customer_id=cid,
                customer_name=per_rider_name[cid],
                lifetime_invoiced_ghs=invoiced,
                lifetime_collected_ghs=collected,
                lifetime_outstanding_ghs=outstanding,
                collection_ratio=ratio,
            )
        )

    top_outstanding = sorted(
        [r for r in rankings if r.lifetime_outstanding_ghs > 0],
        key=lambda r: r.lifetime_outstanding_ghs,
        reverse=True,
    )[:10]
    bottom_ratio = sorted(
        [r for r in rankings if r.lifetime_invoiced_ghs > 1000],
        key=lambda r: r.collection_ratio,
    )[:10]
    top_collected = sorted(
        rankings, key=lambda r: r.lifetime_collected_ghs, reverse=True
    )[:10]

    # Cumulative subscription counts
    cum_active = sum(1 for v in sub_map.values() if v[0] == "active")
    cum_completed = sum(1 for v in sub_map.values() if v[0] == "completed")
    cum_recovery = sum(1 for v in sub_map.values() if v[0] == "recovery")

    return TrendsReport(
        as_of=as_of,
        months=[by_month[k] for k in sorted_keys],
        top_10_outstanding=top_outstanding,
        bottom_10_ratio=bottom_ratio,
        top_10_collected_lifetime=top_collected,
        cumulative_active=cum_active,
        cumulative_completed=cum_completed,
        cumulative_recovery=cum_recovery,
    )
