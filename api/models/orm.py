"""SQLAlchemy ORM models — mirror schema.sql.

Schema ownership: schema.sql is authoritative. Postgres loads it on first
container boot via docker-entrypoint-initdb.d. These ORM classes exist for
querying only; they do NOT drive DDL.
"""

from datetime import datetime, date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB, UUID
from sqlalchemy.orm import relationship

from api.database import Base


def _uuid() -> str:
    return str(uuid4())


# Enum types — `create_type=False` so SQLAlchemy never tries to (re)create them;
# Postgres already has them from schema.sql.
USER_ROLE = PgEnum(
    "Finance Officer",
    "Collections Lead",
    "Collections Analyst",
    "Ops Analyst",
    "Recovery Officer",
    "Admin",
    name="user_role",
    create_type=False,
)
FLEET_TYPE = PgEnum("Wahu", "TSA", name="fleet_type", create_type=False)
RIDER_STATUS_ENUM = PgEnum(
    "active", "paused", "completed", "churned",
    name="rider_status_enum", create_type=False,
)
PAYMENT_CHANNEL = PgEnum(
    "mtn", "telecel", "hero", "bolt_deduction", "suspense",
    name="payment_channel", create_type=False,
)
RUN_STATUS = PgEnum(
    "queued", "running", "succeeded", "failed",
    name="run_status", create_type=False,
)
STEP_STATUS = PgEnum(
    "pending", "running", "succeeded", "failed",
    name="step_status", create_type=False,
)
EXCEPTION_SEVERITY = PgEnum(
    "info", "warning", "error", "critical",
    name="exception_severity", create_type=False,
)
EXCEPTION_STATUS = PgEnum(
    "open", "resolved", "escalated",
    name="exception_status_enum", create_type=False,
)
SIGNOFF_STATUS = PgEnum(
    "pending", "approved", "rejected",
    name="signoff_status", create_type=False,
)


class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False)
    google_id = Column(String(255))
    first_name = Column(String(100))
    last_name = Column(String(100))
    role = Column(USER_ROLE, nullable=False)
    fleet_context = Column(FLEET_TYPE, default="Wahu")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Run(Base):
    __tablename__ = "runs"

    run_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_date = Column(Date, nullable=False)
    trigger_step = Column(Integer, nullable=False)
    status = Column(RUN_STATUS, default="queued")
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("trigger_step BETWEEN 1 AND 12", name="ck_runs_trigger_step"),
    )

    step_results = relationship(
        "StepResult", back_populates="run", cascade="all, delete-orphan"
    )
    exceptions = relationship(
        "Exception_", back_populates="run", cascade="all, delete-orphan"
    )


class StepResult(Base):
    __tablename__ = "step_results"

    result_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id = Column(
        UUID(as_uuid=False),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    step = Column(Integer, nullable=False)
    status = Column(STEP_STATUS, default="pending")
    output_path = Column(String(512))
    exception_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    row_count = Column(Integer, default=0)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("step BETWEEN 1 AND 12", name="ck_step_results_step"),
    )

    run = relationship("Run", back_populates="step_results")


# `Exception` shadows the builtin; suffix with underscore for the ORM class.
class Exception_(Base):
    __tablename__ = "exceptions"

    exception_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id = Column(
        UUID(as_uuid=False),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    step = Column(Integer, nullable=False)
    severity = Column(EXCEPTION_SEVERITY, nullable=False)
    status = Column(EXCEPTION_STATUS, default="open")
    error_code = Column(String(50))
    message = Column(Text, nullable=False)
    context = Column(JSONB)
    assigned_to = Column(UUID(as_uuid=False), ForeignKey("users.user_id"))
    resolved_at = Column(DateTime)
    resolution_note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="exceptions")


class Signoff(Base):
    __tablename__ = "signoffs"

    signoff_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id = Column(
        UUID(as_uuid=False),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    step = Column(Integer, nullable=False)
    signed_by = Column(
        UUID(as_uuid=False), ForeignKey("users.user_id"), nullable=False
    )
    approval_status = Column(SIGNOFF_STATUS, default="approved")
    approval_note = Column(Text)
    signed_at = Column(DateTime, default=datetime.utcnow)


class SuspenseItem(Base):
    __tablename__ = "suspense_items"

    suspense_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_date = Column(Date, nullable=False)
    channel = Column(PAYMENT_CHANNEL, nullable=False)
    channel_reference = Column(String(255), unique=True)
    amount_ghs = Column(Numeric(10, 2), nullable=False)
    msisdn = Column(String(20))
    received_at = Column(DateTime)
    status = Column(EXCEPTION_STATUS, default="open")
    rider_id = Column(String(50))
    invoice_id = Column(String(100))
    cleared_by = Column(UUID(as_uuid=False), ForeignKey("users.user_id"))
    cleared_at = Column(DateTime)
    clearance_note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class PaymentApplicationLog(Base):
    __tablename__ = "payment_application_log"

    log_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_date = Column(Date, nullable=False)
    channel_txn_id = Column(String(255), nullable=False)
    channel = Column(PAYMENT_CHANNEL, nullable=False)
    rider_id = Column(String(50), nullable=False)
    invoice_id = Column(String(100))
    amount_applied_ghs = Column(Numeric(10, 2), nullable=False)
    applied_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("channel_txn_id"),)


class ZohoQbInvoiceMap(Base):
    __tablename__ = "zoho_qb_invoice_map"

    mapping_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    zoho_invoice_id = Column(String(100), nullable=False)
    qb_invoice_id = Column(String(100))
    rider_id = Column(String(50), nullable=False)
    fleet = Column(FLEET_TYPE, nullable=False)
    mapped_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("zoho_invoice_id"),)


class ZohoQbPaymentMap(Base):
    __tablename__ = "zoho_qb_payment_map"

    mapping_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    zoho_payment_id = Column(String(100), nullable=False)
    qb_payment_id = Column(String(100))
    rider_id = Column(String(50), nullable=False)
    channel = Column(PAYMENT_CHANNEL, nullable=False)
    fleet = Column(FLEET_TYPE, nullable=False)
    mapped_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("zoho_payment_id"),)


class CompletionEvent(Base):
    __tablename__ = "completion_events"

    event_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    subscription_id = Column(String(100), nullable=False)
    rider_id = Column(String(50), nullable=False)
    customer_id = Column(String(100))
    completion_date = Column(Date, nullable=False)
    total_weeks_billed = Column(Integer, nullable=False)
    total_amount_paid_ghs = Column(Numeric(12, 2), nullable=False)
    signed_off_by = Column(UUID(as_uuid=False), ForeignKey("users.user_id"))
    certificate_issued_date = Column(Date)
    certificate_path = Column(String(512))
    fleet = Column(FLEET_TYPE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class MtdRanking(Base):
    __tablename__ = "mtd_rankings"

    ranking_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    report_date = Column(Date, nullable=False)
    rider_id = Column(String(50), nullable=False)
    subscription_id = Column(String(100))
    fleet = Column(FLEET_TYPE, nullable=False)
    composite_score = Column(Numeric(5, 2))
    paid_factor = Column(Numeric(5, 2))
    on_time_factor = Column(Numeric(5, 2))
    retention_factor = Column(Numeric(5, 2))
    outstandings_factor = Column(Numeric(5, 2))
    band = Column(String(20))
    rank = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class SmsOptout(Base):
    __tablename__ = "sms_optouts"

    optout_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    rider_id = Column(String(50))
    msisdn = Column(String(20), nullable=False)
    opted_out_at = Column(DateTime, default=datetime.utcnow)
    opt_in_at = Column(DateTime)


class SmsLog(Base):
    __tablename__ = "sms_logs"

    log_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_date = Column(Date, nullable=False)
    rider_id = Column(String(50), nullable=False)
    msisdn = Column(String(20))
    template_version = Column(String(50))
    message_text = Column(Text)
    gateway_reference = Column(String(100))
    send_status = Column(String(20))
    delivered_at = Column(DateTime)
    failed_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.user_id"))
    action = Column(String(255), nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(String(255))
    changes = Column(JSONB)
    timestamp = Column(DateTime, default=datetime.utcnow)
