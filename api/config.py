"""Configuration management."""

from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings."""

    # Database
    DATABASE_URL: str = "postgresql://wahu:wahu_collections_2026@localhost:5432/collections"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/auth/callback"

    # Zoho API
    ZOHO_AUTH_TOKEN: str = ""
    ZOHO_ORGANIZATION_ID: str = ""
    ZOHO_BILLING_API_URL: str = "https://www.zohoapis.com/billing/v2"

    # Google Drive — folder holding Zoho invoice CSV exports
    ZOHO_INVOICES_DRIVE_FOLDER_ID: str = "19fd10Y4AZ8evazSh6SKFTurRam-vPYM1"
    # Separate Drive folder for the Zoho subscriptions export — drives the
    # Active/Recovery/Completed status filter on the Reports page.
    ZOHO_SUBSCRIPTIONS_DRIVE_FOLDER_ID: str = "1yjyx07gKnaZteTrYd9elAt26gIvqb3tK"
    # Drive folder holding rider payment files (MoMo / bank / cash statements)
    PAYMENTS_DRIVE_FOLDER_ID: str = "1CJ3gMVNNpr50P5aKy8Y-sA00OC9xFdpD"
    # Zoho payments exports (CSVs of payments received).
    ZOHO_PAYMENTS_DRIVE_FOLDER_ID: str = "1eveM0LJ6aYZtC1uKM3ItcmF1qCx-mv_g"
    # Bolt weekly payout workings root. Contains per-month subfolders, each
    # holding one Google Sheet per ISO-week titled "Bolt Food Payout
    # Workings - [DD/MM/YYYY]" where the date is the Monday AFTER the
    # Mon-Sun work week (i.e. the payout Monday).
    BOLT_DRIVE_FOLDER_ID: str = "1FEjOVkQKJpqp59xsIObnsyifUYHuuyhM"
    # collections_v3 root — pipeline output XLSX files land here.
    COLLECTIONS_DRIVE_FOLDER_ID: str = "0AOTO8CKQDQcBUk9PVA"
    # Bike fleet roster (multi-tab Google Sheet). The TSA tab's Assigned Rider
    # column lists every rider currently on a TSA bike; any billed Zoho
    # customer not in that list is Wahu fleet.
    BIKE_FLEET_SHEET_ID: str = "1f1x38Sfj2QOe07daZ7xSi9cjp-JyUPg6"
    # Collection Assignment Zones. Has the customer-address roster plus two
    # zone tables: West Zone -> Hortta, East Zone -> TSAC. All TSA fleet
    # riders go to TSAC regardless of zone.
    ASSIGNMENT_ZONES_SHEET_ID: str = "1vyhQBVwGgQDCM7A-A_46zMil9cNDUCKK-lFkojSA3Nc"
    # Only reconcile payments dated on or after this — Zoho already has earlier ones.
    PAYMENTS_CUTOFF_DATE: str = "2026-05-14"
    # Either a path to a JSON file (local dev) OR raw JSON content (Railway/prod).
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""
    DRIVE_INVOICE_FILENAME_FILTER: str = "Invoice"  # only sync titles containing this

    # Daily activities report — archived to this Drive folder at 18:00 Africa/Accra
    ACTIVITIES_REPORT_DRIVE_FOLDER_ID: str = "13PU67g1GtMxU4QYZ2Mg-OieopSbzm-mZ"
    ACTIVITIES_REPORT_HOUR: int = 18  # 6pm Africa/Accra

    # Hubtel SMS
    HUBTEL_API_KEY: str = ""
    HUBTEL_CLIENT_ID: str = ""

    # QuickBooks
    QUICKBOOKS_REALM_ID: str = ""
    QUICKBOOKS_AUTH_TOKEN: str = ""

    # Storage
    STORAGE_BACKEND: str = "filesystem"  # or "s3"
    STORAGE_PATH: str = "./collections_data"

    # FastAPI
    DEBUG: bool = True
    SECRET_KEY: str = "dev-secret-key"

    # CORS — accepts a comma-separated list from the CORS_ORIGINS env var,
    # e.g. "http://localhost:3000,https://collections.wahu.me"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    # Scheduler
    SCHEDULER_TIMEZONE: str = "Africa/Accra"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # tolerate frontend vars (NEXT_PUBLIC_*) in shared .env


settings = Settings()
