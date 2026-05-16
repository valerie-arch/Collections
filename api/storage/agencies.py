"""3rd-party collections agency assignments — JSON-backed.

Lightweight file store: a single JSON map {customer_id: {agency, assigned_at, note}}.
This will move to Postgres later, but a JSON file is enough to ship the UI
without a migration today.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

STORE_PATH = Path("data/agency_assignments.json")
_LOCK = Lock()

# Canonical list — only these two agencies are accepted.
ALLOWED_AGENCIES = ("Hortta", "TSAC")


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


def list_assignments() -> dict:
    """Return the full {customer_id: {agency, assigned_at, note}} map."""
    with _LOCK:
        return _load()


def agency_map() -> dict[str, str]:
    """Return {customer_id: agency_name} for engine use."""
    return {cid: rec["agency"] for cid, rec in list_assignments().items() if rec.get("agency")}


def known_agencies() -> list[str]:
    """Always return the canonical list so filters work even before any
    assignments exist."""
    return list(ALLOWED_AGENCIES)


def assign(customer_id: str, agency: str, note: Optional[str] = None) -> dict:
    if not customer_id or not agency:
        raise ValueError("customer_id and agency are required")
    agency = agency.strip()
    if agency not in ALLOWED_AGENCIES:
        raise ValueError(
            f"agency must be one of: {', '.join(ALLOWED_AGENCIES)}"
        )
    with _LOCK:
        data = _load()
        data[customer_id] = {
            "agency": agency,
            "assigned_at": datetime.utcnow().isoformat() + "Z",
            "note": (note or "").strip() or None,
        }
        _save(data)
        return data[customer_id]


def unassign(customer_id: str) -> bool:
    with _LOCK:
        data = _load()
        if customer_id in data:
            del data[customer_id]
            _save(data)
            return True
        return False
