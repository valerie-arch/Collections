"""Trend series for the Portfolio Dashboard's Trends section.

Returns four time series respecting the dashboard's fleet filter and a
lookback window (3m / 6m / 12m / all):

  1. Collections Rate per month — collected / invoiced, with the raw
     invoiced + collected GHS so the UI can render paired bars under a
     line, plus a target line at 85%.
  4. MRR Movement per month — opening / +new / +reactivated / -churned /
     closing, plus net_new for the waterfall caption.
  6. Net Charge-off per month — windowed from the write-off ledger.
     Cure rate is intentionally omitted (snapshot writer not yet live).
  7. Lifetime Efficiency — running cumulative collected ÷ invoiced.

The two heaviest charts (Aging Trend, Active Payer by Tenure) are
deferred until the daily snapshot writer ships — they'd require a per-
month replay of the engine that's not justified yet.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from api.agents.collections_report.engine import InvoiceRow
from collections_v3.io_.write_offs import WriteOffLedger


COLLECTIONS_RATE_TARGET_PCT = 85.0
DEFAULT_LOOKBACK = "12m"
LOOKBACK_MONTHS = {"3m": 3, "6m": 6, "12m": 12, "all": 60}


# ---------------------------------------------------------------------------
# Shared month-axis helper
# ---------------------------------------------------------------------------

@dataclass
class MonthAxis:
    months: list[tuple[int, int]]            # (year, month) ascending
    labels: list[str]                        # "2026-05"


def month_axis(as_of: date, lookback: str) -> MonthAxis:
    n = LOOKBACK_MONTHS.get(lookback, LOOKBACK_MONTHS[DEFAULT_LOOKBACK])
    months: list[tuple[int, int]] = []
    y, m = as_of.year, as_of.month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()
    return MonthAxis(
        months=months,
        labels=[f"{y}-{m:02d}" for y, m in months],
    )


def _month_key(d: date) -> tuple[int, int]:
    return (d.year, d.month)


def _last_day(y: int, m: int) -> date:
    if m == 12:
        return date(y, 12, 31)
    return date(y + (m // 12), (m % 12) + 1, 1).replace(day=1).fromordinal(
        date(y + (m // 12), (m % 12) + 1, 1).toordinal() - 1
    )


# ---------------------------------------------------------------------------
# 1) Collections Rate per month
# ---------------------------------------------------------------------------

@dataclass
class CollectionsRatePoint:
    label: str
    year: int
    month: int
    invoiced_ghs: float
    collected_ghs: float
    rate_pct: float


@dataclass
class CollectionsRateSeries:
    target_pct: float
    points: list[CollectionsRatePoint]


def collections_rate_trend(
    invoices: list[InvoiceRow], axis: MonthAxis,
) -> CollectionsRateSeries:
    invoiced = defaultdict(lambda: Decimal("0"))
    collected = defaultdict(lambda: Decimal("0"))
    for inv in invoices:
        k_iss = _month_key(inv.invoice_date)
        invoiced[k_iss] += inv.total
        if inv.last_payment_date:
            k_pay = _month_key(inv.last_payment_date)
            collected[k_pay] += inv.total - inv.balance
    points: list[CollectionsRatePoint] = []
    for (y, m), label in zip(axis.months, axis.labels):
        inv_amt = float(invoiced.get((y, m), Decimal("0")))
        col_amt = float(collected.get((y, m), Decimal("0")))
        rate = round((col_amt / inv_amt) * 100, 1) if inv_amt > 0 else 0.0
        points.append(CollectionsRatePoint(
            label=label, year=y, month=m,
            invoiced_ghs=round(inv_amt, 2),
            collected_ghs=round(col_amt, 2),
            rate_pct=rate,
        ))
    return CollectionsRateSeries(
        target_pct=COLLECTIONS_RATE_TARGET_PCT, points=points,
    )


# ---------------------------------------------------------------------------
# 4) MRR Movement per month
# ---------------------------------------------------------------------------

@dataclass
class MrrMovementPoint:
    label: str
    year: int
    month: int
    opening_ghs: float
    new_ghs: float
    reactivated_ghs: float
    churned_ghs: float
    closing_ghs: float
    net_new_ghs: float


@dataclass
class MrrMovementSeries:
    points: list[MrrMovementPoint]


def mrr_movement_trend(
    invoices: list[InvoiceRow], axis: MonthAxis, *,
    subscription_status_map: Optional[dict[str, tuple[str, bool]]] = None,
    subscription_status_dates: Optional[dict[str, date]] = None,
) -> MrrMovementSeries:
    """Per-month MRR movement using invoice corpus + subscription dates.

    Opening MRR = sum of riders' invoiced totals in the PREVIOUS month
                  (proxy for what was billed entering this month).
    New MRR     = riders whose first-ever invoice is in this month, summed
                  by this month's invoiced total.
    Churned MRR = riders whose subscription change date falls in this
                  month and status is recovery/completed; valued by their
                  last invoice total.
    Reactivated = riders billed this month who had a sub change date BEFORE
                  this month and status now active (rare but real).
    Closing     = Opening + New + Reactivated − Churned.
    """
    sub_map = subscription_status_map or {}
    sub_dates = subscription_status_dates or {}

    explicitly_churned = {
        cid for cid, (s, _t) in sub_map.items() if s in {"recovery", "completed"}
    }

    rider_first_invoice: dict[str, tuple[int, int]] = {}
    per_month_totals: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    rider_last_invoice_amount: dict[str, tuple[date, Decimal]] = {}
    for inv in invoices:
        cid = inv.customer_id
        if not cid:
            continue
        k = _month_key(inv.invoice_date)
        prev = rider_first_invoice.get(cid)
        if prev is None or k < prev:
            rider_first_invoice[cid] = k
        if cid not in explicitly_churned:
            per_month_totals[k][cid] += inv.total
        last = rider_last_invoice_amount.get(cid)
        if last is None or inv.invoice_date > last[0]:
            rider_last_invoice_amount[cid] = (inv.invoice_date, inv.total)

    points: list[MrrMovementPoint] = []
    prev_closing = 0.0
    for (y, m), label in zip(axis.months, axis.labels):
        amounts = per_month_totals.get((y, m), {})
        # New: first-ever invoice in this month
        new_total = Decimal("0")
        new_riders = set()
        for cid, amt in amounts.items():
            if rider_first_invoice.get(cid) == (y, m):
                new_total += amt
                new_riders.add(cid)
        # Reactivated: billed this month with a prior recovery/completed flip
        first_of_month = date(y, m, 1)
        reactivated_total = Decimal("0")
        for cid, amt in amounts.items():
            if cid in new_riders:
                continue
            change_date = sub_dates.get(cid)
            if change_date and change_date < first_of_month:
                status = (sub_map.get(cid) or ("", False))[0]
                if status in {"recovery", "completed"}:
                    reactivated_total += amt
        # Churned: status change date inside the month
        last_of_month = _last_day(y, m)
        churned_total = Decimal("0")
        for cid, change_date in sub_dates.items():
            if first_of_month <= change_date <= last_of_month:
                status = (sub_map.get(cid) or ("", False))[0]
                if status in {"recovery", "completed"}:
                    last = rider_last_invoice_amount.get(cid)
                    if last:
                        churned_total += last[1]
        new_f = round(float(new_total), 2)
        rea_f = round(float(reactivated_total), 2)
        ch_f = round(float(churned_total), 2)
        opening = prev_closing
        closing = round(opening + new_f + rea_f - ch_f, 2)
        net_new = round(new_f + rea_f - ch_f, 2)
        points.append(MrrMovementPoint(
            label=label, year=y, month=m,
            opening_ghs=round(opening, 2),
            new_ghs=new_f, reactivated_ghs=rea_f, churned_ghs=ch_f,
            closing_ghs=closing, net_new_ghs=net_new,
        ))
        prev_closing = closing

    return MrrMovementSeries(points=points)


# ---------------------------------------------------------------------------
# 6) Net Charge-off per month (charge-off line only; cure deferred)
# ---------------------------------------------------------------------------

@dataclass
class ChargeOffPoint:
    label: str
    year: int
    month: int
    charge_offs_ghs: float
    recoveries_ghs: float
    net_ghs: float


@dataclass
class ChargeOffSeries:
    available: bool
    points: list[ChargeOffPoint] = field(default_factory=list)
    reason: str = ""


def charge_off_trend(
    ledger: Optional[WriteOffLedger], axis: MonthAxis,
) -> ChargeOffSeries:
    if ledger is None or (ledger.write_offs.empty and ledger.recoveries.empty):
        return ChargeOffSeries(
            available=False,
            reason=(
                "Write-off ledger is empty. Populate the template (or set "
                "WRITE_OFFS_SHEET_ID) for the trend to populate."
            ),
        )
    wo = ledger.write_offs
    rc = ledger.recoveries

    wo_by_month: dict[tuple[int, int], float] = defaultdict(float)
    if not wo.empty:
        for r in wo.itertuples(index=False):
            d = getattr(r, "write_off_date", None)
            if d is None:
                continue
            wo_by_month[_month_key(d)] += float(getattr(r, "amount_ghs", 0.0))
    rc_by_month: dict[tuple[int, int], float] = defaultdict(float)
    if not rc.empty:
        for r in rc.itertuples(index=False):
            d = getattr(r, "recovery_date", None)
            if d is None:
                continue
            rc_by_month[_month_key(d)] += float(getattr(r, "amount_ghs", 0.0))

    points: list[ChargeOffPoint] = []
    for (y, m), label in zip(axis.months, axis.labels):
        co = round(wo_by_month.get((y, m), 0.0), 2)
        re = round(rc_by_month.get((y, m), 0.0), 2)
        points.append(ChargeOffPoint(
            label=label, year=y, month=m,
            charge_offs_ghs=co, recoveries_ghs=re,
            net_ghs=round(co - re, 2),
        ))
    return ChargeOffSeries(available=True, points=points)


# ---------------------------------------------------------------------------
# 7) Lifetime Efficiency running cumulative
# ---------------------------------------------------------------------------

@dataclass
class LifetimeEfficiencyPoint:
    label: str
    year: int
    month: int
    cumulative_invoiced_ghs: float
    cumulative_collected_ghs: float
    efficiency_pct: float


@dataclass
class LifetimeEfficiencySeries:
    points: list[LifetimeEfficiencyPoint]


def lifetime_efficiency_trend(
    invoices: list[InvoiceRow], axis: MonthAxis,
) -> LifetimeEfficiencySeries:
    """Cumulative invoiced and collected through the END of each month on
    the axis. Includes ALL history before the axis (i.e. invoices issued
    pre-axis still contribute their full collected portion)."""
    # Pre-aggregate
    inv_by_month: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0"))
    col_by_month: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0"))
    for inv in invoices:
        inv_by_month[_month_key(inv.invoice_date)] += inv.total
        if inv.last_payment_date:
            col_by_month[_month_key(inv.last_payment_date)] += (
                inv.total - inv.balance
            )

    # Pre-seed cumulatives with months BEFORE the axis so the line is meaningful.
    pre_inv = Decimal("0")
    pre_col = Decimal("0")
    if axis.months:
        first_y, first_m = axis.months[0]
        for (y, m), amt in inv_by_month.items():
            if (y, m) < (first_y, first_m):
                pre_inv += amt
        for (y, m), amt in col_by_month.items():
            if (y, m) < (first_y, first_m):
                pre_col += amt

    cum_inv = pre_inv
    cum_col = pre_col
    points: list[LifetimeEfficiencyPoint] = []
    for (y, m), label in zip(axis.months, axis.labels):
        cum_inv += inv_by_month.get((y, m), Decimal("0"))
        cum_col += col_by_month.get((y, m), Decimal("0"))
        eff = (
            round(float(cum_col / cum_inv) * 100, 1) if cum_inv > 0 else 0.0
        )
        points.append(LifetimeEfficiencyPoint(
            label=label, year=y, month=m,
            cumulative_invoiced_ghs=round(float(cum_inv), 2),
            cumulative_collected_ghs=round(float(cum_col), 2),
            efficiency_pct=eff,
        ))
    return LifetimeEfficiencySeries(points=points)
