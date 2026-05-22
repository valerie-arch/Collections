"""Tier 3 — reference field contains rider_id or bike_reg.

Substring search; first hit wins. We scan multiple receipt fields
(reference, narration, sender_name) because Ghanaian MoMo/bank rails
inconsistently route the customer-typed memo.
"""

from __future__ import annotations

from typing import Optional

from collections_v3.util.rider_index import RiderIndex


def match(receipt_row, index: RiderIndex) -> tuple[Optional[str], Optional[str]]:
    """Returns (rider_id, "REF") or (None, None)."""
    haystack_parts = [
        str(getattr(receipt_row, "reference", "")),
        str(getattr(receipt_row, "narration", "")),
        str(getattr(receipt_row, "sender_name", "")),
    ]
    haystack = " ".join(haystack_parts).upper()
    if not haystack.strip():
        return None, None

    # Bike regs first because they're more specific (TSA-NNNN / WAHUB-NNNN);
    # a CUS-NN substring could accidentally match a longer id.
    for bike_reg, rider_id in index.bike_reg_to_rider.items():
        if bike_reg and bike_reg in haystack:
            return rider_id, "REF"
    for rider_id in index.rider_id_set:
        rid_upper = rider_id.upper()
        if rid_upper and rid_upper in haystack:
            return rider_id, "REF"
    return None, None
