"""Tier 2 — rapidfuzz token_sort_ratio >= NAME_MATCH_THRESHOLD on sender name.

Returns the best-scoring rider_id when the score clears the threshold,
otherwise (None, None). Strictly *greater than or equal to* the threshold,
per the spec acceptance criterion: a score of 84 must fall through.
"""

from __future__ import annotations

from typing import Optional

from rapidfuzz import fuzz, process

from collections_v3.config import NAME_MATCH_THRESHOLD
from collections_v3.io_.bike_fleet import normalize_name
from collections_v3.util.rider_index import RiderIndex


def match(receipt_row, index: RiderIndex) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """Returns (rider_id, "NAME", score) or (None, None, None)."""
    name = normalize_name(str(getattr(receipt_row, "sender_name", "")))
    if not name or not index.name_list:
        return None, None, None

    # rapidfuzz.process.extractOne with token_sort_ratio finds the closest
    # name in the candidate list.
    choices = [n for n, _ in index.name_list]
    rider_ids = [rid for _, rid in index.name_list]
    best = process.extractOne(name, choices, scorer=fuzz.token_sort_ratio)
    if best is None:
        return None, None, None
    matched_name, score, position = best
    if score < NAME_MATCH_THRESHOLD:
        return None, None, None
    return rider_ids[position], "NAME", int(score)
