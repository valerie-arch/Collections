"""Soft-match guardrail (Operator Rule #2 / Step 3 spec).

A name-only Tier 2 match with no phone, no ref, and amount > GHS 500 is
inherently risky — there's no traceable identifier connecting the rider
to the receipt. Even when an operator manually assigns such a row in the
suspense file, we push it back to suspense and demand a phone or ref
before accepting the assignment.

Threshold and the "name-only" definition come from the spec; centralised
here so Step 5/Step 6 and any future review path can call the same check.
"""

from __future__ import annotations

from dataclasses import dataclass


SOFT_MATCH_AMOUNT_THRESHOLD_GHS: float = 500.0


@dataclass
class GuardrailResult:
    accepted: bool
    reason: str = ""


def check_assignment(
    *, amount: float, sender_phone: str, reference: str, narration: str = "",
) -> GuardrailResult:
    """Inspect a suspense-resolution payload. The caller should only invoke
    this when the operator's assignment is *name-only* (no automatic phone/
    account/ref hit) — for tier 1 / tier 3 hits the guardrail is moot.

    Returns accepted=False with a reason when the receipt is "high-value
    name-only" and lacks any traceable identifier.
    """
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        amt = 0.0
    if amt <= SOFT_MATCH_AMOUNT_THRESHOLD_GHS:
        return GuardrailResult(accepted=True)
    phone = (sender_phone or "").strip()
    ref = (reference or "").strip()
    narr = (narration or "").strip()
    if phone or ref or narr:
        return GuardrailResult(accepted=True)
    return GuardrailResult(
        accepted=False,
        reason=(
            f"name_only_soft_match_over_{int(SOFT_MATCH_AMOUNT_THRESHOLD_GHS)}_GHS"
        ),
    )
