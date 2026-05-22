"""Strict header validation. Source files must declare expected columns
exactly — case-insensitive after trimming whitespace. Mismatches abort the
run rather than silently picking the wrong column.
"""

from __future__ import annotations


class HeaderMismatch(Exception):
    """Raised when a source file's columns don't match the contract."""


def require_headers(
    source_name: str,
    file_label: str,
    actual: list[str],
    required: list[str],
) -> dict[str, str]:
    """Return a {required_name -> actual_column_name} map, or raise.

    Match is case-insensitive after trimming whitespace. Extra columns in the
    source are tolerated; missing required columns abort.
    """
    norm_actual = {c.strip().lower(): c for c in actual if c is not None}
    mapping: dict[str, str] = {}
    missing: list[str] = []
    for req in required:
        key = req.strip().lower()
        if key in norm_actual:
            mapping[req] = norm_actual[key]
        else:
            missing.append(req)
    if missing:
        raise HeaderMismatch(
            f"{source_name} ({file_label}) is missing required columns: "
            f"{missing}. Found columns: {actual}"
        )
    return mapping
