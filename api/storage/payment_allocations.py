"""Manual payment allocation decisions.

When the reconciliation engine can't auto-match a payment, the user
reviews the Payments page's match suggestions and makes a call:
  - "allocated"  — assign a specific rider_id (the auto-match was
                   wrong, or there was no auto-match)
  - "not_rider"  — payment is not collections-related (e.g. supplier
                   refund, miskeyed test transaction). Excluded from
                   collections totals and the QuickBooks schedule.

Records persist between requests in data/payment_allocations.json,
keyed by the natural (source_file, line_no) tuple that the parser
already produces. JSON-backed to match the pattern used by
api/storage/suspense.py and api/storage/agencies.py — no SQLAlchemy
table needed for this volume.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

STORE_PATH = Path("data/payment_allocations.json")
_LOCK = Lock()

# Decision codes
STATUS_ALLOCATED = "allocated"
STATUS_NOT_RIDER = "not_rider"


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _key(source_file: str, line_no: int) -> str:
    return f"{source_file}#{line_no}"


def _load() -> dict[str, dict]:
    if not STORE_PATH.exists():
        return {}
    try:
        return json.loads(STORE_PATH.read_text())
    except Exception:
        return {}


def _save(data: dict[str, dict]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))


def get(source_file: str, line_no: int) -> Optional[dict]:
    with _LOCK:
        return _load().get(_key(source_file, line_no))


def all_decisions() -> dict[str, dict]:
    """Return the full keyed map. Caller is read-only."""
    with _LOCK:
        return _load()


def upsert(
    *,
    source_file: str,
    line_no: int,
    status: str,
    rider_id: Optional[str] = None,
    rider_name: Optional[str] = None,
    sender_name: Optional[str] = None,
    sender_phone: Optional[str] = None,
    amount_ghs: Optional[float] = None,
    payment_date: Optional[str] = None,
    reference: Optional[str] = None,
    decided_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Record (or overwrite) a manual decision for a single payment row.

    The sender_* + amount + reference fields are cached on the record so
    the suggestion engine can mine the history (sender_name → rider_id)
    without having to re-load every payment file."""
    if status not in {STATUS_ALLOCATED, STATUS_NOT_RIDER}:
        raise ValueError(f"unknown status: {status!r}")
    if status == STATUS_ALLOCATED and not rider_id:
        raise ValueError("rider_id is required when status is 'allocated'")

    key = _key(source_file, line_no)
    rec = {
        "source_file": source_file,
        "line_no": line_no,
        "status": status,
        "rider_id": (rider_id or "").strip(),
        "rider_name": (rider_name or "").strip(),
        "sender_name": (sender_name or "").strip(),
        "sender_phone": (sender_phone or "").strip(),
        "amount_ghs": float(amount_ghs) if amount_ghs is not None else None,
        "payment_date": (payment_date or "").strip(),
        "reference": (reference or "").strip(),
        "decided_by": (decided_by or "").strip(),
        "decided_at": _now(),
        "notes": (notes or "").strip(),
    }
    with _LOCK:
        data = _load()
        data[key] = rec
        _save(data)
    return rec


def remove(source_file: str, line_no: int) -> bool:
    """Drop a decision (revert to whatever the reconciler said)."""
    key = _key(source_file, line_no)
    with _LOCK:
        data = _load()
        if key in data:
            del data[key]
            _save(data)
            return True
        return False
