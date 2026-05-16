"""Google Drive sync endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.agents.drive_sync import LOCAL_DIR, sync_invoices

router = APIRouter()


@router.post("/sync")
def sync_drive() -> dict:
    """Pull all invoice CSVs from the configured Drive folder into local storage."""
    try:
        return sync_invoices()
    except RuntimeError as exc:
        # Misconfiguration — surface as a 400 with the actionable message.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Drive sync failed: {exc}") from exc


@router.get("/status")
def drive_status() -> dict:
    """Show what's currently in the local invoices folder."""
    files = sorted(LOCAL_DIR.glob("*.csv")) if LOCAL_DIR.exists() else []
    return {
        "local_folder": str(LOCAL_DIR),
        "file_count": len(files),
        "total_size_bytes": sum(p.stat().st_size for p in files),
        "files": [
            {
                "name": p.name,
                "size_bytes": p.stat().st_size,
                "modified_at": p.stat().st_mtime,
            }
            for p in files
        ],
    }
