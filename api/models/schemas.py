"""Pydantic schemas for Wahu Collections data pipeline."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field, EmailStr


# ============ Enums ============

class RiderStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CHURNED = "churned"


class PaymentChannel(str, Enum):
    MTN = "mtn"
    TELECEL = "telecel"
    HERO = "hero"
    BOLT = "bolt_deduction"
    SUSPENSE = "suspense"


class Fleet(str, Enum):
    WAHU = "Wahu"
    TSA = "TSA"


class InvoiceStatus(str, Enum):
    OPEN = "Open"
    PARTIALLY_PAID = "Partially Paid"
    PAID = "Paid"
    OVERDUE = "Overdue"
    VOID = "Void"


# ============ Input File Schemas ============

class MtnMerchantRow(BaseModel):
    """MTN MoMo daily merchant transaction."""
    merchant_reference: str = Field(..., alias="merchant_ref")
    msisdn: str
    amount: float
    timestamp: str
    transaction_id: Optional[str] = None
    status: str = "completed"

    class Config:
        populate_by_name = True


class TelecelMerchantRow(BaseModel):
    """Telecel MoMo daily merchant transaction."""
    merchant_reference: str = Field(..., alias="merchant_ref")
    msisdn: str
    amount: float
    timestamp: str
    transaction_id: Optional[str] = None
    status: str = "completed"

    class Config:
        populate_by_name = True


class HeroAppRow(BaseModel):
    """Wahu Hero app daily transaction."""
    hero_transaction_id: str
    rider_id: str
    amount: float
    timestamp: str
    status: str = "completed"


class BikeInventoryRow(BaseModel):
    """Wahu OS bike assignment (Slot 4, dropped from MVP)."""
    bike_id: str
    rider_id: str
    assignment_date: date
    status: str


class RiderMasterRow(BaseModel):
    """Wahu OS rider master (Slot 6, dropped from MVP)."""
    rider_id: str
    name: str
    msisdn: str
    status: str
    bike_id: Optional[str] = None


class ZohoInvoiceRow(BaseModel):
    """Zoho Billing invoice export (Slot 5)."""
    invoice_id: str
    rider_id: str
    subscription_id: str
    invoice_date: date
    due_date: date
    amount_invoiced: float
    amount_paid_to_date: float
    balance_outstanding: float
    status: InvoiceStatus
    org_tag: Optional[Fleet] = Fleet.WAHU

    @property
    def days_past_due(self) -> int:
        if self.status in [InvoiceStatus.PAID, InvoiceStatus.VOID]:
            return 0
        return (date.today() - self.due_date).days


class ZohoPaymentPlanRow(BaseModel):
    """Zoho Subscriptions export (Slot 5) — load-bearing for billing & completion."""
    subscription_id: str
    customer_id: str
    customer_name: str
    customer_email: str
    plan_name: str
    period: Literal["weeks", "months"]
    repeats_every: int
    period_bill_ghs: float
    total_billing_cycles: int
    cycles_billed_to_date: int
    remaining_cycles: int
    status: Literal["live", "paused", "expired", "cancelled"]
    start_date: date
    paused_date: Optional[date] = None
    last_billing_date: Optional[date] = None
    last_invoice_id: Optional[str] = None
    tsa_flag: Optional[str] = None

    @property
    def weekly_bill_ghs(self) -> float:
        """SOP §3: weekly bill = period_bill_ghs (if weekly), or period_bill_ghs/4.33 (if monthly)."""
        if self.period == "weeks":
            return self.period_bill_ghs
        else:
            return self.period_bill_ghs / 4.33

    @property
    def daily_rate_ghs(self) -> float:
        """SOP §3: daily_rate = weekly_bill / 6 (for pro-rata maintenance billing)."""
        return self.weekly_bill_ghs / 6.0

    @property
    def weeks_remaining(self) -> int:
        if self.period == "weeks":
            return self.remaining_cycles
        else:
            return int(self.remaining_cycles * 4.33)

    @property
    def rider_status_sop(self) -> RiderStatus:
        """SOP §2-3: map Zoho status to SOP status."""
        mapping = {
            "live": RiderStatus.ACTIVE,
            "paused": RiderStatus.PAUSED,
            "expired": RiderStatus.COMPLETED,
            "cancelled": RiderStatus.CHURNED,
        }
        return mapping[self.status]

    @property
    def is_paid_ahead(self) -> bool:
        """SOP §3: rider has credit balance (computed from invoice ledger)."""
        return False  # Placeholder; computed at invoice level in Step 1

    @property
    def meets_completion(self) -> bool:
        """SOP §7.6: rider ready for Completed transition."""
        return self.remaining_cycles == 0 and self.cycles_billed_to_date == self.total_billing_cycles

    @property
    def fleet(self) -> Fleet:
        """SOP §2: fleet from tsa_flag. Blank/None = Wahu Fleet."""
        if self.tsa_flag and self.tsa_flag.upper() == "TSA":
            return Fleet.TSA
        return Fleet.WAHU

    @property
    def is_b2b_excluded(self) -> bool:
        """SOP: B2B customers excluded from MoMo/Hero/MTD/SMS/Bolt."""
        excluded_customers = ["TT Logistics", "Papa's Pizza", "Regimanuel Gray"]
        return self.customer_name in excluded_customers


class BoltFoodEarningsRow(BaseModel):
    """Bolt Food weekly earnings (Slot 6)."""
    bolt_rider_id: str
    base_earnings: float
    courier_tip: float
    vat: float
    week_start_date: date
    week_end_date: date

    @property
    def adjusted_earnings(self) -> float:
        """SOP §8.2: adjusted = base + tip + VAT."""
        return self.base_earnings + self.courier_tip + self.vat


# ============ Process Models ============

class DailyPaymentRow(BaseModel):
    """Normalized daily payment (post-reconciliation, Step 4 output)."""
    rider_id: str
    channel: PaymentChannel
    channel_reference: str
    amount: float
    matched_date: date
    invoice_id: Optional[str] = None


class WeeklyBillingRow(BaseModel):
    """Weekly billing register row (Step 3 output)."""
    rider_id: str
    subscription_id: str
    billing_week: str  # YYYY-WW format
    full_bill_ghs: float
    maintenance_days: int = 0
    pro_rata_adjustment: float = 0.0
    final_bill_ghs: float
    prior_balance_ghs: float = 0.0
    fleet: Fleet


class SuspenseItem(BaseModel):
    """Unmatched payment in suspense (Step 5 output)."""
    suspense_id: str
    channel: PaymentChannel
    channel_reference: str
    amount: float
    msisdn: Optional[str] = None
    received_date: date
    status: Literal["pending", "cleared", "escalated"]
    proposed_action: Optional[str] = None


class MTDRankingRow(BaseModel):
    """MTD rider ranking (Step 9 output)."""
    rider_id: str
    fleet: Fleet
    mtd_invoiced: float
    mtd_paid: float
    on_time_pct: float
    consecutive_active_weeks: int
    current_outstanding: float
    paid_factor: float
    on_time_factor: float
    retention_factor: float
    outstandings_factor: float
    composite_score: float
    band: Literal["Top", "Mid", "At Risk"]
    rank: int


class CompletionEvent(BaseModel):
    """Rider completion transition (Step 1 gating, feeds Report C)."""
    subscription_id: str
    rider_id: str
    customer_id: str
    completion_date: date
    total_weeks_billed: int
    total_amount_paid: float
    fleet: Fleet


# ============ API Response Models ============

class RunResponse(BaseModel):
    run_id: str
    run_date: date
    trigger_step: int
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ExceptionResponse(BaseModel):
    exception_id: str
    run_id: str
    step: int
    severity: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True
