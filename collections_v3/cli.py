"""`collections` CLI — typer entrypoint for the v3 pipeline.

  collections run --fleet {Wahu|TSA|All} \
                  --period {Week|MTD|Lifetime|Custom} \
                  --agency {TSAC|Hortta|Unassigned|All} \
                  [--start YYYY-MM-DD --end YYYY-MM-DD]

Filters AND-compose. Defaults: --fleet All, --period Week, --agency All.

All 6 reconciliation steps + the initial invoice pull are wired:
step0 → step1 → step2 → step3 → step4 → step5 → step6.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import typer

from collections_v3 import governance
from collections_v3.config import DRIVE_FOLDER_COLLECTIONS
from collections_v3.io_.suspense_persistence import read_suspense_xlsx
from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.steps import (
    step0_invoices, step1_load, step2_match, step3_suspense,
    step4_outstanding, step5_bolt_payout, step6_reports,
)
from collections_v3.util.drive_writer import upload_artifact
from collections_v3.util.operator_rules import check_unfiltered_first
from collections_v3.util.paths import build_filename
from collections_v3.util.rider_index import build_index

logger = logging.getLogger(__name__)
app = typer.Typer(
    add_completion=False,
    help="collections_v3 — rider reconciliation pipeline.",
    no_args_is_help=True,
)


# Force typer to keep `run` as a subcommand even though it's currently the
# only one — without this, typer collapses a single-command app to root and
# `collections run ...` would have to become `collections ...`.
@app.callback()
def _root() -> None:
    """collections_v3 CLI."""


def resolve_window(period: Period, start: Optional[date], end: Optional[date], *, today: Optional[date] = None) -> tuple[Optional[date], Optional[date]]:
    """Translate the --period flag into a concrete (start, end) date window.

    Week     -> prior ISO week, Mon-Sun
    MTD      -> first of this month through today
    Lifetime -> (None, None)
    Custom   -> caller must pass both --start and --end
    """
    today = today or date.today()
    if period == Period.Lifetime:
        return None, None
    if period == Period.Custom:
        if not (start and end):
            raise typer.BadParameter("--period Custom requires --start AND --end")
        if start > end:
            raise typer.BadParameter("--start must be on or before --end")
        return start, end
    if period == Period.MTD:
        return today.replace(day=1), today
    if period == Period.Week:
        # Prior ISO week (Monday-Sunday). today.weekday(): Mon=0..Sun=6.
        this_monday = today - timedelta(days=today.weekday())
        prior_monday = this_monday - timedelta(days=7)
        prior_sunday = prior_monday + timedelta(days=6)
        return prior_monday, prior_sunday
    raise typer.BadParameter(f"Unknown period {period!r}")


def _build_ctx(
    fleet: Fleet, agency: Agency, period: Period,
    start: Optional[date], end: Optional[date],
    operator: str,
) -> RunContext:
    s, e = resolve_window(period, start, end)
    return RunContext(
        fleet=fleet, agency=agency, period=period,
        start=s, end=e,
        operator=operator,
        drive_folder_id=DRIVE_FOLDER_COLLECTIONS,
    )


# ---------------------------------------------------------------------------
# `collections run`
# ---------------------------------------------------------------------------

@app.command("run")
def cmd_run(
    fleet: Fleet = typer.Option(Fleet.All, "--fleet", case_sensitive=False, help="Filter to one fleet, or All."),
    period: Period = typer.Option(Period.Week, "--period", case_sensitive=False, help="Date window for the run."),
    agency: Agency = typer.Option(Agency.All, "--agency", case_sensitive=False, help="Filter to one collection agency, or All."),
    start: Optional[datetime] = typer.Option(None, "--start", formats=["%Y-%m-%d"], help="Custom period start (inclusive)."),
    end: Optional[datetime] = typer.Option(None, "--end", formats=["%Y-%m-%d"], help="Custom period end (inclusive)."),
    operator: str = typer.Option("cli", "--operator", help="Logged as the operator on the run record."),
    no_upload: bool = typer.Option(False, "--no-upload", help="Skip Drive upload; write local XLSX only."),
    allow_filtered_first: bool = typer.Option(
        False, "--allow-filtered-first",
        help="Override Rule 1 (unfiltered-first).",
    ),
):
    """Execute the pipeline. Currently only step0 (invoice pull) is wired."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ctx = _build_ctx(
        fleet=fleet, agency=agency, period=period,
        start=start.date() if start else None,
        end=end.date() if end else None,
        operator=operator,
    )
    logger.info(
        "ctx: fleet=%s agency=%s period=%s window=%s..%s",
        ctx.fleet, ctx.agency, ctx.period, ctx.start, ctx.end,
    )

    # Governance banner (Prompt 12) — surface any Qs running on defaults.
    gov = governance.load()
    banner = governance.banner_text(gov)
    if banner:
        typer.echo(banner)

    # Operator Rule 1 — filtered runs need an unfiltered universe run first.
    guard = check_unfiltered_first(
        ctx, artifacts_dir=Path("artifacts"),
        allow_override=allow_filtered_first,
    )
    if not guard.passed:
        typer.echo(f"Rule 1 violation: {guard.reason}", err=True)
        raise typer.Exit(code=2)

    try:
        summary = step0_invoices.run_and_publish(upload=not no_upload, ctx=ctx)
    except Exception as e:
        logger.exception("step0 failed: %s", e)
        raise typer.Exit(code=2)

    typer.echo(
        f"\nstep0 done: {summary['filename']}\n"
        f"  billed: {summary['total_billed']}  Wahu: {summary['wahu_count']}  "
        f"TSA: {summary['tsa_count']}  flags: {summary['flag_count']}\n"
        f"  local: {summary['local_path']}\n"
        f"  drive: {summary['drive_link'] or '(not uploaded)'}\n"
    )

    # step1 — load, scope, opening outstanding, agency-history.
    try:
        s1 = step1_load.run(ctx)
        typer.echo(
            f"step1 done: invoices_in_scope={len(s1.invoices_in_scope)} "
            f"riders={len(s1.riders_in_scope)} receipts={len(s1.receipts)} "
            f"bolt_rows={len(s1.bolt_earnings)}"
        )
    except Exception as e:
        logger.exception("step1 failed: %s", e)
        raise typer.Exit(code=2)

    # step2 — three-tier matcher + FIFO. Requires step1 outputs + a rider
    # index built from the same sources.
    try:
        bike_assignments = None  # populated when Prompt 4's bike loader lands
        rider_index = build_index(
            invoices_all=s1.invoices_all,
            bolt_earnings=s1.bolt_earnings,
            bike_fleet_assignments=bike_assignments,
            zoho_payments=s1.zoho_payments,
        )
        s2 = step2_match.run(
            ctx, receipts=s1.receipts, invoices_all=s1.invoices_all,
            riders_in_scope=s1.riders_in_scope, rider_index=rider_index,
            zoho_payments=s1.zoho_payments,
        )
        typer.echo(
            f"step2 done: matched_rows={s2.counts['matched_rows']} "
            f"unique_receipts={s2.counts['matched_unique_receipts']} "
            f"out_of_scope={s2.counts['out_of_scope']} "
            f"already_in_zoho={s2.counts['already_in_zoho']} "
            f"suspense={s2.counts['suspense']} "
            f"credit_total={s2.counts['credit_total_ghs']} GHS"
        )
    except Exception as e:
        logger.exception("step2 failed: %s", e)
        raise typer.Exit(code=2)

    # step3 — write the suspense XLSX with decision aids + carry-forward.
    try:
        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(exist_ok=True)
        # Carry forward from the most recent prior suspense file (matched by
        # the locked artifact prefix). Drive is the source of truth once the
        # Shared-Drive issue is resolved; until then we read local.
        prior_path = _find_latest_local_suspense(artifacts_dir)
        previous_df = read_suspense_xlsx(prior_path) if prior_path else pd.DataFrame()
        out_path = artifacts_dir / build_filename("suspense", ctx)
        rows = step3_suspense.export(
            ctx,
            step2_suspense=s2.suspense,
            previous_suspense=previous_df,
            rider_index=rider_index,
            invoices_all=s1.invoices_all,
            out_path=out_path,
        )
        bucket_counts: dict[str, int] = {}
        for r in rows:
            bucket_counts[r.aging_bucket] = bucket_counts.get(r.aging_bucket, 0) + 1

        # Upload the same bytes to Drive under Monthly Matched Payments/.
        drive_link = "(not uploaded)"
        if not no_upload:
            payload = out_path.read_bytes()
            uploaded = upload_artifact("suspense", ctx, payload)
            drive_link = uploaded.get("webViewLink", "(uploaded, no link)")

        typer.echo(
            f"step3 done: {len(rows)} suspense rows\n"
            f"  local: {out_path}\n"
            f"  drive: {drive_link}\n"
            f"  aging buckets: {bucket_counts or '(none)'}\n"
            f"  carry-forward source: {prior_path or '(no prior file)'}"
        )
    except Exception as e:
        logger.exception("step3 failed: %s", e)
        raise typer.Exit(code=2)

    # step4 — refresh closing outstanding, carry credit forward.
    try:
        s4 = step4_outstanding.run(
            ctx,
            opening_outstanding=s1.opening_outstanding,
            matched_payments=s2.matched_payments,
            rider_credits_this_run=s2.rider_credits,
        )
        out_path = artifacts_dir / build_filename("rider_outstanding", ctx)
        out_path.write_bytes(step4_outstanding.write_xlsx(s4))
        drive_link = "(not uploaded)"
        if not no_upload:
            uploaded = upload_artifact("rider_outstanding", ctx, out_path.read_bytes())
            drive_link = uploaded.get("webViewLink", "(uploaded, no link)")
        typer.echo(
            f"step4 done: {s4.totals['riders']} riders | "
            f"opening={s4.totals['opening_total']:.2f}  "
            f"applied={s4.totals['applied_total']:.2f}  "
            f"closing_outstanding={s4.totals['closing_outstanding_total']:.2f}  "
            f"closing_credit={s4.totals['closing_credit_total']:.2f}\n"
            f"  local: {out_path}\n  drive: {drive_link}"
        )
    except Exception as e:
        logger.exception("step4 failed: %s", e)
        raise typer.Exit(code=2)

    # step5 — weekly Bolt payout (matrix + FIFO deduction). Always writes
    # two files: one for Wahu, one for TSA (even under --fleet All).
    try:
        s5 = step5_bolt_payout.run(
            ctx,
            bolt_earnings=s1.bolt_earnings,
            outstanding_df=s4.outstanding,
            invoices_all=s1.invoices_all,
        )
        for fleet_label, artifact_name in [("Wahu", "rider_payout_Wahu"),
                                            ("TSA", "rider_payout_TSA")]:
            fp = s5.fleets[fleet_label]
            payload = step5_bolt_payout.write_xlsx(fp)
            local_path = artifacts_dir / build_filename(artifact_name, ctx)
            local_path.write_bytes(payload)
            drive_link = "(not uploaded)"
            if not no_upload:
                uploaded = upload_artifact(artifact_name, ctx, payload)
                drive_link = uploaded.get("webViewLink", "(uploaded, no link)")
            gt = fp.grand_totals
            typer.echo(
                f"step5 [{fleet_label}] done: riders={gt.get('rider_count', 0)} "
                f"earnings={gt.get('bolt_earnings_total', 0.0):.2f}  "
                f"deduction={gt.get('deduction_total', 0.0):.2f}  "
                f"payout={gt.get('net_payout_to_rider_total', 0.0):.2f}\n"
                f"  local: {local_path}\n  drive: {drive_link}"
            )
    except Exception as e:
        logger.exception("step5 failed: %s", e)
        raise typer.Exit(code=2)

    # step6 — run summary (md + pdf), agency performance, data quality, QB exports.
    try:
        sources = [
            {"name": "Zoho invoices folder", "drive_id": "(folder)", "rows": len(s1.invoices_all)},
            {"name": f"TSA roster tab '{s1.sources_used.get('tsa_roster_tab', '')}'",
             "drive_id": "(sheet)", "rows": 0},
            {"name": "Receipts (MTN / Telecel / Bank)", "drive_id": "(folder)", "rows": len(s1.receipts)},
            {"name": "Bolt earnings", "drive_id": "(folder)", "rows": len(s1.bolt_earnings)},
        ]
        s6 = step6_reports.compute(
            ctx=ctx, operator=operator, sources=sources,
            invoices_in_scope=s1.invoices_in_scope,
            invoices_all=s1.invoices_all,
            receipts_total=len(s1.receipts),
            receipts_dedup_removed=s1.receipts_dedup_removed,
            matched_payments=s2.matched_payments,
            out_of_scope=s2.out_of_scope,
            suspense_rows=rows,            # SuspenseRow list from step3.export above
            rider_index=rider_index,
            riders_in_scope=s1.riders_in_scope,
            bolt_fleets=s5.fleets,
            outstanding_df=s4.outstanding,
        )

        # Local writes + Drive uploads. One entry per artifact slot.
        artifact_payloads = [
            ("run_summary", "md", s6.run_summary_md.encode("utf-8")),
            ("run_summary", "pdf", s6.run_summary_pdf),
            ("data_quality", "xlsx", _xlsx_bytes_from_df(s6.data_quality, "data_quality")),
            ("qb_invoices", "iif", s6.qb_invoices_iif),
            ("qb_invoices", "csv", s6.qb_invoices_csv),
            ("qb_payments", "iif", s6.qb_payments_iif),
            ("qb_payments", "csv", s6.qb_payments_csv),
        ]
        # agency_performance is a real XLSX (multi-sheet capable); use its writer.
        ap_payload = _xlsx_bytes_from_df(s6.agency_performance, "agency_performance")
        artifact_payloads.append(("agency_performance", "xlsx", ap_payload))

        for art, ext, payload in artifact_payloads:
            local_path = artifacts_dir / build_filename(art, ctx, ext=ext)
            local_path.write_bytes(payload)
            link = "(not uploaded)"
            if not no_upload:
                uploaded = upload_artifact(art, ctx, payload, ext=ext)
                link = uploaded.get("webViewLink", "(uploaded)")
            typer.echo(f"step6 [{art}.{ext}] -> {local_path}\n  drive: {link}")
    except Exception as e:
        logger.exception("step6 failed: %s", e)
        raise typer.Exit(code=2)


def _xlsx_bytes_from_df(df, sheet_name: str) -> bytes:
    """Tiny helper for the single-sheet xlsx artifacts (data_quality,
    agency_performance) so we don't ship a writer-per-artifact."""
    import io as _io
    import pandas as _pd
    buf = _io.BytesIO()
    with _pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name=sheet_name, index=False)
    return buf.getvalue()


def _find_latest_local_suspense(artifacts_dir: Path) -> Optional[Path]:
    """Return the most-recently-modified suspense_*.xlsx in artifacts/,
    or None when no prior file exists."""
    candidates = sorted(
        artifacts_dir.glob("suspense_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def main() -> int:
    try:
        app()
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
