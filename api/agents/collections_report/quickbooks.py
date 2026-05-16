"""QuickBooks Online (QBO) import helpers.

Builds rows shaped for the standard QBO Excel/CSV import templates:
- Invoices: one row per invoice
- Payments: one row per recorded payment (per Last Payment Date)

Fleet maps to QBO 'Class' so collections can be tracked separately for
Wahu Mobility vs TSA in the GL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Literal

from api.agents.collections_report.engine import InvoiceRow

ExportType = Literal["invoices", "payments"]
FleetFilter = Literal["All", "Wahu", "TSA"]


@dataclass
class QbInvoiceRow:
    invoice_no: str
    customer: str
    invoice_date: str
    due_date: str
    terms: str
    item: str            # service item — typically the subscription plan name
    description: str
    quantity: float
    rate: float
    amount: float
    balance: float
    status: str
    fleet: str           # → QBO Class
    currency: str = "GHS"


@dataclass
class QbPaymentRow:
    customer: str
    payment_date: str
    amount: float
    payment_method: str    # default "MoMo" — finance can override
    reference_no: str      # invoice number paid (proxy for txn ref)
    applied_to_invoice_no: str
    memo: str
    fleet: str
    currency: str = "GHS"


@dataclass
class QbExport:
    type: ExportType
    fleet: FleetFilter
    window_start: date
    window_end: date
    invoice_rows: list[QbInvoiceRow] = field(default_factory=list)
    payment_rows: list[QbPaymentRow] = field(default_factory=list)
    total_amount: Decimal = Decimal("0")
    row_count: int = 0


def _resolve_fleet(
    customer_id: str,
    customer_name: str,
    subs_map: dict[str, tuple[str, bool]] | None,
    name_map: dict[str, str] | None,
) -> str:
    """Same precedence as the rest of the platform: OS list → sub TSA flag → Wahu."""
    if name_map and customer_name:
        f = name_map.get(customer_name.strip().lower())
        if f in ("TSA", "Wahu"):
            return f
    if subs_map:
        sub = subs_map.get(customer_id)
        if sub and sub[1]:
            return "TSA"
    return "Wahu"


def _passes_fleet(row_fleet: str, want: FleetFilter) -> bool:
    return want == "All" or row_fleet == want


def build_invoice_export(
    invoices: Iterable[InvoiceRow],
    *,
    window_start: date,
    window_end: date,
    fleet: FleetFilter = "All",
    subscription_status_map: dict[str, tuple[str, bool]] | None = None,
    name_fleet_map: dict[str, str] | None = None,
) -> QbExport:
    rows: list[QbInvoiceRow] = []
    total = Decimal("0")

    for inv in invoices:
        if not (window_start <= inv.invoice_date <= window_end):
            continue
        rider_fleet = _resolve_fleet(
            inv.customer_id, inv.customer_name, subscription_status_map, name_fleet_map
        )
        if not _passes_fleet(rider_fleet, fleet):
            continue

        rows.append(
            QbInvoiceRow(
                invoice_no=getattr(inv, "invoice_number", "") or "",
                customer=inv.customer_name,
                invoice_date=inv.invoice_date.isoformat(),
                due_date=inv.due_date.isoformat() if inv.due_date else inv.invoice_date.isoformat(),
                terms="Due on Receipt",
                item="Subscription billing",
                description=f"Invoice for {inv.customer_name}",
                quantity=1.0,
                rate=float(inv.total),
                amount=float(inv.total),
                balance=float(inv.balance),
                status=inv.status,
                fleet=rider_fleet,
            )
        )
        total += inv.total

    rows.sort(key=lambda r: (r.invoice_date, r.customer))
    return QbExport(
        type="invoices",
        fleet=fleet,
        window_start=window_start,
        window_end=window_end,
        invoice_rows=rows,
        total_amount=total,
        row_count=len(rows),
    )


def build_payment_export(
    invoices: Iterable[InvoiceRow],
    *,
    window_start: date,
    window_end: date,
    fleet: FleetFilter = "All",
    subscription_status_map: dict[str, tuple[str, bool]] | None = None,
    name_fleet_map: dict[str, str] | None = None,
    payment_method_default: str = "MoMo",
) -> QbExport:
    """Payments dated in window — derived from Zoho's Last Payment Date."""
    rows: list[QbPaymentRow] = []
    total = Decimal("0")

    for inv in invoices:
        pay_date = inv.last_payment_date
        if not pay_date or not (window_start <= pay_date <= window_end):
            continue
        paid = inv.total - inv.balance
        if paid <= 0:
            continue
        rider_fleet = _resolve_fleet(
            inv.customer_id, inv.customer_name, subscription_status_map, name_fleet_map
        )
        if not _passes_fleet(rider_fleet, fleet):
            continue

        invoice_no = getattr(inv, "invoice_number", "") or ""
        rows.append(
            QbPaymentRow(
                customer=inv.customer_name,
                payment_date=pay_date.isoformat(),
                amount=float(paid),
                payment_method=payment_method_default,
                reference_no=invoice_no,
                applied_to_invoice_no=invoice_no,
                memo=(
                    f"Payment received on {pay_date.isoformat()} for invoice "
                    f"{invoice_no} dated {inv.invoice_date.isoformat()}"
                ),
                fleet=rider_fleet,
            )
        )
        total += paid

    rows.sort(key=lambda r: (r.payment_date, r.customer))
    return QbExport(
        type="payments",
        fleet=fleet,
        window_start=window_start,
        window_end=window_end,
        payment_rows=rows,
        total_amount=total,
        row_count=len(rows),
    )
