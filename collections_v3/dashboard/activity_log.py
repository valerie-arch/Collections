"""Collector activity log — the spec's `agency_activity` data model.

One JSON record per logged action:
    timestamp, agency, collector_id, rider_id, action_type, outcome,
    amount_ghs, notes

`action_type` ∈ {call_placed, sms_sent, in_person_visit,
                 payment_received, promise_to_pay}.

`outcome` is action-type-specific (e.g. `connected | vmail` for calls,
`met | not_in` for visits, ISO date string for promise_to_pay).

Storage is a JSON list at `data/agency_activity.json` (mirrors the
existing pattern in api/storage/activities.py, just under a different
filename + schema).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional


STORE_PATH = Path("data/agency_activity.json")
_LOCK = Lock()

ACTION_TYPES = {
    "call_placed", "sms_sent", "in_person_visit",
    "payment_received", "promise_to_pay",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_all(path: Path = STORE_PATH) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []


def _write_all(items: list[dict], path: Path = STORE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, sort_keys=True))


def _resolve_path(path: Optional[Path]) -> Path:
    """Always look up STORE_PATH at call time so tests can monkeypatch."""
    return path or STORE_PATH


def list_all(path: Optional[Path] = None) -> list[dict]:
    with _LOCK:
        return list(_read_all(_resolve_path(path)))


def log_activity(
    *,
    agency: str,
    collector_id: str,
    rider_id: str,
    action_type: str,
    outcome: str = "",
    amount_ghs: float = 0.0,
    notes: str = "",
    timestamp: Optional[str] = None,
    path: Optional[Path] = None,
) -> dict:
    if action_type not in ACTION_TYPES:
        raise ValueError(
            f"action_type {action_type!r} must be one of {sorted(ACTION_TYPES)}"
        )
    record = {
        "id": uuid.uuid4().hex,
        "timestamp": timestamp or _now_iso(),
        "agency": agency,
        "collector_id": collector_id,
        "rider_id": rider_id,
        "action_type": action_type,
        "outcome": outcome,
        "amount_ghs": round(float(amount_ghs or 0.0), 2),
        "notes": notes,
    }
    resolved = _resolve_path(path)
    with _LOCK:
        items = _read_all(resolved)
        items.append(record)
        _write_all(items, resolved)
    return record
