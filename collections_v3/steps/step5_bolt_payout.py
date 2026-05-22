"""Step 5 — Weekly Bolt payout (Monday job).

For each rider with Bolt earnings this week:
  1. Pull their closing_outstanding from Step 4.
  2. Apply the deduction decision matrix (GHS 420 cap).
  3. FIFO-apply the deduction against their oldest open invoices.
  4. Record the row in the appropriate per-fleet output file.

Two files are ALWAYS produced (even under --fleet All): one for Wahu and
one for TSA. Each file carries a per-agency subtotal block and a fleet
grand-total row.

Deduction is posted with `payment_source = "Bolt_Weekly"`. The applied
amount per invoice is captured so Step 4 on the next run sees the
reduced amount_due.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from collections_v3.schemas import RunContext
from collections_v3.util.bolt_matrix import compute_deduction
from collections_v3.util.fifo import apply_fifo

logger = logging.getLogger(__name__)


PAYMENT_SOURCE = "Bolt_Weekly"

PAYOUT_COLUMNS = [
    "week_start", "week_end",
    "rider_id", "rider_name", "fleet", "agency", "momo_account",
    "outstanding_before", "bolt_earnings", "deduction",
    "net_payout_to_rider", "outstanding_after",
    "invoices_settled", "applications_detail",
    "payment_source",
]


@dataclass
class FleetPayout:
    fleet: str                       # "Wahu" or "TSA"
    payouts: pd.DataFrame
    by_agency_subtotals: pd.DataFrame
    grand_totals: dict


@dataclass
class Step5Result:
    fleets: dict[str, FleetPayout] = field(default_factory=dict)


def _per_rider_open_invoices(invoices_all: pd.DataFrame) -> dict[str, list[dict]]:
    """Group open invoices (amount_due > 0) by rider, oldest-first."""
    if invoices_all is None or invoices_all.empty:
        return {}
    df = invoices_all[invoices_all["amount_due"].astype(float) > 0].copy()
    out: dict[str, list[dict]] = {}
    for rid, sub in df.groupby("rider_id"):
        sub = sub.sort_values(
            ["invoice_date", "invoice_number"], na_position="last"
        )
        out[str(rid).strip()] = sub[[
            "invoice_id", "invoice_number", "invoice_date", "amount_due",
        ]].to_dict("records")
    return out


def _outstanding_lookup(outstanding_df: pd.DataFrame) -> dict[str, dict]:
    """Returns {rider_id: {closing_outstanding, fleet, agency, rider_name}}."""
    if outstanding_df is None or outstanding_df.empty:
        return {}
    out: dict[str, dict] = {}
    for r in outstanding_df.itertuples(index=False):
        rid = str(getattr(r, "rider_id", "")).strip()
        if not rid:
            continue
        out[rid] = {
            "closing_outstanding": float(getattr(r, "closing_outstanding", 0.0) or 0.0),
            "fleet": str(getattr(r, "fleet", "") or ""),
            "agency": str(getattr(r, "agency", "") or ""),
            "rider_name": str(getattr(r, "rider_name", "") or ""),
        }
    return out


def compute(
    *,
    bolt_earnings: pd.DataFrame,
    outstanding_df: pd.DataFrame,
    invoices_all: pd.DataFrame,
) -> Step5Result:
    """Run the matrix per rider, FIFO-apply deductions, group by fleet."""
    out = Step5Result()
    out.fleets["Wahu"] = FleetPayout(
        fleet="Wahu",
        payouts=pd.DataFrame(columns=PAYOUT_COLUMNS),
        by_agency_subtotals=pd.DataFrame(),
        grand_totals={},
    )
    out.fleets["TSA"] = FleetPayout(
        fleet="TSA",
        payouts=pd.DataFrame(columns=PAYOUT_COLUMNS),
        by_agency_subtotals=pd.DataFrame(),
        grand_totals={},
    )

    if bolt_earnings is None or bolt_earnings.empty:
        return out

    open_by_rider = _per_rider_open_invoices(invoices_all)
    outstanding = _outstanding_lookup(outstanding_df)

    rows_by_fleet: dict[str, list[dict]] = {"Wahu": [], "TSA": []}
    for r in bolt_earnings.itertuples(index=False):
        rid = str(getattr(r, "rider_id", "") or "").strip()
        if not rid:
            continue
        earnings = float(getattr(r, "bolt_payout", 0.0) or 0.0)
        if earnings <= 0:
            continue

        info = outstanding.get(rid, {})
        fleet = info.get("fleet") or ""
        if fleet not in ("Wahu", "TSA"):
            # Unknown / B2B / unmapped — skip; surfaces in data_quality later.
            continue
        outstanding_before = info.get("closing_outstanding", 0.0)
        agency = info.get("agency", "")
        rider_name = info.get("rider_name") or str(getattr(r, "rider_name", ""))

        deduction, payout = compute_deduction(outstanding_before, earnings)

        # FIFO-apply the deduction against the rider's open invoices.
        fifo = apply_fifo(deduction, open_by_rider.get(rid, []))
        invoices_settled_ids = [iid for iid, _ in fifo.applications]
        applications_detail = "; ".join(
            f"{iid}={amt:.2f}" for iid, amt in fifo.applications
        )
        # Any residual from apply_fifo would imply the rider's outstanding
        # was less than the deduction — the matrix already prevents that,
        # so credit should be 0. Treat any residual defensively.
        if fifo.credit > 0:
            logger.warning(
                "rider %s: bolt deduction %s exceeds open invoices (%s residual)",
                rid, deduction, fifo.credit,
            )

        outstanding_after = round(max(0.0, outstanding_before - deduction), 2)

        rows_by_fleet[fleet].append({
            "week_start": getattr(r, "week_start", None),
            "week_end": getattr(r, "week_end", None),
            "rider_id": rid,
            "rider_name": rider_name,
            "fleet": fleet,
            "agency": agency,
            "momo_account": str(getattr(r, "momo_account", "") or ""),
            "outstanding_before": round(outstanding_before, 2),
            "bolt_earnings": round(earnings, 2),
            "deduction": deduction,
            "net_payout_to_rider": payout,
            "outstanding_after": outstanding_after,
            "invoices_settled": ", ".join(invoices_settled_ids),
            "applications_detail": applications_detail,
            "payment_source": PAYMENT_SOURCE,
        })

    for fleet, rows in rows_by_fleet.items():
        df = pd.DataFrame(rows, columns=PAYOUT_COLUMNS)
        out.fleets[fleet] = FleetPayout(
            fleet=fleet,
            payouts=df,
            by_agency_subtotals=_subtotals_by_agency(df),
            grand_totals=_grand_totals(df),
        )
    return out


def _subtotals_by_agency(payouts: pd.DataFrame) -> pd.DataFrame:
    if payouts.empty:
        return pd.DataFrame(columns=[
            "agency", "rider_count", "bolt_earnings", "deduction", "net_payout_to_rider",
        ])
    g = payouts.groupby("agency", as_index=False).agg(
        rider_count=("rider_id", "count"),
        bolt_earnings=("bolt_earnings", "sum"),
        deduction=("deduction", "sum"),
        net_payout_to_rider=("net_payout_to_rider", "sum"),
    )
    for col in ("bolt_earnings", "deduction", "net_payout_to_rider"):
        g[col] = g[col].round(2)
    return g.sort_values("agency").reset_index(drop=True)


def _grand_totals(payouts: pd.DataFrame) -> dict:
    if payouts.empty:
        return {
            "rider_count": 0, "bolt_earnings_total": 0.0,
            "deduction_total": 0.0, "net_payout_to_rider_total": 0.0,
        }
    return {
        "rider_count": int(len(payouts)),
        "bolt_earnings_total": round(float(payouts["bolt_earnings"].sum()), 2),
        "deduction_total": round(float(payouts["deduction"].sum()), 2),
        "net_payout_to_rider_total": round(float(payouts["net_payout_to_rider"].sum()), 2),
    }


def write_xlsx(fleet_payout: FleetPayout) -> bytes:
    """Three sheets per fleet file: payouts, by_agency_subtotals, grand_totals."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        fleet_payout.payouts.to_excel(xw, sheet_name="payouts", index=False)
        fleet_payout.by_agency_subtotals.to_excel(
            xw, sheet_name="by_agency_subtotals", index=False,
        )
        pd.DataFrame([fleet_payout.grand_totals]).to_excel(
            xw, sheet_name="grand_totals", index=False,
        )
    return buf.getvalue()


def run(
    ctx: RunContext,
    *,
    bolt_earnings: pd.DataFrame,
    outstanding_df: pd.DataFrame,
    invoices_all: pd.DataFrame,
) -> Step5Result:
    return compute(
        bolt_earnings=bolt_earnings,
        outstanding_df=outstanding_df,
        invoices_all=invoices_all,
    )
