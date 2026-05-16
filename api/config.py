"""Configuration management."""

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
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""  # path to service account JSON
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

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # Scheduler
    SCHEDULER_TIMEZONE: str = "Africa/Accra"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # tolerate frontend vars (NEXT_PUBLIC_*) in shared .env


settings = Settings()
