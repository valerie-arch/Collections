"""Ghanaian-phone normalisation.

Strips +, 00, country code 233; keeps the last PHONE_KEEP_LAST digits (9).
Implementation note: Tier 1 in Prompt 5 will join receipts to riders on
this canonical form, so deviations here propagate everywhere.
"""

from __future__ import annotations

import re

from collections_v3.config import PHONE_KEEP_LAST


_NON_DIGIT = re.compile(r"\D+")


def normalize_phone(raw: str | None) -> str:
    """Return the canonical, country-code-stripped form, or '' for blanks."""
    if not raw:
        return ""
    digits = _NON_DIGIT.sub("", str(raw))
    if not digits:
        return ""
    # Drop a leading 00 (international prefix).
    if digits.startswith("00"):
        digits = digits[2:]
    # Drop a leading 233 (Ghana country code).
    if digits.startswith("233"):
        digits = digits[3:]
    # Drop a leading 0 (local trunk prefix) only if it would leave us with at
    # least PHONE_KEEP_LAST digits — handles "0244xxx" -> "244xxx".
    if digits.startswith("0") and len(digits) > PHONE_KEEP_LAST:
        digits = digits[1:]
    return digits[-PHONE_KEEP_LAST:]
