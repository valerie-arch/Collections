"""Step 2 — Auto-reconcile receipts.

Pipeline:
  2A  already_booked  : drop receipts already recorded in Zoho
  2B  three tiers     : PHONE / ACCOUNT > NAME (>= 85) > REF
  2C  FIFO apply      : split matched amount across rider's oldest open
                        invoices, residual -> rider_credit
  2D  suspense        : receipts with no tier hit go to Suspense ledger

Output buckets:
  * matched_payments      — receipts resolved to an in-scope rider
  * out_of_scope          — tier hit, but the rider is outside --fleet/--agency
  * already_in_zoho       — receipts already recorded in Zoho (don't allocate)
  * suspense              — receipts with no tier hit
  * rider_credits         — residuals from over-payment (per rider)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from collections_v3.matching import tier1_phone, tier2_name, tier3_ref
from collections_v3.schemas import RunContext
from collections_v3.util.already_booked import (
    AlreadyBookedIndex, build_already_booked_index, is_already_booked,
)
from collections_v3.util.fifo import apply_fifo
from collections_v3.util.operator_rules import check_name_only_soft_match
from collections_v3.util.rider_index import RiderIndex

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

MATCHED_COLUMNS = [
    "txn_id", "channel", "date", "receipt_amount", "rider_id", "rider_name",
    "match_tier", "match_score", "invoice_id", "applied_amount",
    "is_residual_credit", "source_file",
]
SUSPENSE_COLUMNS = [
    "txn_id", "channel", "date", "amount", "sender_name",
    "sender_phone_canonical", "reference", "narration", "source_file",
    "reason",
]
OUT_OF_SCOPE_COLUMNS = [
    "txn_id", "channel", "date", "amount", "rider_id", "rider_name",
    "rider_fleet", "rider_agency", "match_tier", "match_score",
    "active_filter_fleet", "active_filter_agency",
]
ALREADY_IN_ZOHO_COLUMNS = [
    "txn_id", "channel", "date", "amount", "sender_name",
    "reference", "source_file",
]


@dataclass
class Step2Result:
    matched_payments: pd.DataFrame
    out_of_scope: pd.DataFrame
    already_in_zoho: pd.DataFrame
    suspense: pd.DataFrame
    rider_credits: pd.DataFrame
    counts: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tier dispatch
# ---------------------------------------------------------------------------

def _tier_match(receipt_row, index: RiderIndex) -> tuple[Optional[str], Optional[str], Optional[int]]:
    rid, tier = tier1_phone(receipt_row, index)
    if rid:
        return rid, tier, None
    rid, tier, score = tier2_name(receipt_row, index)
    if rid:
        return rid, tier, score
    rid, tier = tier3_ref(receipt_row, index)
    if rid:
        return rid, tier, None
    return None, None, None


def _open_invoices_for(rider_id: str, invoices_all: pd.DataFrame) -> list[dict]:
    """Return open invoices (amount_due > 0) for a rider, oldest-first.

    invoices_all must include: rider_id, invoice_id, invoice_number,
    invoice_date, amount_due."""
    if invoices_all.empty:
        return []
    df = invoices_all[
        (invoices_all["rider_id"].astype(str).str.strip() == rider_id)
        & (invoices_all["amount_due"].astype(float) > 0)
    ]
    if df.empty:
        return []
    return df[["invoice_id", "invoice_number", "invoice_date", "amount_due"]].to_dict("records")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(
    ctx: RunContext,
    *,
    receipts: pd.DataFrame,
    invoices_all: pd.DataFrame,
    riders_in_scope: set[str],
    rider_index: RiderIndex,
    zoho_payments: Optional[pd.DataFrame] = None,
) -> Step2Result:
    """Run Step 2 against pre-loaded inputs from Step 1."""
    matched_rows: list[dict] = []
    out_of_scope_rows: list[dict] = []
    already_rows: list[dict] = []
    suspense_rows: list[dict] = []
    credit_rows: list[dict] = []

    ab: AlreadyBookedIndex = build_already_booked_index(zoho_payments)
    active_fleet = ctx.fleet.value if hasattr(ctx.fleet, "value") else str(ctx.fleet)
    active_agency = ctx.agency.value if hasattr(ctx.agency, "value") else str(ctx.agency)

    receipts_df = receipts.copy() if receipts is not None else pd.DataFrame()
    for receipt in receipts_df.itertuples(index=False):
        # 2A — already booked in Zoho?
        if is_already_booked(receipt, ab):
            already_rows.append({
                "txn_id": getattr(receipt, "txn_id", ""),
                "channel": getattr(receipt, "channel", ""),
                "date": getattr(receipt, "date", None),
                "amount": float(getattr(receipt, "amount", 0.0)),
                "sender_name": getattr(receipt, "sender_name", ""),
                "reference": getattr(receipt, "reference", ""),
                "source_file": getattr(receipt, "source_file", ""),
            })
            continue

        # 2B — tier 1/2/3
        rider_id, tier, score = _tier_match(receipt, rider_index)

        if not rider_id:
            suspense_rows.append({
                "txn_id": getattr(receipt, "txn_id", ""),
                "channel": getattr(receipt, "channel", ""),
                "date": getattr(receipt, "date", None),
                "amount": float(getattr(receipt, "amount", 0.0)),
                "sender_name": getattr(receipt, "sender_name", ""),
                "sender_phone_canonical": getattr(receipt, "sender_phone_canonical", ""),
                "reference": getattr(receipt, "reference", ""),
                "narration": getattr(receipt, "narration", ""),
                "source_file": getattr(receipt, "source_file", ""),
                "reason": "no_tier_hit",
            })
            continue

        # Operator Rule 2 — a name-only Tier 2 hit > GHS 500 with no phone
        # / ref / narration is too risky to auto-apply. Push to suspense.
        rule2 = check_name_only_soft_match(
            tier=tier or "",
            amount=float(getattr(receipt, "amount", 0.0) or 0.0),
            sender_phone=str(getattr(receipt, "sender_phone_canonical", "")),
            reference=str(getattr(receipt, "reference", "")),
            narration=str(getattr(receipt, "narration", "")),
        )
        if not rule2.passed:
            suspense_rows.append({
                "txn_id": getattr(receipt, "txn_id", ""),
                "channel": getattr(receipt, "channel", ""),
                "date": getattr(receipt, "date", None),
                "amount": float(getattr(receipt, "amount", 0.0)),
                "sender_name": getattr(receipt, "sender_name", ""),
                "sender_phone_canonical": getattr(receipt, "sender_phone_canonical", ""),
                "reference": getattr(receipt, "reference", ""),
                "narration": getattr(receipt, "narration", ""),
                "source_file": getattr(receipt, "source_file", ""),
                "reason": rule2.rule,
            })
            continue

        # Scope gate.
        if rider_id not in riders_in_scope:
            out_of_scope_rows.append({
                "txn_id": getattr(receipt, "txn_id", ""),
                "channel": getattr(receipt, "channel", ""),
                "date": getattr(receipt, "date", None),
                "amount": float(getattr(receipt, "amount", 0.0)),
                "rider_id": rider_id,
                "rider_name": rider_index.rider_id_to_name.get(rider_id, ""),
                "rider_fleet": rider_index.rider_id_to_fleet.get(rider_id, ""),
                "rider_agency": rider_index.rider_id_to_agency.get(rider_id, ""),
                "match_tier": tier,
                "match_score": score,
                "active_filter_fleet": active_fleet,
                "active_filter_agency": active_agency,
            })
            continue

        # 2C — apply FIFO.
        open_invs = _open_invoices_for(rider_id, invoices_all)
        amount = float(getattr(receipt, "amount", 0.0))
        fifo = apply_fifo(amount, open_invs)
        rider_name = rider_index.rider_id_to_name.get(rider_id, "")
        receipt_meta = dict(
            txn_id=getattr(receipt, "txn_id", ""),
            channel=getattr(receipt, "channel", ""),
            date=getattr(receipt, "date", None),
            receipt_amount=amount,
            rider_id=rider_id,
            rider_name=rider_name,
            match_tier=tier,
            match_score=score,
            source_file=getattr(receipt, "source_file", ""),
        )
        if not fifo.applications and fifo.credit <= 0:
            # Rider matched but had no open invoices AND no credit (shouldn't
            # happen — amount > 0 forces credit). Surface as suspense to
            # avoid silent loss.
            suspense_rows.append({
                **{k: receipt_meta.get(k, "") for k in ["txn_id", "channel", "date"]},
                "amount": amount,
                "sender_name": getattr(receipt, "sender_name", ""),
                "sender_phone_canonical": getattr(receipt, "sender_phone_canonical", ""),
                "reference": getattr(receipt, "reference", ""),
                "narration": getattr(receipt, "narration", ""),
                "source_file": getattr(receipt, "source_file", ""),
                "reason": "matched_but_no_open_invoices_and_no_credit",
            })
            continue
        for inv_id, applied in fifo.applications:
            matched_rows.append({
                **receipt_meta,
                "invoice_id": inv_id,
                "applied_amount": applied,
                "is_residual_credit": False,
            })
        if fifo.credit > 0:
            matched_rows.append({
                **receipt_meta,
                "invoice_id": "",
                "applied_amount": fifo.credit,
                "is_residual_credit": True,
            })
            credit_rows.append({
                "rider_id": rider_id,
                "rider_name": rider_name,
                "amount": fifo.credit,
                "source_txn_id": getattr(receipt, "txn_id", ""),
                "source_file": getattr(receipt, "source_file", ""),
                "date": getattr(receipt, "date", None),
            })

    # Many real-world receipts have a blank txn_id, so counting unique
    # receipts by a stable tuple (channel, date, amount, rider_id) is more
    # informative than counting distinct txn_id values.
    unique_receipts = len({
        (r["channel"], r["date"], r["receipt_amount"], r["rider_id"])
        for r in matched_rows
    })
    counts = {
        "matched_rows": len(matched_rows),
        "matched_unique_receipts": unique_receipts,
        "out_of_scope": len(out_of_scope_rows),
        "already_in_zoho": len(already_rows),
        "suspense": len(suspense_rows),
        "rider_credits": len(credit_rows),
        "credit_total_ghs": round(sum(c["amount"] for c in credit_rows), 2),
    }
    logger.info("step2 counts: %s", counts)

    return Step2Result(
        matched_payments=pd.DataFrame(matched_rows, columns=MATCHED_COLUMNS),
        out_of_scope=pd.DataFrame(out_of_scope_rows, columns=OUT_OF_SCOPE_COLUMNS),
        already_in_zoho=pd.DataFrame(already_rows, columns=ALREADY_IN_ZOHO_COLUMNS),
        suspense=pd.DataFrame(suspense_rows, columns=SUSPENSE_COLUMNS),
        rider_credits=pd.DataFrame(credit_rows),
        counts=counts,
    )
