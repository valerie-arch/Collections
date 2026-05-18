"""Suspense reconciliation queue — JSON-backed store.

When a payment lands in MoMo/Hero/Telecel/cash without a clear rider link,
finance officers create a suspense entry here. The platform helps surface
candidate riders to match against. Resolutions are recorded for audit.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

STORE_PATH = Path("data/suspense.json")
_LOCK = Lock()


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _load() -> dict:
    if not STORE_PATH.exists():
        return {}
    try:
        return json.loads(STORE_PATH.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))


def list_items(status: Optional[str] = None) -> list[dict]:
    with _LOCK:
        items = list(_load().values())
    # Migrate legacy "escalated" → "booked" on read.
    for i in items:
        if i.get("status") == "escalated":
            i["status"] = "booked"
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda i: (i.get("status") != "open", i.get("received_at", ""), i.get("created_at", "")), reverse=True)
    return items


def get(item_id: str) -> Optional[dict]:
    return _load().get(item_id)


def find_by_source_key(source_key: str) -> Optional[dict]:
    """Return the existing suspense item matching a source_key, or None."""
    if not source_key:
        return None
    with _LOCK:
        for rec in _load().values():
            if rec.get("source_key") == source_key:
                return rec
    return None


def create(
    *,
    channel: str,
    channel_reference: str,
    amount_ghs: float,
    received_at: str,
    msisdn: Optional[str] = None,
    note: Optional[str] = None,
    source_key: Optional[str] = None,
) -> dict:
    """Create a new suspense item.

    If `source_key` is provided and an existing item already carries it,
    return that existing item instead of creating a duplicate. This is how
    repeated runs of the Payments reconcile flow stay idempotent.
    """
    if amount_ghs <= 0:
        raise ValueError("amount_ghs must be positive")
    if not channel_reference.strip():
        raise ValueError("channel_reference required")

    key = (source_key or "").strip() or None
    if key is not None:
        existing = find_by_source_key(key)
        if existing is not None:
            return existing

    with _LOCK:
        data = _load()
        # Double-check inside the lock to close the race window.
        if key is not None:
            for rec in data.values():
                if rec.get("source_key") == key:
                    return rec
        sid = uuid.uuid4().hex
        rec = {
            "id": sid,
            "channel": channel.strip().lower(),
            "channel_reference": channel_reference.strip(),
            "msisdn": (msisdn or "").strip() or None,
            "amount_ghs": round(float(amount_ghs), 2),
            "received_at": received_at,
            "status": "open",
            "note": (note or "").strip() or None,
            "resolved_rider_id": None,
            "resolved_rider_name": None,
            "resolved_invoice_number": None,
            "resolved_at": None,
            "resolution_note": None,
            "source_key": key,
            "created_at": _now(),
        }
        data[sid] = rec
        _save(data)
        return rec


def resolve(
    item_id: str,
    *,
    rider_id: str,
    rider_name: Optional[str] = None,
    invoice_number: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    with _LOCK:
        data = _load()
        if item_id not in data:
            raise KeyError(item_id)
        rec = data[item_id]
        rec["status"] = "resolved"
        rec["resolved_rider_id"] = rider_id.strip()
        rec["resolved_rider_name"] = (rider_name or "").strip() or None
        rec["resolved_invoice_number"] = (invoice_number or "").strip() or None
        rec["resolution_note"] = (note or "").strip() or None
        rec["resolved_at"] = _now()
        _save(data)
        return rec


def book_to_suspense_account(item_id: str, note: Optional[str] = None) -> dict:
    """Park the payment in the accounting suspense account — acknowledged
    receipt with no rider/invoice match yet. Equivalent to 'GL: suspense'."""
    with _LOCK:
        data = _load()
        if item_id not in data:
            raise KeyError(item_id)
        data[item_id]["status"] = "booked"
        if note:
            data[item_id]["resolution_note"] = note.strip()
        _save(data)
        return data[item_id]


# Backward-compat alias for any existing callers.
escalate = book_to_suspense_account


def reopen(item_id: str) -> dict:
    with _LOCK:
        data = _load()
        if item_id not in data:
            raise KeyError(item_id)
        data[item_id]["status"] = "open"
        data[item_id]["resolved_rider_id"] = None
        data[item_id]["resolved_rider_name"] = None
        data[item_id]["resolved_invoice_number"] = None
        data[item_id]["resolved_at"] = None
        _save(data)
        return data[item_id]


def delete(item_id: str) -> bool:
    with _LOCK:
        data = _load()
        if item_id in data:
            del data[item_id]
            _save(data)
            return True
        return False
