"""Collections activity log — JSON-backed store.

One record per action taken on a rider. Replaces the manual log that used
to live in Wahu OS. Fields:

- id: uuid
- customer_id, customer_name
- action: phone_call | immobilisation_request | call_to_guarantor |
          remobilisation_request | house_visit | ebike_recovery |
          legal_action_taken | legal_action_update | to_be_written_off | other
- note: free text, REQUIRED
- actor: who took the action (TODO: pull from auth once wired)
- created_at: UTC ISO timestamp (server-set)
- agency: snapshot of the rider's agency assignment at time of action (or null)
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

STORE_PATH = Path("data/activities.json")
_LOCK = Lock()

ACTIONS = (
    "phone_call",
    "immobilisation_request",
    "call_to_guarantor",
    "remobilisation_request",
    "house_visit",
    "ebike_recovery",
    "legal_action_taken",
    "legal_action_update",
    "to_be_written_off",
    "other",
)


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


def list_all() -> list[dict]:
    with _LOCK:
        items = list(_load().values())
    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    return items


def list_for_day(day: date) -> list[dict]:
    """All activities whose created_at falls on the given UTC date."""
    prefix = day.isoformat()
    return [a for a in list_all() if (a.get("created_at") or "").startswith(prefix)]


def list_filtered(
    *,
    customer_id: Optional[str] = None,
    action: Optional[str] = None,
    agency: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
) -> list[dict]:
    items = list_all()
    if customer_id:
        items = [i for i in items if i.get("customer_id") == customer_id]
    if action:
        items = [i for i in items if i.get("action") == action]
    if agency:
        if agency == "Unassigned":
            items = [i for i in items if not i.get("agency")]
        else:
            items = [i for i in items if i.get("agency") == agency]
    if since:
        items = [i for i in items if (i.get("created_at") or "") >= since.isoformat()]
    if until:
        # Inclusive end-of-day
        end_iso = (until.isoformat() + "T23:59:59Z")
        items = [i for i in items if (i.get("created_at") or "") <= end_iso]
    return items


def create(
    *,
    customer_id: str,
    customer_name: str,
    action: str,
    note: str,
    actor: Optional[str] = None,
    agency: Optional[str] = None,
) -> dict:
    if not customer_id.strip():
        raise ValueError("customer_id required")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(ACTIONS)}")
    if not note.strip():
        raise ValueError("note is required — every action must have a written note")

    with _LOCK:
        data = _load()
        aid = uuid.uuid4().hex
        rec = {
            "id": aid,
            "customer_id": customer_id.strip(),
            "customer_name": customer_name.strip(),
            "action": action,
            "note": note.strip(),
            "actor": (actor or "").strip() or "collections-officer",
            "agency": (agency or "").strip() or None,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        data[aid] = rec
        _save(data)
        return rec


def delete(activity_id: str) -> bool:
    with _LOCK:
        data = _load()
        if activity_id in data:
            del data[activity_id]
            _save(data)
            return True
        return False
