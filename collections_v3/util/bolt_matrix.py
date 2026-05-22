"""Bolt weekly payout — deduction decision matrix.

Spec (top-down, first match wins):

  | Condition                                  | Deduction         | Payout            |
  |--------------------------------------------|-------------------|-------------------|
  | outstanding >= earnings AND earnings >= 420| min(420, outstanding) | earnings - deduction |
  | outstanding >= earnings AND earnings < 420 | min(earnings, outstanding, 420) | earnings - deduction |
  | outstanding <  earnings                    | outstanding (clear)   | earnings - outstanding |
  | outstanding == 0                           | 0                     | earnings           |

Cap: GHS 420 / rider / week. Surplus always flows to the rider.

Decision matrix kept tiny + pure so the Step 5 orchestrator can compose
it with FIFO application and fleet routing without inheriting any I/O.
"""

from __future__ import annotations

from collections_v3.config import MAX_WEEKLY_DEDUCTION_GHS


def compute_deduction(
    outstanding: float,
    earnings: float,
    *,
    cap: float = float(MAX_WEEKLY_DEDUCTION_GHS),
) -> tuple[float, float]:
    """Return (deduction, payout_to_rider) for one rider's week.

    The four spec rows collapse to a single rule: we never deduct more
    than (a) what's owed, (b) what was earned, or (c) the weekly cap.
    Acceptance case #1 (outstanding=500, earnings=600 -> deduction=420)
    makes it explicit that the cap binds even when outstanding < earnings
    — so the 'full clearance' row in the spec table also gets the cap.

    Payout is always max(0, earnings - deduction).
    """
    outstanding = max(0.0, float(outstanding or 0.0))
    earnings = max(0.0, float(earnings or 0.0))
    deduction = min(outstanding, earnings, cap)
    payout = max(0.0, earnings - deduction)
    return round(deduction, 2), round(payout, 2)
