"""Match-candidate suggestions for unmatched payments.

The reconciler returns a single best match (or none) above its threshold.
For the Payments page review workflow we want the TOP N candidates so
the user can pick the right one. Sources, in priority order:

  1. Prior allocation history — a previous payment from the same sender
     was manually allocated to a rider. High confidence (95%) — same
     sender almost always means same rider.
  2. Name overlap — Jaccard-ish overlap between payment sender name and
     each rider's name. Score 0..1. We surface candidates with score
     >= 0.25 (lower than the reconciler's auto-match threshold so the
     user sees plausible but not-quite-confident options).

Returns top N (default 3) candidates sorted by confidence desc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .matcher import RiderRecord, _name_score


SUGGESTION_NAME_THRESHOLD = 0.25


@dataclass
class MatchCandidate:
    rider_id: str
    rider_name: str
    confidence: float       # 0..1
    reason: str             # "history" | "name"
    detail: str             # human-readable explanation


def _normalize_sender(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def build_history_index(
    allocations: Iterable[dict],
) -> dict[str, tuple[str, str]]:
    """sender_name → (rider_id, rider_name) from allocation records."""
    idx: dict[str, tuple[str, str]] = {}
    for rec in allocations:
        if rec.get("status") != "allocated":
            continue
        sender = _normalize_sender(rec.get("sender_name", ""))
        rid = (rec.get("rider_id") or "").strip()
        rname = (rec.get("rider_name") or "").strip()
        if sender and rid:
            idx[sender] = (rid, rname)
    return idx


def suggest_matches(
    sender_name: str,
    riders: list[RiderRecord],
    *,
    history: Optional[dict[str, tuple[str, str]]] = None,
    top_n: int = 3,
) -> list[MatchCandidate]:
    """Return up to `top_n` suggested rider matches for a payment whose
    sender appears as `sender_name`."""
    history = history or {}
    candidates: dict[str, MatchCandidate] = {}

    # 1) History: have we manually allocated this exact sender before?
    sender_key = _normalize_sender(sender_name)
    if sender_key and sender_key in history:
        rid, rname = history[sender_key]
        # The cached rider_name may be stale — prefer the live one if found.
        live = next((r for r in riders if r.customer_id == rid), None)
        if live:
            candidates[rid] = MatchCandidate(
                rider_id=rid,
                rider_name=live.customer_name,
                confidence=0.95,
                reason="history",
                detail=f"Previously allocated payments from “{sender_name}” to this rider",
            )

    # 2) Name overlap
    for r in riders:
        if r.customer_id in candidates:
            continue
        score = _name_score(sender_name, r.customer_name)
        if score >= SUGGESTION_NAME_THRESHOLD:
            candidates[r.customer_id] = MatchCandidate(
                rider_id=r.customer_id,
                rider_name=r.customer_name,
                confidence=round(score, 3),
                reason="name",
                detail=f"Name overlap {(score * 100):.0f}%",
            )

    return sorted(candidates.values(), key=lambda c: -c.confidence)[:top_n]
