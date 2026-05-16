"""Invoice outliers — derived "exceptions" surfaced from the invoice data.

Categories surfaced for the Exceptions tab:
  - very_old_open    : open invoices > 180 days
  - large_balance    : open invoices with balance > 5000 GHS
  - unpaid_recurring : rider has 3+ consecutive open invoices in a row
  - status_mismatch  : Zoho status says "paid" but balance > 0 (or vice versa)
  - missing_customer : invoice has no customer_id (data quality)
  - duplicate_invoice: same Invoice Number across files with different totals
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable

from api.agents.collections_report.engine import InvoiceRow


@dataclass
class OutlierItem:
    category: str
    severity: str  # info | warning | error
    title: str
    detail: str
    customer_id: str = ""
    customer_name: str = ""
    invoice_id: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    amount_ghs: float = 0.0
    days_old: int = 0


@dataclass
class OutliersReport:
    as_of: date
    counts: dict[str, int] = field(default_factory=dict)
    items: list[OutlierItem] = field(default_factory=list)


def detect_outliers(invoices: Iterable[InvoiceRow], *, as_of: date | None = None) -> OutliersReport:
    invoices = list(invoices)
    as_of = as_of or date.today()
    items: list[OutlierItem] = []

    by_customer: dict[str, list[InvoiceRow]] = defaultdict(list)
    for inv in invoices:
        if inv.customer_id:
            by_customer[inv.customer_id].append(inv)

    for inv in invoices:
        days = (as_of - inv.invoice_date).days
        # 1. very old open invoices
        if inv.balance > 0 and days > 180:
            items.append(OutlierItem(
                category="very_old_open",
                severity="error" if days > 365 else "warning",
                title=f"Open invoice over {180 if days <= 365 else 365} days",
                detail=f"{inv.invoice_number}: outstanding GHS {float(inv.balance):,.2f} since {inv.invoice_date.isoformat()}",
                customer_id=inv.customer_id,
                customer_name=inv.customer_name,
                invoice_id=inv.invoice_id,
                invoice_number=inv.invoice_number,
                invoice_date=inv.invoice_date.isoformat(),
                amount_ghs=float(inv.balance),
                days_old=days,
            ))
        # 2. large balances
        if inv.balance > 5000:
            items.append(OutlierItem(
                category="large_balance",
                severity="warning",
                title=f"Large open balance (GHS {float(inv.balance):,.0f})",
                detail=f"{inv.invoice_number}: outstanding GHS {float(inv.balance):,.2f}, invoiced {inv.invoice_date.isoformat()}",
                customer_id=inv.customer_id,
                customer_name=inv.customer_name,
                invoice_id=inv.invoice_id,
                invoice_number=inv.invoice_number,
                invoice_date=inv.invoice_date.isoformat(),
                amount_ghs=float(inv.balance),
                days_old=days,
            ))
        # 3. status mismatch
        if inv.status in ("paid", "closed") and inv.balance > 0:
            items.append(OutlierItem(
                category="status_mismatch",
                severity="error",
                title="Zoho marked paid but balance > 0",
                detail=f"{inv.invoice_number}: status={inv.status}, balance GHS {float(inv.balance):,.2f}",
                customer_id=inv.customer_id,
                customer_name=inv.customer_name,
                invoice_id=inv.invoice_id,
                invoice_number=inv.invoice_number,
                invoice_date=inv.invoice_date.isoformat(),
                amount_ghs=float(inv.balance),
            ))
        elif inv.status in ("open", "overdue") and inv.balance == 0:
            items.append(OutlierItem(
                category="status_mismatch",
                severity="info",
                title="Balance = 0 but status open",
                detail=f"{inv.invoice_number}: status={inv.status}, balance 0 — likely needs status flip",
                customer_id=inv.customer_id,
                customer_name=inv.customer_name,
                invoice_id=inv.invoice_id,
                invoice_number=inv.invoice_number,
                invoice_date=inv.invoice_date.isoformat(),
            ))
        # 4. missing customer_id
        if not inv.customer_id:
            items.append(OutlierItem(
                category="missing_customer",
                severity="warning",
                title="Invoice has no customer ID",
                detail=f"{inv.invoice_number or inv.invoice_id}: cannot attribute to a rider",
                invoice_id=inv.invoice_id,
                invoice_number=inv.invoice_number,
                invoice_date=inv.invoice_date.isoformat(),
                amount_ghs=float(inv.total),
            ))

    # 5. duplicates by invoice_number with different totals
    by_number: dict[str, list[InvoiceRow]] = defaultdict(list)
    for inv in invoices:
        if inv.invoice_number:
            by_number[inv.invoice_number].append(inv)
    for number, group in by_number.items():
        totals = {round(float(g.total), 2) for g in group}
        if len(group) > 1 and len(totals) > 1:
            items.append(OutlierItem(
                category="duplicate_invoice",
                severity="warning",
                title=f"Invoice {number} appears with mismatched totals",
                detail=f"Seen {len(group)} times across files with totals {sorted(totals)}",
                customer_id=group[0].customer_id,
                customer_name=group[0].customer_name,
                invoice_id=group[0].invoice_id,
                invoice_number=number,
            ))

    # 6. unpaid recurring: rider has 3+ consecutive open invoices
    for cid, rider_invs in by_customer.items():
        rider_invs.sort(key=lambda i: i.invoice_date)
        streak = 0
        max_streak = 0
        for inv in rider_invs:
            if inv.balance > 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        if max_streak >= 3:
            unpaid = [i for i in rider_invs if i.balance > 0]
            total_open = sum((i.balance for i in unpaid), Decimal("0"))
            items.append(OutlierItem(
                category="unpaid_recurring",
                severity="warning",
                title=f"{max_streak} consecutive unpaid invoices",
                detail=f"Rider has {len(unpaid)} open invoices totaling GHS {float(total_open):,.2f}",
                customer_id=cid,
                customer_name=rider_invs[0].customer_name,
                amount_ghs=float(total_open),
            ))

    # Sort: errors first, then by amount desc
    sev_order = {"error": 0, "warning": 1, "info": 2}
    items.sort(key=lambda x: (sev_order.get(x.severity, 9), -x.amount_ghs))

    counts = Counter(it.category for it in items)
    return OutliersReport(as_of=as_of, counts=dict(counts), items=items)
