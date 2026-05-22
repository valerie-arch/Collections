"""Step 4 — Refresh outstanding.

Per-rider formula (spec):
    outstanding = opening_outstanding
                - applied_this_run
                - prior_credit_consumed
    closing_credit = (prior_credit - prior_credit_consumed) + new_credit_this_run

where:
  * opening_outstanding   = Σ amount_due on the rider's open invoices
                            (from Step 1's opening_outstanding table)
  * applied_this_run      = Σ applied_amount on matched_payments rows
                            for this rider that landed on an invoice
                            (is_residual_credit == False)
  * new_credit_this_run   = Σ amount on rider_credits rows for this rider
                            (Step 2's overpayment residuals)
  * prior_credit          = balance from artifacts/rider_credits.xlsx
                            (carried from prior run)
  * prior_credit_consumed = min(prior_credit, max(0, opening - applied))

Closing outstanding is floored at 0 — a negative balance is shown as a
credit, never as negative outstanding (per spec).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from collections_v3.schemas import RunContext
from collections_v3.util.credits import load_balances, write_balances

logger = logging.getLogger(__name__)


OUTPUT_COLUMNS = [
    "rider_id", "rider_name", "fleet", "agency",
    "opening_outstanding", "applied_this_run", "prior_credit",
    "prior_credit_consumed", "new_credit_this_run",
    "closing_outstanding", "closing_credit", "open_invoice_count",
]


@dataclass
class Step4Result:
    outstanding: pd.DataFrame
    closing_credits: dict[str, float]  # rider_id -> balance to persist next run
    totals: dict


def _per_rider_applied(matched_payments: pd.DataFrame) -> dict[str, float]:
    if matched_payments is None or matched_payments.empty:
        return {}
    applied = matched_payments[~matched_payments["is_residual_credit"].astype(bool)]
    if applied.empty:
        return {}
    grp = applied.groupby("rider_id")["applied_amount"].sum()
    return {str(k): float(v) for k, v in grp.items()}


def _per_rider_new_credit(rider_credits: pd.DataFrame) -> dict[str, float]:
    if rider_credits is None or rider_credits.empty:
        return {}
    grp = rider_credits.groupby("rider_id")["amount"].sum()
    return {str(k): float(v) for k, v in grp.items()}


def compute(
    opening_outstanding: pd.DataFrame,
    matched_payments: pd.DataFrame,
    rider_credits_this_run: pd.DataFrame,
    *,
    prior_credits: Optional[dict[str, float]] = None,
) -> Step4Result:
    """Pure math — no I/O, easy to test."""
    prior_credits = prior_credits or {}
    applied_by_rider = _per_rider_applied(matched_payments)
    new_credit_by_rider = _per_rider_new_credit(rider_credits_this_run)

    # Riders who only show up via a credit (no opening) still need a row.
    rider_ids = set(opening_outstanding["rider_id"].astype(str)) if not opening_outstanding.empty else set()
    rider_ids.update(applied_by_rider)
    rider_ids.update(new_credit_by_rider)
    rider_ids.update(prior_credits.keys())

    rows = []
    closing_credits: dict[str, float] = {}
    for rid in rider_ids:
        rid_s = str(rid)
        opening_row = (
            opening_outstanding[opening_outstanding["rider_id"].astype(str) == rid_s].head(1)
            if not opening_outstanding.empty else pd.DataFrame()
        )
        if not opening_row.empty:
            r = opening_row.iloc[0]
            rider_name = r["rider_name"]
            fleet = r["fleet"]
            agency = r["agency"]
            opening = float(r["opening_outstanding"])
            open_count = int(r["open_invoice_count"])
        else:
            rider_name = fleet = agency = ""
            opening = 0.0
            open_count = 0

        applied = float(applied_by_rider.get(rid_s, 0.0))
        new_credit = float(new_credit_by_rider.get(rid_s, 0.0))
        prior_credit = float(prior_credits.get(rid_s, 0.0))

        balance_after_applied = opening - applied                  # could be negative if Step 2 over-applied
        prior_credit_consumed = min(prior_credit, max(0.0, balance_after_applied))
        closing_outstanding = max(0.0, balance_after_applied - prior_credit_consumed)
        closing_credit = max(0.0, prior_credit - prior_credit_consumed) + new_credit

        rows.append({
            "rider_id": rid_s,
            "rider_name": rider_name,
            "fleet": fleet,
            "agency": agency,
            "opening_outstanding": round(opening, 2),
            "applied_this_run": round(applied, 2),
            "prior_credit": round(prior_credit, 2),
            "prior_credit_consumed": round(prior_credit_consumed, 2),
            "new_credit_this_run": round(new_credit, 2),
            "closing_outstanding": round(closing_outstanding, 2),
            "closing_credit": round(closing_credit, 2),
            "open_invoice_count": open_count,
        })
        if round(closing_credit, 2) > 0:
            closing_credits[rid_s] = round(closing_credit, 2)

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS).sort_values(
        ["closing_outstanding", "closing_credit"], ascending=[False, False]
    ).reset_index(drop=True)

    totals = {
        "riders": len(df),
        "opening_total": round(float(df["opening_outstanding"].sum()), 2),
        "applied_total": round(float(df["applied_this_run"].sum()), 2),
        "closing_outstanding_total": round(float(df["closing_outstanding"].sum()), 2),
        "closing_credit_total": round(float(df["closing_credit"].sum()), 2),
        "riders_with_open_balance": int((df["closing_outstanding"] > 0).sum()),
        "riders_with_credit": int((df["closing_credit"] > 0).sum()),
    }
    return Step4Result(outstanding=df, closing_credits=closing_credits, totals=totals)


def write_xlsx(result: Step4Result) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        result.outstanding.to_excel(xw, sheet_name="rider_outstanding", index=False)
        totals_df = pd.DataFrame([result.totals])
        totals_df.to_excel(xw, sheet_name="totals", index=False)
    return buf.getvalue()


def run(
    ctx: RunContext,
    *,
    opening_outstanding: pd.DataFrame,
    matched_payments: pd.DataFrame,
    rider_credits_this_run: pd.DataFrame,
    prior_credits_path: Path = Path("artifacts/rider_credits.xlsx"),
) -> Step4Result:
    """Step 4 with persistence. Reads prior credits, computes, persists
    closing credits for the next run."""
    prior = load_balances(prior_credits_path)
    result = compute(
        opening_outstanding=opening_outstanding,
        matched_payments=matched_payments,
        rider_credits_this_run=rider_credits_this_run,
        prior_credits=prior,
    )
    rider_id_to_name = dict(zip(
        result.outstanding["rider_id"].astype(str),
        result.outstanding["rider_name"].astype(str),
    ))
    write_balances(
        result.closing_credits,
        rider_id_to_name=rider_id_to_name,
        path=prior_credits_path,
    )
    return result
