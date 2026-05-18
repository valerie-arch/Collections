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


SUBS_LOCAL_DIR = Path("sample_inputs/zoho")  # subscription CSVs land here


def sync_invoices(
    folder_id: Optional[str] = None, name_contains: Optional[str] = None
) -> dict:
    """Pull invoice CSVs from the invoices folder, AND the subscription CSV
    from the separate subscriptions folder.

    Two folders because that's how the user organises Drive:
      - ZOHO_INVOICES_DRIVE_FOLDER_ID: invoice exports
      - ZOHO_SUBSCRIPTIONS_DRIVE_FOLDER_ID: the per-rider Subscription Status
        export (drives the Active/Recovery/Completed filter).
    """
    inv_folder = folder_id or settings.ZOHO_INVOICES_DRIVE_FOLDER_ID
    name_contains = name_contains or settings.DRIVE_INVOICE_FILENAME_FILTER

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    SUBS_LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    client = get_drive_client()

    state = _load_state()
    downloaded: list[str] = []
    skipped: list[str] = []

    def _accept(f) -> bool:
        return (
            f.mime_type == "text/csv"
            or f.mime_type == GOOGLE_SHEET_MIME
            or f.name.lower().endswith(".csv")
        )

    def _fetch(f) -> tuple[bytes, str]:
        if f.mime_type == GOOGLE_SHEET_MIME:
            data = client.download_file(f.id, export_mime="text/csv")
            name = f.name if f.name.lower().endswith(".csv") else f.name + ".csv"
            return data, name
        return client.download_file(f.id), f.name

    # ---- 1) invoice folder
    inv_files = client.list_folder(inv_folder, name_contains=name_contains)
    inv_files = [f for f in inv_files if _accept(f)]
    for f in inv_files:
        if state.get(f.id) == f.modified_time:
            existing = LOCAL_DIR / _safe_filename(f.name if not f.mime_type == GOOGLE_SHEET_MIME or f.name.lower().endswith(".csv") else f.name + ".csv")
            if existing.exists():
                skipped.append(f.name)
                continue
        logger.info("downloading invoice %s (%s)", f.name, f.mime_type)
        try:
            data, name = _fetch(f)
        except Exception as e:
            logger.exception("failed to download invoice %s: %s", f.name, e)
            continue
        (LOCAL_DIR / _safe_filename(name)).write_bytes(data)
        state[f.id] = f.modified_time
        downloaded.append(name)

    # ---- 2) subscriptions folder (separate Drive folder)
    subs_folder = settings.ZOHO_SUBSCRIPTIONS_DRIVE_FOLDER_ID
    subs_count = 0
    subs_error: Optional[str] = None
    if subs_folder:
        try:
            subs_files = client.list_folder(subs_folder)
            subs_files = [f for f in subs_files if _accept(f)]
            if not subs_files:
                subs_error = (
                    f"Subscriptions folder {subs_folder} listed 0 CSV/Sheet files. "
                    "Check the folder ID and that the file is a CSV or Google Sheet."
                )
            for f in subs_files:
                if state.get(f.id) == f.modified_time:
                    existing = SUBS_LOCAL_DIR / _safe_filename(f.name if not f.mime_type == GOOGLE_SHEET_MIME or f.name.lower().endswith(".csv") else f.name + ".csv")
                    if existing.exists():
                        skipped.append(f.name)
                        continue
                logger.info("downloading subscription %s (%s)", f.name, f.mime_type)
                try:
                    data, name = _fetch(f)
                except Exception as e:
                    logger.exception("failed to download subscription %s: %s", f.name, e)
                    subs_error = f"download failed for {f.name}: {e}"
                    continue
                (SUBS_LOCAL_DIR / _safe_filename(name)).write_bytes(data)
                state[f.id] = f.modified_time
                downloaded.append(name)
            subs_count = len(subs_files)
        except Exception as e:
            # Most common cause: folder not shared with the service account.
            # Surface the message so it shows up in the UI.
            subs_error = (
                f"Subscriptions folder {subs_folder} not accessible: {e}. "
                "Make sure that folder is shared with the service-account email."
            )
            logger.warning(subs_error)

    _save_state(state)

    return {
        "folder_id": inv_folder,
        "subscriptions_folder_id": subs_folder,
        "subscriptions_synced": subs_count,
        "subscriptions_error": subs_error,
        "filter": name_contains,
        "total": len(inv_files) + subs_count,
        "downloaded": downloaded,
        "skipped": skipped,
    }


# ----- Payment statements (MoMo / bank / cash) -----

PAYMENTS_LOCAL_DIR = Path("sample_inputs/payments")
PAYMENTS_STATE_FILE = PAYMENTS_LOCAL_DIR / ".sync_state.json"


def _load_payments_state() -> dict[str, str]:
    if not PAYMENTS_STATE_FILE.exists():
        return {}
    try:
        return json.loads(PAYMENTS_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_payments_state(state: dict[str, str]) -> None:
    PAYMENTS_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    PAYMENTS_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def _download_payment_file(client, drive_file) -> tuple[bytes, str]:
    """Download a Drive file's bytes + the local filename we should save it as.

    Google Sheets get exported as CSV with a .csv extension. Uploaded CSV/XLSX
    are saved verbatim.
    """
    name = drive_file.name
    if drive_file.mime_type == GOOGLE_SHEET_MIME:
        data = client.download_file(drive_file.id, export_mime="text/csv")
        if not name.lower().endswith(".csv"):
            name = name + ".csv"
        return data, name
    data = client.download_file(drive_file.id)
    return data, name


def sync_payments(folder_id: Optional[str] = None) -> dict:
    """Pull every payment file from the payments Drive folder.

    Accepts CSV, XLSX, AND native Google Sheets (exported as CSV).
    """
    folder_id = folder_id or settings.PAYMENTS_DRIVE_FOLDER_ID
    PAYMENTS_LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    client = get_drive_client()
    files = client.list_folder(folder_id)

    accepted_mime = {
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",  # some MoMo exports get tagged this way
        GOOGLE_SHEET_MIME,
    }
    files = [
        f for f in files
        if f.mime_type in accepted_mime
        or f.name.lower().endswith((".csv", ".xlsx", ".xls"))
    ]

    state = _load_payments_state()
    downloaded: list[str] = []
    skipped: list[str] = []

    for f in files:
        # For Google Sheets we use modifiedTime to detect changes since the
        # exported bytes differ run-to-run.
        cache_key = f.modified_time
        if state.get(f.id) == cache_key:
            target_name = f.name if f.mime_type != GOOGLE_SHEET_MIME else (
                f.name if f.name.lower().endswith(".csv") else f.name + ".csv"
            )
            if (PAYMENTS_LOCAL_DIR / _safe_filename(target_name)).exists():
                skipped.append(f.name)
                continue
        logger.info("downloading payment file %s (%s)", f.name, f.mime_type)
        try:
            data, target_name = _download_payment_file(client, f)
        except Exception as e:
            logger.exception("failed to download %s: %s", f.name, e)
            continue
        local_path = PAYMENTS_LOCAL_DIR / _safe_filename(target_name)
        local_path.write_bytes(data)
        state[f.id] = cache_key
        downloaded.append(target_name)

    _save_payments_state(state)

    return {
        "folder_id": folder_id,
        "total": len(files),
        "downloaded": downloaded,
        "skipped": skipped,
    }
