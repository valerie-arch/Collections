"""Match candidates for a suspense payment — search the invoice corpus for
plausible rider/invoice matches.

Strategy:
- Exact balance match within ±2 GHS rounding
- Same as invoice total (likely a full settlement)
- For each match, return: rider, invoice info, age, why_match
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from api.agents.collections_report.engine import InvoiceRow

DEFAULT_AMOUNT_TOLERANCE = Decimal("2.00")


@dataclass
class MatchCandidate:
    customer_id: str
    customer_name: str
    invoice_id: str
    invoice_number: str
    invoice_date: str
    invoice_total_ghs: float
    invoice_balance_ghs: float
    days_old: int
    confidence: str  # high | medium | low
    why_match: str


def find_matches(
    invoices: Iterable[InvoiceRow],
    *,
    amount_ghs: float,
    msisdn: str | None = None,
    as_of: date | None = None,
    tolerance: Decimal = DEFAULT_AMOUNT_TOLERANCE,
    limit: int = 25,
) -> list[MatchCandidate]:
    invoices = list(invoices)
    as_of = as_of or date.today()
    target = Decimal(str(amount_ghs))
    candidates: list[MatchCandidate] = []

    for inv in invoices:
        # Strong signal: balance exactly equals the suspense amount (settles in full)
        if inv.balance > 0 and abs(inv.balance - target) <= tolerance:
            days = (as_of - inv.invoice_date).days
            candidates.append(MatchCandidate(
                customer_id=inv.customer_id,
                customer_name=inv.customer_name,
                invoice_id=inv.invoice_id,
                invoice_number=getattr(inv, "invoice_number", "") or "",
                invoice_date=inv.invoice_date.isoformat(),
                invoice_total_ghs=float(inv.total),
                invoice_balance_ghs=float(inv.balance),
                days_old=days,
                confidence="high",
                why_match=f"Open balance GHS {float(inv.balance):.2f} matches payment exactly.",
            ))
            continue

        # Medium signal: invoice total equals the payment (full-cycle settlement)
        if inv.total > 0 and abs(inv.total - target) <= tolerance and inv.balance > 0:
            days = (as_of - inv.invoice_date).days
            candidates.append(MatchCandidate(
                customer_id=inv.customer_id,
                customer_name=inv.customer_name,
                invoice_id=inv.invoice_id,
                invoice_number=getattr(inv, "invoice_number", "") or "",
                invoice_date=inv.invoice_date.isoformat(),
                invoice_total_ghs=float(inv.total),
                invoice_balance_ghs=float(inv.balance),
                days_old=days,
                confidence="medium",
                why_match=f"Invoice total GHS {float(inv.total):.2f} matches payment — likely settling full cycle.",
            ))

    # Sort: high confidence first, then most-recent invoice
    conf_rank = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: (conf_rank.get(c.confidence, 9), c.days_old))
    return candidates[:limit]
