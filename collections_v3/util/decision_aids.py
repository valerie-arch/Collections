"""Decision-aid scoring for suspense rows.

Spec formula:
    score = name_score * 0.5 + phone_partial * 0.3 + amount_equals_open_invoice * 0.2

  * name_score                  : rapidfuzz token_sort_ratio between
                                  sender_name and rider name (0-100)
  * phone_partial               : rapidfuzz partial_ratio between the
                                  receipt's phone digits and the rider's
                                  known phone (0-100)
  * amount_equals_open_invoice  : 100 if the receipt amount exactly
                                  matches any of the rider's open invoice
                                  amounts (in cents), else 0

Returns the top-3 candidates per receipt with their fleet, agency, and
open-invoice list inline so the operator has everything to decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

import pandas as pd
from rapidfuzz import fuzz

from collections_v3.io_.bike_fleet import normalize_name
from collections_v3.util.phone import normalize_phone
from collections_v3.util.rider_index import RiderIndex


@dataclass
class Candidate:
    rider_id: str
    rider_name: str
    fleet: str
    agency: str
    composite_score: float
    name_score: int
    phone_partial: int
    amount_match: int
    open_invoices: list[tuple[str, float]]  # (invoice_id, amount_due)

    def to_summary_str(self) -> str:
        """Single-line summary suitable for a single XLSX cell."""
        invs = "; ".join(f"{iid}={amt:.2f}" for iid, amt in self.open_invoices[:5])
        return (
            f"{self.rider_id} | {self.rider_name} | {self.fleet}/{self.agency} | "
            f"score={self.composite_score:.1f} (name={self.name_score} "
            f"phone={self.phone_partial} amt={self.amount_match}) | "
            f"open: {invs or '(none)'}"
        )


def _amount_cents(v) -> int:
    if v is None:
        return 0
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return 0


def _open_invoices_for_rider(rider_id: str, invoices_all: pd.DataFrame) -> list[tuple[str, float]]:
    if invoices_all is None or invoices_all.empty:
        return []
    df = invoices_all[
        (invoices_all["rider_id"].astype(str).str.strip() == rider_id)
        & (invoices_all["amount_due"].astype(float) > 0)
    ]
    return list(zip(df["invoice_id"].astype(str), df["amount_due"].astype(float)))


def _open_invoice_amount_cents(rider_id: str, invoices_all: pd.DataFrame) -> set[int]:
    return {_amount_cents(amt) for _, amt in _open_invoices_for_rider(rider_id, invoices_all)}


def _rider_phone(rider_id: str, index: RiderIndex) -> str:
    # Reverse-lookup the indexed phone (if any) for this rider.
    for phone, rid in index.phone_to_rider.items():
        if rid == rider_id:
            return phone
    return ""


def score_candidates(
    sender_name: str,
    sender_phone: str,
    receipt_amount: float,
    index: RiderIndex,
    invoices_all: pd.DataFrame,
    *,
    top_n: int = 3,
) -> list[Candidate]:
    """Score every indexed rider against this receipt and return top N."""
    s_name = normalize_name(sender_name)
    s_phone = normalize_phone(sender_phone)
    receipt_cents = _amount_cents(receipt_amount)

    candidates: list[Candidate] = []
    for rider_id, rider_name in index.rider_id_to_name.items():
        r_name = normalize_name(rider_name)
        name_score = int(fuzz.token_sort_ratio(s_name, r_name)) if s_name and r_name else 0

        rider_phone_canon = _rider_phone(rider_id, index)
        if s_phone and rider_phone_canon:
            phone_partial = int(fuzz.partial_ratio(s_phone, rider_phone_canon))
        else:
            phone_partial = 0

        open_cents = _open_invoice_amount_cents(rider_id, invoices_all)
        amount_match = 100 if receipt_cents and receipt_cents in open_cents else 0

        composite = name_score * 0.5 + phone_partial * 0.3 + amount_match * 0.2

        # Skip candidates with zero composite to keep the list useful.
        if composite <= 0:
            continue

        candidates.append(Candidate(
            rider_id=rider_id,
            rider_name=rider_name,
            fleet=index.rider_id_to_fleet.get(rider_id, ""),
            agency=index.rider_id_to_agency.get(rider_id, ""),
            composite_score=round(composite, 2),
            name_score=name_score,
            phone_partial=phone_partial,
            amount_match=amount_match,
            open_invoices=_open_invoices_for_rider(rider_id, invoices_all),
        ))

    candidates.sort(key=lambda c: c.composite_score, reverse=True)
    return candidates[:top_n]
