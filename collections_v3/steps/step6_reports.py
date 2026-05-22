"""Step 6 — Reporting and audit trail.

Produces (per run):
  * run_summary.md / run_summary.pdf  (one-page, locked)
  * agency_performance.xlsx
  * data_quality.xlsx
  * qb_invoices.iif + qb_invoices.csv
  * qb_payments.iif + qb_payments.csv

The qb_upload_log singleton is *not* written by `run()` — that's an
operator-confirmed action (call `util.qb_upload_log.append_upload` after
the IIF makes it into QuickBooks).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from collections_v3 import governance
from collections_v3.io_ import qb_exports
from collections_v3.schemas import RunContext
from collections_v3.util import agency_performance, data_quality, run_summary

logger = logging.getLogger(__name__)


@dataclass
class Step6Result:
    run_summary_md: str
    run_summary_pdf: bytes
    agency_performance: pd.DataFrame
    data_quality: pd.DataFrame
    qb_invoices_iif: bytes
    qb_invoices_csv: bytes
    qb_payments_iif: bytes
    qb_payments_csv: bytes


def compute(
    *,
    ctx: RunContext,
    operator: str,
    sources: list[dict],
    invoices_in_scope: pd.DataFrame,
    invoices_all: pd.DataFrame,
    receipts_total: int,
    receipts_dedup_removed: int,
    matched_payments: pd.DataFrame,
    out_of_scope: pd.DataFrame,
    suspense_rows,
    rider_index,
    riders_in_scope: set[str],
    bolt_fleets,
    outstanding_df: pd.DataFrame,
) -> Step6Result:
    # Run summary.
    stats = run_summary.collect_stats(
        ctx=ctx, operator=operator, sources=sources,
        matched_payments=matched_payments,
        out_of_scope=out_of_scope,
        suspense_rows=suspense_rows,
        bolt_fleets=bolt_fleets,
        outstanding_df=outstanding_df,
    )
    md = run_summary.render_markdown(stats)
    pdf = run_summary.render_pdf(stats)

    # Agency performance — honour governance.Q3 (include_bolt_weekly).
    suspense_count = len(suspense_rows or [])
    gov = governance.load()
    ap_df = agency_performance.compute(
        outstanding_df=outstanding_df,
        matched_payments=matched_payments,
        total_receipts=receipts_total,
        suspense_count=suspense_count,
        invoices_all=invoices_all,
        bolt_fleets=bolt_fleets,
        include_bolt_weekly=gov.config.agency_scoring.include_bolt_weekly,
    )

    # Data quality.
    dq_df = data_quality.build_flags(
        invoices_all=invoices_all,
        receipts_dedup_removed=receipts_dedup_removed,
        riders_in_scope=riders_in_scope,
        rider_index=rider_index,
        out_of_scope_count=(0 if out_of_scope is None or out_of_scope.empty else len(out_of_scope)),
    )

    # QB exports.
    qb_inv_iif = qb_exports.invoices_to_iif(invoices_in_scope)
    qb_inv_csv = qb_exports.invoices_to_csv(invoices_in_scope)
    qb_pay_iif = qb_exports.payments_to_iif(matched_payments, bolt_fleets)
    qb_pay_csv = qb_exports.payments_to_csv(matched_payments, bolt_fleets)

    return Step6Result(
        run_summary_md=md,
        run_summary_pdf=pdf,
        agency_performance=ap_df,
        data_quality=dq_df,
        qb_invoices_iif=qb_inv_iif,
        qb_invoices_csv=qb_inv_csv,
        qb_payments_iif=qb_pay_iif,
        qb_payments_csv=qb_pay_csv,
    )


def run(ctx: RunContext) -> None:  # pragma: no cover - CLI wires the real call
    raise NotImplementedError(
        "step6_reports.compute(...) is invoked directly by the CLI with "
        "the prior steps' outputs threaded in."
    )
