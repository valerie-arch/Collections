"""Payment reconciliation engine.

Pipeline:
  1) Load every payment in the Drive-synced folder (parser).
  2) Filter to payments dated >= PAYMENTS_CUTOFF_DATE (avoid double-applying
     anything Finance has already posted to Zoho).
  3) Build a rider master from the latest Zoho invoice corpus.
  4) Match each payment to a rider (matcher).
  5) For each matched payment, allocate it across that rider's open invoices,
     oldest first, with overflow to the next invoice.
  6) Anything that doesn't match → unmatched_for_suspense.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from api.agents.collections_report.engine import InvoiceRow
from api.agents.collections_report.parsers import parse_zoho_invoice_csv

from .matcher import RiderMatch, RiderRecord, match_payments
from .parser import PaymentRow, parse_folder


@dataclass
class Allocation:
    invoice_id: str
    invoice_number: str
    applied_ghs: Decimal
    invoice_balance_before: Decimal
    invoice_balance_after: Decimal


@dataclass
class ReconciledPayment:
    payment: PaymentRow
    rider_id: str
    rider_name: str
    allocations: list[Allocation] = field(default_factory=list)
    unapplied_ghs: Decimal = Decimal("0")  # overflow with nowhere to land
    method: str = "customer_id"
    confidence: float = 1.0


@dataclass
class UnmatchedPayment:
    payment: PaymentRow
    best_guess_rider_name: str = ""
    best_guess_confidence: float = 0.0
    reason: str = ""


@dataclass
class ReconcileResult:
    cutoff_date: date
    invoices_corpus_size: int
    riders_in_master: int
    total_payments: int
    in_scope_payments: int
    matched: list[ReconciledPayment] = field(default_factory=list)
    unmatched: list[UnmatchedPayment] = field(default_factory=list)

    @property
    def total_matched_amount_ghs(self) -> Decimal:
        return sum(
            (sum((a.applied_ghs for a in m.allocations), Decimal("0")) for m in self.matched),
            Decimal("0"),
        )

    @property
    def total_unmatched_amount_ghs(self) -> Decimal:
        return sum((u.payment.amount_ghs for u in self.unmatched), Decimal("0"))


def _build_rider_master(invoices: list[InvoiceRow]) -> list[RiderRecord]:
    """Latest known name per customer_id, from the invoice corpus."""
    by_id: dict[str, RiderRecord] = {}
    for inv in invoices:
        cid = (inv.customer_id or "").strip()
        if not cid:
            continue
        # Prefer the name from the most recent invoice for that rider.
        existing = by_id.get(cid)
        if not existing or (inv.invoice_date and (not existing.customer_name or len(inv.customer_name) > len(existing.customer_name))):
            by_id[cid] = RiderRecord(customer_id=cid, customer_name=inv.customer_name or "")
    return list(by_id.values())


def _open_invoices_for_rider(invoices: list[InvoiceRow], rider_id: str) -> list[InvoiceRow]:
    rows = [inv for inv in invoices if (inv.customer_id or "").strip() == rider_id and inv.balance > 0]
    rows.sort(key=lambda inv: (inv.invoice_date, inv.invoice_number))
    return rows


def reconcile_payments(
    *,
    payments_folder: str | Path,
    invoices_folder: str | Path,
    cutoff_date: date,
) -> ReconcileResult:
    # 1+2) Load and filter payments
    all_payments = parse_folder(payments_folder)
    in_scope = [
        p for p in all_payments
        if p.date is None or p.date >= cutoff_date
    ]

    # 3) Build invoice corpus + rider master
    invoices: list[InvoiceRow] = []
    invoices_path = Path(invoices_folder)
    if invoices_path.exists():
        for f in sorted(invoices_path.glob("*.csv")):
            try:
                invoices.extend(parse_zoho_invoice_csv(f))
            except Exception:
                continue
    rider_master = _build_rider_master(invoices)

    result = ReconcileResult(
        cutoff_date=cutoff_date,
        invoices_corpus_size=len(invoices),
        riders_in_master=len(rider_master),
        total_payments=len(all_payments),
        in_scope_payments=len(in_scope),
    )

    if not in_scope:
        return result

    # 4) Match payments → riders
    matches: list[RiderMatch] = match_payments(in_scope, rider_master)

    # Working copy of invoice balances — we mutate as we allocate so multiple
    # payments to the same rider don't double-apply against the same invoice.
    balance_by_invoice: dict[str, Decimal] = {inv.invoice_id: inv.balance for inv in invoices}

    # 5) Allocate
    for m in matches:
        if m.rider_id is None:
            result.unmatched.append(
                UnmatchedPayment(
                    payment=m.payment,
                    best_guess_rider_name=m.rider_name or "",
                    best_guess_confidence=m.confidence,
                    reason=(
                        f"name confidence {m.confidence:.0%} below threshold"
                        if m.confidence > 0
                        else "no rider name match"
                    ),
                )
            )
            continue

        open_invs = _open_invoices_for_rider(invoices, m.rider_id)
        # Apply live balance from working set
        for inv in open_invs:
            inv.balance = balance_by_invoice.get(inv.invoice_id, inv.balance)

        amount_left = m.payment.amount_ghs
        rec = ReconciledPayment(
            payment=m.payment,
            rider_id=m.rider_id,
            rider_name=m.rider_name or "",
            method=m.method,
            confidence=m.confidence,
        )

        for inv in open_invs:
            if amount_left <= 0:
                break
            current_balance = balance_by_invoice.get(inv.invoice_id, inv.balance)
            if current_balance <= 0:
                continue
            applied = min(amount_left, current_balance)
            new_balance = current_balance - applied
            rec.allocations.append(
                Allocation(
                    invoice_id=inv.invoice_id,
                    invoice_number=inv.invoice_number or inv.invoice_id,
                    applied_ghs=applied,
                    invoice_balance_before=current_balance,
                    invoice_balance_after=new_balance,
                )
            )
            balance_by_invoice[inv.invoice_id] = new_balance
            amount_left -= applied

        rec.unapplied_ghs = amount_left
        result.matched.append(rec)

    return result
