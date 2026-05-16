"""Drive sync agent — pulls Zoho invoice CSVs from a Drive folder into local storage.

Idempotent: skips files whose modifiedTime matches the cached version on disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from api.config import settings
from api.integrations.google_drive import DriveFile, get_drive_client

logger = logging.getLogger(__name__)

LOCAL_DIR = Path("sample_inputs/zoho/invoices")
STATE_FILE = LOCAL_DIR / ".sync_state.json"


def _safe_filename(name: str) -> str:
    return name.replace("/", "_").replace(" ", "_")


def _load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict[str, str]) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def sync_invoices(
    folder_id: Optional[str] = None, name_contains: Optional[str] = None
) -> dict:
    """Pull every CSV from the configured Drive folder into LOCAL_DIR.

    Returns a summary dict: {downloaded, skipped, total, files}.
    """
    folder_id = folder_id or settings.ZOHO_INVOICES_DRIVE_FOLDER_ID
    name_contains = name_contains or settings.DRIVE_INVOICE_FILENAME_FILTER

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    client = get_drive_client()
    files = client.list_folder(folder_id, name_contains=name_contains)
    files = [f for f in files if f.mime_type == "text/csv"]

    state = _load_state()
    downloaded: list[str] = []
    skipped: list[str] = []

    for f in files:
        local_path = LOCAL_DIR / _safe_filename(f.name)
        if state.get(f.id) == f.modified_time and local_path.exists():
            skipped.append(f.name)
            continue
        logger.info("downloading %s (%s bytes)", f.name, f.size_bytes)
        data = client.download_file(f.id)
        local_path.write_bytes(data)
        state[f.id] = f.modified_time
        downloaded.append(f.name)

    _save_state(state)

    return {
        "folder_id": folder_id,
        "filter": name_contains,
        "total": len(files),
        "downloaded": downloaded,
        "skipped": skipped,
    }
