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
    def __init__(self, service_account_file: str) -> None:
        # Imported lazily so the platform still boots when the deps aren't
        # installed yet or no service account is configured.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

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

    def download_file(self, file_id: str) -> bytes:
        """Download raw bytes for a non-Google native file (e.g., a CSV)."""
        from googleapiclient.http import MediaIoBaseDownload

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
    """Lazy-initialized Drive client. Raises if no service-account file configured."""
    path = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    if not path or not Path(path).exists():
        raise RuntimeError(
            "Google Drive sync needs GOOGLE_SERVICE_ACCOUNT_FILE pointing at a "
            "valid service-account JSON. See docs/google-drive-setup.md."
        )
    return DriveClient(path)
