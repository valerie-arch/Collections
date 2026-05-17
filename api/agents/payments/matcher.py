"""Match a normalised PaymentRow to a Wahu rider.

Order of confidence:
  1. Exact Customer ID embedded in the reference / narration (e.g. "WHR1234").
  2. Customer name token overlap against the rider master.

If no match crosses the score threshold, the payment is "unmatched" and
will be pushed to suspense.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .parser import PaymentRow


@dataclass
class RiderRecord:
    customer_id: str
    customer_name: str


@dataclass
class RiderMatch:
    payment: PaymentRow
    rider_id: Optional[str]
    rider_name: Optional[str]
    confidence: float  # 0..1
    method: str        # 'customer_id' | 'name_overlap' | 'none'


_CID_RE = re.compile(r"\bWHR[-_\s]?(\d{2,6})\b", re.IGNORECASE)
_STOPWORDS = {
    "mr", "mrs", "ms", "miss", "dr", "rev", "hon",
    "junior", "jr", "snr", "the", "and", "of",
}


def _name_tokens(name: str) -> set[str]:
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", name or "").lower()
    return {t for t in cleaned.split() if len(t) >= 2 and t not in _STOPWORDS}


def _name_score(payment_name: str, rider_name: str) -> float:
    pt = _name_tokens(payment_name)
    rt = _name_tokens(rider_name)
    if not pt or not rt:
        return 0.0
    overlap = pt & rt
    if not overlap:
        return 0.0
    # Jaccard-ish: weighted toward overlap relative to rider name length.
    return len(overlap) / max(len(rt), 1)


def match_payments(
    payments: Iterable[PaymentRow],
    riders: Iterable[RiderRecord],
    *,
    name_threshold: float = 0.5,
) -> list[RiderMatch]:
    rider_list = list(riders)
    id_to_rider = {r.customer_id.upper(): r for r in rider_list}

    out: list[RiderMatch] = []
    for p in payments:
        # 1) Customer ID match in reference / name
        match_id: Optional[str] = None
        for blob in (p.reference, p.raw_name):
            m = _CID_RE.search(blob or "")
            if m:
                # Try with and without dash
                candidate = f"WHR{m.group(1)}"
                candidates = [candidate, candidate.upper(), f"WHR-{m.group(1)}"]
                for c in candidates:
                    if c.upper() in id_to_rider:
                        match_id = c.upper()
                        break
                if match_id:
                    break

        if match_id:
            r = id_to_rider[match_id]
            out.append(
                RiderMatch(
                    payment=p,
                    rider_id=r.customer_id,
                    rider_name=r.customer_name,
                    confidence=1.0,
                    method="customer_id",
                )
            )
            continue

        # 2) Name overlap
        best: tuple[float, Optional[RiderRecord]] = (0.0, None)
        for r in rider_list:
            score = _name_score(p.raw_name, r.customer_name)
            if score > best[0]:
                best = (score, r)

        if best[1] is not None and best[0] >= name_threshold:
            r = best[1]
            out.append(
                RiderMatch(
                    payment=p,
                    rider_id=r.customer_id,
                    rider_name=r.customer_name,
                    confidence=best[0],
                    method="name_overlap",
                )
            )
        else:
            out.append(
                RiderMatch(
                    payment=p,
                    rider_id=None,
                    rider_name=None,
                    confidence=best[0] if best[1] else 0.0,
                    method="none",
                )
            )
    return out
