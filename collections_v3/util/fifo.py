"""FIFO application of a matched receipt across a rider's open invoices.

Rules (per Operator Rule #6):
  * Apply oldest-open-invoice first.
  * Partial application allowed — track applied amount per invoice line.
  * Residual after all open invoices are full → `rider_credit` (never
    auto-refund, per Operator Rule #3).
  * No silent rounding — work in cents internally to avoid float drift.

Inputs:
  * `amount`: GHS the receipt brought in.
  * `open_invoices`: list[dict] with keys (invoice_id, invoice_number,
    invoice_date, amount_due) — already sorted oldest-first OR sorted here.

Returns:
  * `applications`: list[(invoice_id, applied_amount_ghs)]
  * `credit`: float — residual that became rider_credit (0.0 if none)
  * `remaining_due`: dict[invoice_id, new_amount_due_ghs] after application
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass
class FifoResult:
    applications: list[tuple[str, float]]   # (invoice_id, applied amount)
    credit: float                            # residual -> rider_credit
    remaining_due: dict[str, float]          # invoice_id -> remaining amount_due


def _cents(x) -> int:
    if x is None:
        return 0
    return int(round(float(x) * 100))


def apply_fifo(
    amount: float,
    open_invoices: Iterable[dict],
) -> FifoResult:
    """Apply `amount` GHS across `open_invoices` oldest-first."""
    # Sort defensively. Use invoice_date when present; tie-break on
    # invoice_number to keep the order deterministic.
    invoices = sorted(
        list(open_invoices),
        key=lambda r: (
            r.get("invoice_date") or "",
            str(r.get("invoice_number") or ""),
        ),
    )
    remaining_cents = _cents(amount)
    applications: list[tuple[str, float]] = []
    remaining_due: dict[str, float] = {}

    for inv in invoices:
        invoice_id = str(inv.get("invoice_id") or inv.get("invoice_number") or "")
        due_cents = _cents(inv.get("amount_due") or 0)
        if due_cents <= 0 or remaining_cents <= 0:
            remaining_due[invoice_id] = round(due_cents / 100.0, 2)
            continue
        applied_cents = min(remaining_cents, due_cents)
        remaining_cents -= applied_cents
        applications.append((invoice_id, round(applied_cents / 100.0, 2)))
        remaining_due[invoice_id] = round((due_cents - applied_cents) / 100.0, 2)

    credit_ghs = round(remaining_cents / 100.0, 2)
    return FifoResult(applications=applications, credit=credit_ghs, remaining_due=remaining_due)
