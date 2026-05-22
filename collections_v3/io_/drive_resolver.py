"""Resolve Drive source files by name pattern, picking the latest modifiedTime.

The spec forbids hard-coding file IDs — file content is replaced by the
business over time, so each loader names its expected file via a substring
pattern and we resolve the most-recently-modified match at run time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from api.integrations.google_drive import DriveClient, DriveFile, get_drive_client


GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
ACCEPTED_TABULAR_MIMES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # some statement exports get tagged this way
    GOOGLE_SHEET_MIME,
}


@dataclass
class ResolvedFile:
    """One Drive file plus the bytes we downloaded for it."""

    drive_file: DriveFile
    content: bytes
    # The filename we should treat this as locally (Sheets get .csv).
    effective_name: str
    # MIME of the bytes we got (after any export). CSV/XLSX/etc.
    effective_mime: str


class DriveSourceMissing(Exception):
    """Raised when no file in the given folder matches the name pattern."""


def _is_tabular(f: DriveFile) -> bool:
    if f.mime_type in ACCEPTED_TABULAR_MIMES:
        return True
    return f.name.lower().endswith((".csv", ".xlsx", ".xls"))


def _matches(f: DriveFile, name_contains: str) -> bool:
    return name_contains.lower() in f.name.lower()


def resolve_latest(
    folder_id: str,
    name_contains: str,
    *,
    client: Optional[DriveClient] = None,
) -> ResolvedFile:
    """Pick the latest-modifiedTime tabular file in `folder_id` matching
    `name_contains`. Download it (exporting Google Sheets as CSV)."""
    client = client or get_drive_client()
    candidates = [
        f for f in client.list_folder(folder_id, name_contains=name_contains)
        if _is_tabular(f) and _matches(f, name_contains)
    ]
    if not candidates:
        raise DriveSourceMissing(
            f"No tabular file containing '{name_contains}' found in Drive "
            f"folder {folder_id}. Check the filename and that the folder is "
            f"shared with the service account."
        )
    candidates.sort(key=lambda f: f.modified_time, reverse=True)
    chosen = candidates[0]

    if chosen.mime_type == GOOGLE_SHEET_MIME:
        data = client.download_file(chosen.id, export_mime="text/csv")
        name = chosen.name if chosen.name.lower().endswith(".csv") else chosen.name + ".csv"
        return ResolvedFile(
            drive_file=chosen,
            content=data,
            effective_name=name,
            effective_mime="text/csv",
        )

    data = client.download_file(chosen.id)
    return ResolvedFile(
        drive_file=chosen,
        content=data,
        effective_name=chosen.name,
        effective_mime=chosen.mime_type or "",
    )


def list_matching(
    folder_id: str,
    name_contains: str,
    *,
    client: Optional[DriveClient] = None,
) -> list[DriveFile]:
    """List (do not download) all files in a folder matching a name substring."""
    client = client or get_drive_client()
    return [
        f for f in client.list_folder(folder_id, name_contains=name_contains)
        if _matches(f, name_contains)
    ]
