"""Tier 1 — canonical phone (MoMo/Telecel) or sender account (bank) → rider.

First-hit wins: phone before account before nothing. Returns the rider_id
and a tier label ("PHONE" or "ACCOUNT"), or (None, None) if no hit.
"""

from __future__ import annotations

from typing import Optional

from collections_v3.util.phone import normalize_phone
from collections_v3.util.rider_index import RiderIndex


def match(receipt_row, index: RiderIndex) -> tuple[Optional[str], Optional[str]]:
    """Returns (rider_id, "PHONE" | "ACCOUNT") or (None, None)."""
    # Phone path — both MoMo (msisdn) and Telecel come through the
    # canonical sender_phone_canonical field; legacy raw field is the fallback.
    phone = str(getattr(receipt_row, "sender_phone_canonical", "")).strip()
    if not phone:
        phone = normalize_phone(getattr(receipt_row, "sender_phone_raw", ""))
    if phone and phone in index.phone_to_rider:
        return index.phone_to_rider[phone], "PHONE"

    # Bank account path — the receipts parser puts the account string in
    # either `sender_account` (when surfaced explicitly) or `reference`
    # (when the bank statement uses a long account-like ref).
    account = str(getattr(receipt_row, "sender_account", "")).strip()
    if account and account in index.account_to_rider:
        return index.account_to_rider[account], "ACCOUNT"

    ref = str(getattr(receipt_row, "reference", "")).strip()
    if ref and ref in index.account_to_rider:
        return index.account_to_rider[ref], "ACCOUNT"

    return None, None
