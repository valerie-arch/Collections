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


def _subs_canonical_name(drive_file: DriveFile) -> str:
    """Canonical filename for a synced subscriptions CSV.

    The report loader globs `zoho_subscriptions*.csv` and takes the last
    one alphabetically. Drive files are typically named "Subscriptions (3).csv"
    or similar, which don't match. We rewrite to a sortable, glob-matching
    name keyed by Drive modifiedTime so the freshest export wins on sort.
    """
    stamp = (drive_file.modified_time or "").replace(":", "").replace(".", "_")
    return f"zoho_subscriptions_{stamp or drive_file.id}.csv"


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
                target = SUBS_LOCAL_DIR / _subs_canonical_name(f)
                if state.get(f.id) == f.modified_time and target.exists():
                    skipped.append(f.name)
                    continue
                logger.info("downloading subscription %s (%s)", f.name, f.mime_type)
                try:
                    data, _ = _fetch(f)
                except Exception as e:
                    logger.exception("failed to download subscription %s: %s", f.name, e)
                    subs_error = f"download failed for {f.name}: {e}"
                    continue
                target.write_bytes(data)
                state[f.id] = f.modified_time
                downloaded.append(target.name)
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
FOLDER_MIME = "application/vnd.google-apps.folder"


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


_PAYMENT_ACCEPTED_MIME = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # some MoMo exports get tagged this way
    GOOGLE_SHEET_MIME,
}


def _walk_payment_files(
    client, folder_id: str, *, depth: int = 0, max_depth: int = 3,
    prefix: str = "",
) -> list[tuple]:
    """Walk a Drive folder for payment files, recursing into subfolders.

    Yields (drive_file, prefix_path) so files in subfolders like
    'Payments/MTN/file.csv' get a prefix 'MTN_' applied to their saved
    local filename — preserves channel attribution AND avoids collisions
    when two channels have files with the same name.

    Defensive: if list_folder fails on a subfolder (service-account perms
    glitch, network blip), we log and continue rather than aborting the
    whole sync.
    """
    if depth > max_depth:
        return []
    out: list[tuple] = []
    try:
        children = client.list_folder(folder_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "list_folder failed for %s (depth=%d): %s",
            folder_id, depth, e,
        )
        return out
    for f in children:
        if f.mime_type == FOLDER_MIME:
            sub_prefix = f"{prefix}{_safe_filename(f.name)}_"
            out.extend(_walk_payment_files(
                client, f.id, depth=depth + 1, max_depth=max_depth,
                prefix=sub_prefix,
            ))
            continue
        is_payment = (
            f.mime_type in _PAYMENT_ACCEPTED_MIME
            or f.name.lower().endswith((".csv", ".xlsx", ".xls"))
        )
        if is_payment:
            out.append((f, prefix))
    return out


def sync_payments(folder_id: Optional[str] = None) -> dict:
    """Pull every payment file from the payments Drive folder.

    Walks subfolders one level deep so a Payments/{MTN,Telecel,Bank,Cash}
    layout is handled correctly. Subfolder names are prepended to the
    local filename (e.g. `MTN_<name>.csv`) to preserve channel context
    and avoid collisions between identically-named files.

    Accepts CSV, XLSX, and native Google Sheets (exported as CSV).
    """
    folder_id = folder_id or settings.PAYMENTS_DRIVE_FOLDER_ID
    PAYMENTS_LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    client = get_drive_client()
    walked = _walk_payment_files(client, folder_id)

    state = _load_payments_state()
    downloaded: list[str] = []
    skipped: list[str] = []

    for f, prefix in walked:
        cache_key = f.modified_time
        # Compute the target name early so the skip check uses the same
        # filename that download would write.
        target_name = f.name if f.mime_type != GOOGLE_SHEET_MIME else (
            f.name if f.name.lower().endswith(".csv") else f.name + ".csv"
        )
        target_name = prefix + target_name
        local_path = PAYMENTS_LOCAL_DIR / _safe_filename(target_name)

        if state.get(f.id) == cache_key and local_path.exists():
            skipped.append(target_name)
            continue
        logger.info(
            "downloading payment file %s (%s) -> %s",
            f.name, f.mime_type, target_name,
        )
        try:
            data, raw_name = _download_payment_file(client, f)
        except Exception as e:
            logger.exception("failed to download %s: %s", f.name, e)
            continue
        # _download_payment_file returns the raw name; we use our prefixed
        # version for the local path so subfolder context survives.
        local_path.write_bytes(data)
        state[f.id] = cache_key
        downloaded.append(target_name)

    _save_payments_state(state)

    return {
        "folder_id": folder_id,
        "total": len(walked),
        "downloaded": downloaded,
        "skipped": skipped,
    }
