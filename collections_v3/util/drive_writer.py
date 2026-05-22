"""Drive write helpers: subfolder resolution, _v{n} versioning, artifact upload.

Lifts the bits from step0_invoices.py into a generalized form so every
step can use them. Spec contract:

  * Never overwrite. If `{filename}` exists in the target folder, append
    `_v{n}` and log a warning. Non-singleton artifacts always go through
    this path.
  * Singletons (`rider_agency_history`, `qb_upload_log`) bypass versioning
    entirely — caller is responsible for appending rows to the existing
    Drive file rather than creating new ones.
"""

from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from typing import Optional

from api.config import settings
from api.integrations.google_drive import DriveClient, DriveFile, get_drive_client
from collections_v3.schemas import RunContext
from collections_v3.util import artifacts as artifact_registry
from collections_v3.util.paths import build_filename, drive_target

logger = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_VERSION_RE = re.compile(r"_v(\d+)\.(?P<ext>[A-Za-z0-9]+)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Subfolder resolution
# ---------------------------------------------------------------------------

def _find_child_folder(
    parent_id: str, name: str, *, client: DriveClient
) -> Optional[DriveFile]:
    """Return the immediate child subfolder with this name, or None."""
    matches = client.list_folder(parent_id, name_contains=name)
    for f in matches:
        if f.mime_type == FOLDER_MIME and f.name == name:
            return f
    return None


def _create_folder(parent_id: str, name: str, *, client: DriveClient) -> str:
    """Create a Drive folder under `parent_id`. Returns the new folder id."""
    body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
    created = (
        client._service.files()
        .create(body=body, fields="id, name", supportsAllDrives=True)
        .execute()
    )
    return created["id"]


def ensure_subfolder(
    parent_id: str, path: str, *, client: Optional[DriveClient] = None
) -> str:
    """Walk `path` ('A/B/C') under `parent_id`, creating folders that don't
    exist. Returns the leaf folder id."""
    client = client or get_drive_client()
    cur = parent_id
    for part in PurePosixPath(path).parts:
        if not part or part == "/":
            continue
        existing = _find_child_folder(cur, part, client=client)
        if existing:
            cur = existing.id
        else:
            logger.info("creating Drive folder %r under %s", part, cur)
            cur = _create_folder(cur, part, client=client)
    return cur


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def next_versioned_filename(
    folder_id: str, base_filename: str, *, client: Optional[DriveClient] = None
) -> str:
    """Find the lowest non-colliding filename in `folder_id`.

    If `{base}.ext` is absent, return it. Otherwise look at every
    `{base}_v{n}.ext` and return `_v{max+1}`.
    """
    client = client or get_drive_client()
    stem, _, ext = base_filename.rpartition(".")
    if not stem:
        # base_filename had no extension — treat the whole thing as stem
        stem = base_filename
        ext = ""

    files = client.list_folder(folder_id, name_contains=stem)
    names = {f.name for f in files if f.mime_type != FOLDER_MIME}
    if base_filename not in names:
        return base_filename

    max_v = 1
    prefix = f"{stem}_v"
    for name in names:
        if not name.startswith(prefix):
            continue
        m = _VERSION_RE.search(name)
        if not m:
            continue
        if ext and m.group("ext").lower() != ext.lower():
            continue
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if n > max_v:
            max_v = n
    return f"{stem}_v{max_v + 1}.{ext}" if ext else f"{stem}_v{max_v + 1}"


# ---------------------------------------------------------------------------
# High-level upload
# ---------------------------------------------------------------------------

def _mime_for_ext(ext: str) -> str:
    return {
        "xlsx": XLSX_MIME,
        "csv": "text/csv",
        "md": "text/markdown",
        "pdf": "application/pdf",
        "iif": "text/plain",  # QuickBooks IIF is plain text
    }.get(ext.lower(), "application/octet-stream")


def upload_artifact(
    artifact: str,
    ctx: RunContext,
    payload: bytes,
    *,
    ext: Optional[str] = None,
    client: Optional[DriveClient] = None,
    root_folder_id: Optional[str] = None,
) -> dict:
    """Place `payload` in Drive at the right subfolder + filename.

    Non-singleton: filename is auto-versioned with `_v{n}` if a collision
    exists. Singleton: caller-managed append; this helper raises so the
    caller doesn't accidentally double-create.
    """
    spec = artifact_registry.get(artifact)
    if spec.singleton:
        raise ValueError(
            f"{artifact!r} is a singleton — use a per-artifact append helper, "
            "not upload_artifact."
        )

    client = client or get_drive_client()
    root = root_folder_id or settings.COLLECTIONS_DRIVE_FOLDER_ID
    base_name = build_filename(artifact, ctx, ext=ext)
    sub_path = drive_target(artifact, ctx)
    target_folder = ensure_subfolder(root, sub_path, client=client)

    final_name = next_versioned_filename(target_folder, base_name, client=client)
    if final_name != base_name:
        logger.warning(
            "Drive collision for %s in %s — uploading as %s",
            base_name, sub_path, final_name,
        )

    return client.upload_file(
        folder_id=target_folder,
        filename=final_name,
        data=payload,
        mime_type=_mime_for_ext(final_name.rpartition(".")[2]),
    )
