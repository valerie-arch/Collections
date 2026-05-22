"""Aging math for suspense rows.

Aging bucket is computed from `first_seen_at`, NOT the receipt date — a
receipt that landed in suspense weeks ago should age out of "0-7" even if
the receipt itself is recent.

Buckets:
  0-7    days_in_suspense  <= 7
  8-30   8  <= days_in_suspense <= 30
  31-60  31 <= days_in_suspense <= 60
  60+    days_in_suspense  > 60
"""

from __future__ import annotations

from datetime import date
from typing import Optional


def days_in_suspense(first_seen_at: Optional[date], today: Optional[date] = None) -> int:
    if first_seen_at is None:
        return 0
    today = today or date.today()
    return max(0, (today - first_seen_at).days)


def aging_bucket(days: int) -> str:
    if days <= 7:
        return "0_7"
    if days <= 30:
        return "8_30"
    if days <= 60:
        return "31_60"
    return "60+"
