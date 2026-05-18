"""Google Drive client backed by a service-account JSON.

Setup: see docs/google-drive-setup.md. The service account email needs to be
added (View permission is enough) to the Drive folder so list/download work.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from api.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: str
    size_bytes: int


class DriveClient:
    def __init__(self, *, service_account_file: str = "", service_account_info: Optional[dict] = None) -> None:
        # Imported lazily so the platform still boots when the deps aren't
        # installed yet or no service account is configured.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        if service_account_info:
            creds = service_account.Credentials.from_service_account_info(
                service_account_info, scopes=SCOPES
            )
        else:
            creds = service_account.Credentials.from_service_account_file(
                service_account_file, scopes=SCOPES
            )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_folder(
        self, folder_id: str, *, name_contains: Optional[str] = None
    ) -> list[DriveFile]:
        """List non-trashed files in a folder. Optionally filter by name substring."""
        q_parts = [f"'{folder_id}' in parents", "trashed = false"]
        if name_contains:
            # Escape single quotes for the Drive query language.
            safe = name_contains.replace("'", "\\'")
            q_parts.append(f"name contains '{safe}'")
        query = " and ".join(q_parts)

        files: list[DriveFile] = []
        page_token: Optional[str] = None
        while True:
            resp = (
                self._service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                    pageSize=100,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            for f in resp.get("files", []):
                files.append(
                    DriveFile(
                        id=f["id"],
                        name=f["name"],
                        mime_type=f.get("mimeType", ""),
                        modified_time=f.get("modifiedTime", ""),
                        size_bytes=int(f.get("size", 0) or 0),
                    )
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return files

    def download_file(self, file_id: str, *, export_mime: Optional[str] = None) -> bytes:
        """Download a Drive file.

        For non-Google native files (CSV/XLSX uploaded as-is) leaves export_mime
        as None — uses get_media. For Google native files (Sheets/Docs/Slides)
        pass an export_mime like "text/csv" — uses export_media.
        """
        from googleapiclient.http import MediaIoBaseDownload

        if export_mime:
            request = self._service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = self._service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def upload_file(
        self,
        *,
        folder_id: str,
        filename: str,
        data: bytes,
        mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ) -> dict:
        """Upload bytes into a Drive folder. Returns {id, name, webViewLink}."""
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
        body = {"name": filename, "parents": [folder_id]}
        created = (
            self._service.files()
            .create(
                body=body,
                media_body=media,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return created


@lru_cache(maxsize=1)
def get_drive_client() -> DriveClient:
    """Lazy-initialized Drive client.

    Prefers GOOGLE_SERVICE_ACCOUNT_JSON (raw JSON string from env, for hosted
    environments like Railway). Falls back to GOOGLE_SERVICE_ACCOUNT_FILE
    (filesystem path, used in local dev).
    """
    import json

    raw = (settings.GOOGLE_SERVICE_ACCOUNT_JSON or "").strip()
    if raw:
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}"
            ) from e
        return DriveClient(service_account_info=info)

    path = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    if path and Path(path).exists():
        return DriveClient(service_account_file=path)

    raise RuntimeError(
        "Google Drive sync needs either GOOGLE_SERVICE_ACCOUNT_JSON (raw JSON, "
        "for hosted envs) or GOOGLE_SERVICE_ACCOUNT_FILE (path to a JSON file, "
        "for local dev). See docs/google-drive-setup.md."
    )
