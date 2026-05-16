"""Daily activities report job — builds xlsx and archives it to Google Drive.

Designed to be called both:
  - On schedule at 18:00 Africa/Accra via APScheduler
  - Manually via POST /api/activities/run-daily for backfills and testing
"""

from __future__ import annotations

import logging
from datetime import date

from api.agents.collections_report.activities_xlsx import write_activities_xlsx
from api.config import settings
from api.storage import activities as activity_store

logger = logging.getLogger(__name__)


def _upload_to_drive(filename: str, payload: bytes) -> dict:
    try:
        from api.integrations.google_drive import get_drive_client

        client = get_drive_client()
        result = client.upload_file(
            folder_id=settings.ACTIVITIES_REPORT_DRIVE_FOLDER_ID,
            filename=filename,
            data=payload,
        )
        logger.info("uploaded %s to Drive: %s", filename, result.get("webViewLink"))
        return {"uploaded": True, **result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("drive upload failed")
        return {"uploaded": False, "reason": str(exc)}


def run_daily_report(report_day: date | None = None) -> dict:
    """Build the daily xlsx and archive it to Google Drive."""
    report_day = report_day or date.today()
    items = activity_store.list_for_day(report_day)
    payload = write_activities_xlsx(report_day, items)

    filename = f"Wahu_Collections_Activities_{report_day.isoformat()}.xlsx"
    drive_result = _upload_to_drive(filename, payload)

    return {
        "day": report_day.isoformat(),
        "activities_count": len(items),
        "unique_riders": len({a.get("customer_id") for a in items if a.get("customer_id")}),
        "xlsx_bytes": len(payload),
        "filename": filename,
        "drive": drive_result,
    }
