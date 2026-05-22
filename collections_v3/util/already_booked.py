"""Step 2A — already-booked check.

A receipt is "already in Zoho" when its txn_id appears as the
`reference_number` on a Zoho payment, or when the receipt's
(date, amount, sender_phone/account) tuple matches a Zoho payment of the
same shape. We never re-allocate already-booked receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from collections_v3.util.phone import normalize_phone


@dataclass
class AlreadyBookedIndex:
    refs: set[str]                                  # zoho payment reference_number
    by_date_amount_phone: dict[tuple, str]          # (date, amount_cents, phone) -> payment_id
    by_date_amount_ref: dict[tuple, str]            # (date, amount_cents, ref)   -> payment_id


def _to_cents(v) -> int:
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return 0


def build_already_booked_index(
    zoho_payments: Optional[pd.DataFrame],
) -> AlreadyBookedIndex:
    refs: set[str] = set()
    by_dap: dict[tuple, str] = {}
    by_dar: dict[tuple, str] = {}
    if zoho_payments is None or zoho_payments.empty:
        return AlreadyBookedIndex(refs, by_dap, by_dar)
    for r in zoho_payments.itertuples(index=False):
        ref = str(getattr(r, "reference_number", "")).strip()
        if ref:
            refs.add(ref)
        pid = str(getattr(r, "payment_id", "")).strip() or ref or ""
        d = getattr(r, "date", None)
        amt = _to_cents(getattr(r, "amount", 0.0))
        # We don't have a phone on the Zoho payment row, so the (date, amount,
        # ref) form is the only secondary key we can build cheaply.
        if d is not None and amt and ref:
            by_dar.setdefault((d, amt, ref), pid)
    return AlreadyBookedIndex(refs, by_dap, by_dar)


def is_already_booked(
    receipt_row, ab: AlreadyBookedIndex
) -> bool:
    """A receipt is already booked when its txn_id or its
    (date, amount, reference) tuple matches a Zoho payment."""
    txn = str(getattr(receipt_row, "txn_id", "")).strip()
    if txn and txn in ab.refs:
        return True
    ref = str(getattr(receipt_row, "reference", "")).strip()
    if ref and ref in ab.refs:
        return True
    d = getattr(receipt_row, "date", None)
    amt = _to_cents(getattr(receipt_row, "amount", 0.0))
    if d is not None and amt and txn:
        if (d, amt, txn) in ab.by_date_amount_ref:
            return True
    return False
