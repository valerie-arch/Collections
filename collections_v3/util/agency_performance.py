"""Agency performance snapshot.

Three metrics per collection agency:
  * Collection rate %     = Σ applied this run / Σ opening outstanding
  * Suspense rate %       = suspense receipts (count) / total receipts (count)
  * Average days-to-match = mean(receipt_date - invoice_date) across this
                            agency's matched applications

Suspense isn't agency-attributed at the time of receipt (no rider yet), so
the suspense_rate % is the same value for every agency row — it's a
system-wide health metric printed per row so the operator can see it
alongside the per-agency numbers without flipping sheets.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


COLUMNS = [
    "agency", "rider_count", "opening_outstanding_ghs",
    "applied_ghs", "collection_rate_pct",
    "suspense_rate_pct", "avg_days_to_match",
]


def _days_diff(receipt_date, invoice_date) -> Optional[int]:
    if receipt_date is None or invoice_date is None:
        return None
    try:
        rd = pd.to_datetime(receipt_date)
        idate = pd.to_datetime(invoice_date)
        return int((rd - idate).days)
    except Exception:
        return None


def compute(
    outstanding_df: pd.DataFrame,
    matched_payments: pd.DataFrame,
    *,
    total_receipts: int,
    suspense_count: int,
    invoices_all: Optional[pd.DataFrame] = None,
    bolt_fleets=None,
    include_bolt_weekly: bool = True,
) -> pd.DataFrame:
    """Per-agency performance snapshot.

    Q3 (governance.agency_scoring.include_bolt_weekly): Bolt deductions are
    now synthesized as receipts in Step 1 and flow through matched_payments
    and Step 4's `applied_this_run`, so they're already in `applied_ghs`.
    The flag is preserved as a kill-switch: when False, Bolt-channel rows
    are subtracted out so collection_rate_pct reflects MoMo/bank receipts
    only. `bolt_fleets` is no longer the source of the bolt total.
    """
    suspense_pct = (
        round(100 * suspense_count / total_receipts, 1)
        if total_receipts else 0.0
    )

    if outstanding_df is None or outstanding_df.empty:
        return pd.DataFrame(columns=COLUMNS)

    # Per-agency opening + applied. `applied_this_run` already includes
    # Bolt deductions (synthesized as channel="bolt_deduction" receipts).
    per_agency = outstanding_df.groupby("agency", as_index=False).agg(
        rider_count=("rider_id", "count"),
        opening_outstanding_ghs=("opening_outstanding", "sum"),
        applied_ghs=("applied_this_run", "sum"),
    )

    # Kill-switch: when include_bolt_weekly=False, back out the Bolt-channel
    # contribution per agency from `applied_ghs`.
    bolt_applied_by_agency: dict[str, float] = {}
    if not include_bolt_weekly and matched_payments is not None and not matched_payments.empty:
        bolt_only = matched_payments[
            (matched_payments["channel"].astype(str) == "bolt_deduction")
            & (~matched_payments["is_residual_credit"].astype(bool))
        ]
        if not bolt_only.empty:
            rider_to_agency = dict(zip(
                outstanding_df["rider_id"].astype(str),
                outstanding_df["agency"].astype(str),
            ))
            for r in bolt_only.itertuples(index=False):
                ag = rider_to_agency.get(str(getattr(r, "rider_id", "")), "")
                bolt_applied_by_agency[ag] = (
                    bolt_applied_by_agency.get(ag, 0.0)
                    + float(getattr(r, "applied_amount", 0.0) or 0.0)
                )

    # Avg days-to-match per agency.
    avg_dtm: dict[str, float] = {}
    if matched_payments is not None and not matched_payments.empty and invoices_all is not None and not invoices_all.empty:
        applied = matched_payments[~matched_payments["is_residual_credit"].astype(bool)]
        inv_dates = invoices_all.set_index("invoice_id")["invoice_date"].to_dict()
        rider_agency = dict(zip(outstanding_df["rider_id"].astype(str), outstanding_df["agency"].astype(str)))
        diffs_by_agency: dict[str, list[int]] = {}
        for r in applied.itertuples(index=False):
            rd = getattr(r, "date", None)
            inv_id = str(getattr(r, "invoice_id", ""))
            idate = inv_dates.get(inv_id)
            d = _days_diff(rd, idate)
            if d is None:
                continue
            ag = rider_agency.get(str(getattr(r, "rider_id", "")), "")
            diffs_by_agency.setdefault(ag, []).append(d)
        for ag, vals in diffs_by_agency.items():
            avg_dtm[ag] = round(sum(vals) / len(vals), 1) if vals else 0.0

    rows = []
    for r in per_agency.itertuples(index=False):
        opening = float(r.opening_outstanding_ghs)
        # Bolt is already in applied_ghs; subtract it back out when the
        # kill-switch is off so the rate reflects non-Bolt receipts only.
        applied = float(r.applied_ghs) - bolt_applied_by_agency.get(str(r.agency), 0.0)
        rate = round(100 * applied / opening, 1) if opening > 0 else 0.0
        rows.append({
            "agency": r.agency,
            "rider_count": int(r.rider_count),
            "opening_outstanding_ghs": round(opening, 2),
            "applied_ghs": round(applied, 2),
            "collection_rate_pct": rate,
            "suspense_rate_pct": suspense_pct,
            "avg_days_to_match": avg_dtm.get(r.agency, None),
        })
    return pd.DataFrame(rows, columns=COLUMNS).sort_values("agency").reset_index(drop=True)


def write_xlsx(df: pd.DataFrame) -> bytes:
    import io as _io
    buf = _io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="agency_performance", index=False)
    return buf.getvalue()
