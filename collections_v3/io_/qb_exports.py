"""QuickBooks export — IIF + CSV for invoices and payments.

IIF is QuickBooks Desktop's tab-delimited import format. We emit a
minimal but valid structure:

  Invoices  -> TRNS=INVOICE / SPL=INVOICE / ENDTRNS
  Payments  -> TRNS=PAYMENT / SPL=PAYMENT / ENDTRNS

For each TRNS line, the AMOUNT is the cash going TO Accounts Receivable
(invoice) or coming FROM the bank (payment). The matching SPL line
reverses the sign against the income / AR account so the entry balances.

The CSV variant is the same data flattened for QuickBooks Online or for
operators who prefer to review pre-import. Both files are written every
run, even if empty (so the operator has a stable place to look).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Iterable, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

INVOICE_CSV_COLUMNS = [
    "invoice_number", "invoice_date", "rider_id", "rider_name",
    "fleet", "agency", "amount", "amount_due", "status",
]


def invoices_to_csv(invoices_in_scope: pd.DataFrame) -> bytes:
    if invoices_in_scope is None or invoices_in_scope.empty:
        df = pd.DataFrame(columns=INVOICE_CSV_COLUMNS)
    else:
        cols = [c for c in INVOICE_CSV_COLUMNS if c in invoices_in_scope.columns]
        df = invoices_in_scope[cols].copy()
        for c in INVOICE_CSV_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        df = df[INVOICE_CSV_COLUMNS]
    out = io.StringIO()
    df.to_csv(out, index=False, lineterminator="\n")
    return out.getvalue().encode("utf-8")


def _qb_date(d) -> str:
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return ""
    if isinstance(d, (datetime, date)):
        return d.strftime("%m/%d/%Y")
    try:
        return pd.to_datetime(d).strftime("%m/%d/%Y")
    except Exception:
        return ""


def invoices_to_iif(invoices_in_scope: pd.DataFrame) -> bytes:
    """Emit IIF: one TRNS+SPL pair per invoice."""
    lines: list[str] = [
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO",
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO",
        "!ENDTRNS",
    ]
    if invoices_in_scope is not None and not invoices_in_scope.empty:
        for r in invoices_in_scope.itertuples(index=False):
            inv_no = str(getattr(r, "invoice_number", "") or "")
            d = _qb_date(getattr(r, "invoice_date", None))
            name = str(getattr(r, "rider_name", "") or "")
            try:
                amount = float(getattr(r, "amount", 0.0) or 0.0)
            except (TypeError, ValueError):
                amount = 0.0
            memo = f"{getattr(r, 'fleet', '')}/{getattr(r, 'agency', '')}"
            lines.append(
                "TRNS\tINVOICE\t"
                f"{d}\tAccounts Receivable\t{name}\t{amount:.2f}\t{inv_no}\t{memo}"
            )
            lines.append(
                "SPL\tINVOICE\t"
                f"{d}\tSubscription Income\t{name}\t{-amount:.2f}\t{inv_no}\t"
            )
            lines.append("ENDTRNS")
    return ("\n".join(lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Payments (MoMo / bank / Bolt_Weekly)
# ---------------------------------------------------------------------------

PAYMENT_CSV_COLUMNS = [
    "txn_id", "date", "rider_id", "rider_name", "channel",
    "amount", "invoice_id_applied", "payment_source",
]


def _matched_to_payment_rows(matched_payments: pd.DataFrame) -> list[dict]:
    if matched_payments is None or matched_payments.empty:
        return []
    rows = []
    applied = matched_payments[~matched_payments["is_residual_credit"].astype(bool)]
    for r in applied.itertuples(index=False):
        rows.append({
            "txn_id": str(getattr(r, "txn_id", "") or ""),
            "date": getattr(r, "date", None),
            "rider_id": str(getattr(r, "rider_id", "") or ""),
            "rider_name": str(getattr(r, "rider_name", "") or ""),
            "channel": str(getattr(r, "channel", "") or ""),
            "amount": float(getattr(r, "applied_amount", 0.0) or 0.0),
            "invoice_id_applied": str(getattr(r, "invoice_id", "") or ""),
            "payment_source": "Receipt",
        })
    return rows


def _bolt_to_payment_rows(bolt_fleets) -> list[dict]:
    rows = []
    for fp in (bolt_fleets or {}).values():
        if fp.payouts is None or fp.payouts.empty:
            continue
        for r in fp.payouts.itertuples(index=False):
            deduction = float(getattr(r, "deduction", 0.0) or 0.0)
            if deduction <= 0:
                continue
            # Each Bolt deduction posts as a single payment per rider; the
            # applications_detail string carries the per-invoice split.
            rows.append({
                "txn_id": f"BOLT_{getattr(r, 'rider_id', '')}_"
                          f"{getattr(r, 'week_end', '')}",
                "date": getattr(r, "week_end", None),
                "rider_id": str(getattr(r, "rider_id", "") or ""),
                "rider_name": str(getattr(r, "rider_name", "") or ""),
                "channel": "Bolt",
                "amount": deduction,
                "invoice_id_applied": str(getattr(r, "invoices_settled", "") or ""),
                "payment_source": "Bolt_Weekly",
            })
    return rows


def payments_to_csv(matched_payments: pd.DataFrame, bolt_fleets) -> bytes:
    rows = _matched_to_payment_rows(matched_payments) + _bolt_to_payment_rows(bolt_fleets)
    df = pd.DataFrame(rows, columns=PAYMENT_CSV_COLUMNS)
    out = io.StringIO()
    df.to_csv(out, index=False, lineterminator="\n")
    return out.getvalue().encode("utf-8")


def payments_to_iif(matched_payments: pd.DataFrame, bolt_fleets) -> bytes:
    lines: list[str] = [
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO",
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO",
        "!ENDTRNS",
    ]
    for row in _matched_to_payment_rows(matched_payments) + _bolt_to_payment_rows(bolt_fleets):
        d = _qb_date(row["date"])
        deposit_account = "Bank" if row["payment_source"] != "Bolt_Weekly" else "Bolt Clearing"
        amount = float(row["amount"])
        lines.append(
            "TRNS\tPAYMENT\t"
            f"{d}\t{deposit_account}\t{row['rider_name']}\t{amount:.2f}\t"
            f"{row['txn_id']}\t{row['payment_source']}/{row['channel']}"
        )
        lines.append(
            "SPL\tPAYMENT\t"
            f"{d}\tAccounts Receivable\t{row['rider_name']}\t{-amount:.2f}\t"
            f"{row['txn_id']}\t{row['invoice_id_applied']}"
        )
        lines.append("ENDTRNS")
    return ("\n".join(lines) + "\n").encode("utf-8")
