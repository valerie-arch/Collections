"""Pydantic schemas for the v3 pipeline.

These mirror the canonical record shapes used between steps. They're not
the *source* file schemas (those live as alias maps inside each io_/ loader)
— they're the post-normalisation shapes we agreed on at the package level.

Filters / RunContext are also here so every step takes a single, typed
ctx object instead of a bag of kwargs.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class Fleet(str, Enum):
    Wahu = "Wahu"
    TSA = "TSA"
    All = "All"


class Agency(str, Enum):
    TSAC = "TSAC"
    Hortta = "Hortta"
    Unassigned = "Unassigned"
    All = "All"


class Period(str, Enum):
    Week = "Week"
    MTD = "MTD"
    Lifetime = "Lifetime"
    Custom = "Custom"


class RunContext(BaseModel):
    """One per `collections run` invocation. Passed to every step."""

    model_config = ConfigDict(use_enum_values=True)

    fleet: Fleet = Fleet.All
    agency: Agency = Agency.All
    period: Period = Period.Week
    # Resolved window — populated by the CLI from `period` (+ --start/--end
    # for Custom). Lifetime leaves these None.
    start: Optional[date] = None
    end: Optional[date] = None
    # Bookkeeping for the run.
    run_started_at: datetime = Field(default_factory=datetime.utcnow)
    operator: str = "cli"
    drive_folder_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Canonical record shapes
# ---------------------------------------------------------------------------

class InvoiceRecord(BaseModel):
    """One row per Zoho invoice, post-aggregation. Output of step0 and
    consumed by step1+ downstream."""

    invoice_id: str
    invoice_number: str
    customer_id_zoho: str
    rider_id: str            # Customer Number (CUS-NNN)
    rider_name: str
    invoice_date: Optional[date]
    due_date: Optional[date]
    status: str              # lowercased
    amount: Decimal
    amount_due: Decimal
    fleet: str               # Wahu | TSA
    agency: str              # TSAC | Hortta | Unassigned
    area: str = ""           # area/address used for the agency lookup
    source_file: str = ""


class ReceiptRecord(BaseModel):
    """One row per inbound payment receipt (MoMo / Telecel / bank)."""

    txn_id: str
    source: str              # "mtn" | "telecel" | "bank"
    date: date
    amount: Decimal
    sender_name: str = ""
    sender_phone: str = ""
    sender_account: str = ""
    narration: str = ""


class MatchedPayment(BaseModel):
    txn_id: str
    rider_id: str
    invoice_id: str
    applied_amount: Decimal
    match_tier: str          # PHONE | NAME | REF | ALREADY_IN_ZOHO


class SuspenseItem(BaseModel):
    txn_id: str
    date: date
    amount: Decimal
    source: str
    days_in_suspense: int = 0
    assigned_rider_id: Optional[str] = None
