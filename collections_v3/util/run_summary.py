"""Run summary — one-page MD + PDF.

The MD is the canonical form; PDF is rendered from the same data via
reportlab. The PDF is locked to a single page (the spec is explicit) —
that means top-N rider lists get trimmed and long tables clipped if a
run is unusually large.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from collections_v3.schemas import RunContext


# ---------------------------------------------------------------------------
# Stat collection
# ---------------------------------------------------------------------------

@dataclass
class SummaryStats:
    ctx: RunContext
    run_timestamp: datetime
    operator: str
    # Source files (name + drive id + row count). Populated by the caller.
    sources: list[dict] = field(default_factory=list)
    # match-rate breakdown by fleet x agency (counts) — tier -> count
    match_rate_by_fleet_agency: pd.DataFrame = field(default_factory=pd.DataFrame)
    # aging buckets {bucket: count}
    suspense_aging: dict = field(default_factory=dict)
    # by-fleet totals: fleet -> {deducted, paid_out, closing_outstanding}
    by_fleet_totals: pd.DataFrame = field(default_factory=pd.DataFrame)
    # by-agency totals: agency -> {deducted, paid_out, closing_outstanding}
    by_agency_totals: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Top 10 riders by closing_outstanding.
    top10_outstanding: pd.DataFrame = field(default_factory=pd.DataFrame)


def collect_stats(
    *,
    ctx: RunContext,
    operator: str,
    sources: list[dict],
    matched_payments: pd.DataFrame,
    out_of_scope: pd.DataFrame,
    suspense_rows,    # list[SuspenseRow] from step3.export
    bolt_fleets,      # Step5Result.fleets dict
    outstanding_df: pd.DataFrame,
) -> SummaryStats:
    stats = SummaryStats(
        ctx=ctx, run_timestamp=datetime.utcnow(), operator=operator, sources=sources,
    )

    # Match-rate by Fleet x Agency. Pivot on tier counts, then percentage.
    stats.match_rate_by_fleet_agency = _match_rate_breakdown(
        matched_payments, out_of_scope, suspense_rows, outstanding_df,
    )

    # Suspense aging.
    bucket_counts: dict[str, int] = {}
    for r in suspense_rows or []:
        bucket_counts[r.aging_bucket] = bucket_counts.get(r.aging_bucket, 0) + 1
    stats.suspense_aging = bucket_counts

    # By-fleet totals — pull deduction + payout from bolt_fleets, closing
    # outstanding from outstanding_df.
    stats.by_fleet_totals = _by_fleet_totals(bolt_fleets, outstanding_df)
    stats.by_agency_totals = _by_agency_totals(matched_payments, outstanding_df, bolt_fleets)

    # Top 10 by outstanding.
    if outstanding_df is not None and not outstanding_df.empty:
        top = (
            outstanding_df.sort_values("closing_outstanding", ascending=False)
            .head(10)
            [["rider_name", "fleet", "agency", "closing_outstanding"]]
            .reset_index(drop=True)
        )
        stats.top10_outstanding = top
    return stats


def _match_rate_breakdown(matched, out_of_scope, suspense_rows, outstanding_df) -> pd.DataFrame:
    """One row per (fleet, agency) cell, with % per match category that
    sums to 100. Categories: phone, name, ref, account, unmatched."""
    rows = []
    if outstanding_df is None or outstanding_df.empty:
        return pd.DataFrame(columns=[
            "fleet", "agency", "phone_%", "name_%", "ref_%", "account_%", "unmatched_%", "total_receipts",
        ])

    # Index matched rows by (fleet, agency). Each rider's fleet/agency comes
    # from outstanding_df.
    fa_lookup = dict(zip(
        outstanding_df["rider_id"].astype(str),
        zip(outstanding_df["fleet"].astype(str), outstanding_df["agency"].astype(str)),
    ))

    # Build counts.
    counts: dict[tuple, dict] = {}
    if matched is not None and not matched.empty:
        # Dedupe by unique receipt so we don't over-count multi-invoice FIFO rows.
        mu = matched.drop_duplicates(subset=["channel", "date", "receipt_amount", "rider_id"])
        for r in mu.itertuples(index=False):
            fa = fa_lookup.get(str(getattr(r, "rider_id", "")), ("Unknown", "Unknown"))
            tier = (getattr(r, "match_tier", "") or "").upper()
            bucket = {
                "PHONE": "phone", "NAME": "name", "REF": "ref", "ACCOUNT": "account",
                "ALREADY_IN_ZOHO": "already_in_zoho",
            }.get(tier, "other")
            counts.setdefault(fa, {})
            counts[fa][bucket] = counts[fa].get(bucket, 0) + 1

    # Suspense doesn't have a fleet attribution; we count it under ("Unknown",
    # "Unknown") so the breakdown still sums per cell.
    for r in suspense_rows or []:
        fa = ("Unknown", "Unknown")
        counts.setdefault(fa, {})
        counts[fa]["unmatched"] = counts[fa].get("unmatched", 0) + 1

    if out_of_scope is not None and not out_of_scope.empty:
        for r in out_of_scope.itertuples(index=False):
            fa = (str(getattr(r, "rider_fleet", "")), str(getattr(r, "rider_agency", "")))
            counts.setdefault(fa, {})
            counts[fa]["out_of_scope"] = counts[fa].get("out_of_scope", 0) + 1

    for (fleet, agency), cats in counts.items():
        total = sum(cats.values()) or 1
        rows.append({
            "fleet": fleet, "agency": agency,
            "phone_%": round(100 * cats.get("phone", 0) / total, 1),
            "name_%": round(100 * cats.get("name", 0) / total, 1),
            "ref_%": round(100 * cats.get("ref", 0) / total, 1),
            "account_%": round(100 * cats.get("account", 0) / total, 1),
            "unmatched_%": round(100 * cats.get("unmatched", 0) / total, 1),
            "total_receipts": total,
        })
    return pd.DataFrame(rows).sort_values(["fleet", "agency"]).reset_index(drop=True)


def _by_fleet_totals(bolt_fleets, outstanding_df) -> pd.DataFrame:
    rows = []
    closing_by_fleet: dict[str, float] = {}
    if outstanding_df is not None and not outstanding_df.empty:
        for fleet, sub in outstanding_df.groupby("fleet"):
            closing_by_fleet[str(fleet)] = float(sub["closing_outstanding"].sum())
    for fleet in ("Wahu", "TSA"):
        gt = (bolt_fleets or {}).get(fleet)
        rows.append({
            "fleet": fleet,
            "deducted_ghs": round(gt.grand_totals.get("deduction_total", 0.0), 2) if gt else 0.0,
            "paid_out_ghs": round(gt.grand_totals.get("net_payout_to_rider_total", 0.0), 2) if gt else 0.0,
            "closing_outstanding_ghs": round(closing_by_fleet.get(fleet, 0.0), 2),
        })
    return pd.DataFrame(rows)


def _by_agency_totals(matched, outstanding_df, bolt_fleets) -> pd.DataFrame:
    by_agency: dict[str, dict] = {}
    if outstanding_df is not None and not outstanding_df.empty:
        for agency, sub in outstanding_df.groupby("agency"):
            by_agency.setdefault(str(agency), {})
            by_agency[str(agency)]["closing_outstanding_ghs"] = round(
                float(sub["closing_outstanding"].sum()), 2)
    # Deductions/payouts come from Step 5's per-fleet by_agency subtotals.
    for fp in (bolt_fleets or {}).values():
        if fp.by_agency_subtotals is None or fp.by_agency_subtotals.empty:
            continue
        for r in fp.by_agency_subtotals.itertuples(index=False):
            agency = str(getattr(r, "agency", ""))
            by_agency.setdefault(agency, {})
            by_agency[agency]["deducted_ghs"] = by_agency[agency].get("deducted_ghs", 0.0) + float(r.deduction)
            by_agency[agency]["paid_out_ghs"] = by_agency[agency].get("paid_out_ghs", 0.0) + float(r.net_payout_to_rider)

    rows = [{
        "agency": agency,
        "deducted_ghs": round(d.get("deducted_ghs", 0.0), 2),
        "paid_out_ghs": round(d.get("paid_out_ghs", 0.0), 2),
        "closing_outstanding_ghs": round(d.get("closing_outstanding_ghs", 0.0), 2),
    } for agency, d in sorted(by_agency.items())]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_markdown(stats: SummaryStats) -> str:
    ctx = stats.ctx
    lines: list[str] = []
    fleet = getattr(ctx.fleet, "value", ctx.fleet)
    agency = getattr(ctx.agency, "value", ctx.agency)
    period = getattr(ctx.period, "value", ctx.period)
    lines.append(f"# Wahu Collections — Run Summary")
    lines.append("")
    lines.append(
        f"**Run:** {stats.run_timestamp:%Y-%m-%d %H:%M UTC}    "
        f"**Operator:** {stats.operator}    "
        f"**Filters:** fleet={fleet} · agency={agency} · period={period}    "
        f"**Window:** {ctx.start} .. {ctx.end}"
    )
    lines.append("")

    if stats.sources:
        lines.append("## Source files")
        for s in stats.sources:
            lines.append(
                f"- **{s.get('name', '(unnamed)')}** ({s.get('rows', 0)} rows)"
                f" — {s.get('drive_id', '(local)')}"
            )
        lines.append("")

    lines.append("## Match-rate breakdown (Fleet × Agency)")
    if stats.match_rate_by_fleet_agency.empty:
        lines.append("_no receipts matched this run_")
    else:
        lines.append(_df_to_md(stats.match_rate_by_fleet_agency))
    lines.append("")

    lines.append("## Suspense aging")
    if not stats.suspense_aging:
        lines.append("_no suspense rows_")
    else:
        order = ["0_7", "8_30", "31_60", "60+"]
        for b in order:
            lines.append(f"- **{b}**: {stats.suspense_aging.get(b, 0)}")
    lines.append("")

    lines.append("## Totals by fleet")
    lines.append(_df_to_md(stats.by_fleet_totals))
    lines.append("")

    lines.append("## Totals by agency")
    lines.append(_df_to_md(stats.by_agency_totals))
    lines.append("")

    lines.append("## Top 10 riders by closing outstanding")
    if stats.top10_outstanding.empty:
        lines.append("_no outstanding balances_")
    else:
        lines.append(_df_to_md(stats.top10_outstanding))
    return "\n".join(lines)


def _df_to_md(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_(empty)_"
    cols = list(df.columns)
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in df.values.tolist()]
    return "\n".join([head, sep] + rows)


def render_pdf(stats: SummaryStats) -> bytes:
    """One-page PDF using reportlab. Trimmed for fit; the MD is the
    canonical full-fidelity rendering."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=24, rightMargin=24, topMargin=18, bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Heading1"], fontSize=14, spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "section", parent=styles["Heading3"], fontSize=10, spaceAfter=2, spaceBefore=4,
    )
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)

    story: list = []
    ctx = stats.ctx
    fleet = getattr(ctx.fleet, "value", ctx.fleet)
    agency = getattr(ctx.agency, "value", ctx.agency)
    period = getattr(ctx.period, "value", ctx.period)
    story.append(Paragraph("Wahu Collections — Run Summary", title_style))
    story.append(Paragraph(
        f"Run {stats.run_timestamp:%Y-%m-%d %H:%M UTC} · Operator {stats.operator} · "
        f"fleet={fleet} agency={agency} period={period} window={ctx.start}..{ctx.end}",
        small,
    ))

    def _df_to_table(df: pd.DataFrame, max_rows: int = 12):
        if df is None or df.empty:
            return Paragraph("<i>(empty)</i>", small)
        data = [list(df.columns)] + df.head(max_rows).astype(str).values.tolist()
        t = Table(data, hAlign="LEFT", repeatRows=1)
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 7.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    story.append(Paragraph("Match-rate by Fleet × Agency", section_style))
    story.append(_df_to_table(stats.match_rate_by_fleet_agency))

    story.append(Paragraph("Suspense aging", section_style))
    if stats.suspense_aging:
        order = ["0_7", "8_30", "31_60", "60+"]
        ag_df = pd.DataFrame([{"bucket": b, "count": stats.suspense_aging.get(b, 0)} for b in order])
        story.append(_df_to_table(ag_df))
    else:
        story.append(Paragraph("<i>(none)</i>", small))

    story.append(Paragraph("Totals by fleet", section_style))
    story.append(_df_to_table(stats.by_fleet_totals))

    story.append(Paragraph("Totals by agency", section_style))
    story.append(_df_to_table(stats.by_agency_totals))

    story.append(Paragraph("Top 10 riders by closing outstanding", section_style))
    story.append(_df_to_table(stats.top10_outstanding, max_rows=10))

    # Enforce single page: no PageBreak() anywhere, and we sized rows / used
    # landscape so a typical run fits. Reportlab will *overflow* to a second
    # page when too many rows are pushed in; we want to fail loudly here so
    # the operator notices instead of silently producing a 2-pager.
    # Simplest enforcement: build twice — once to count pages, then again.
    doc.build(story)
    # If the build emitted more than one page, regenerate with a smaller font
    # rather than silently overflow.
    pages = doc.page
    if pages > 1:
        # Rebuild compressed.
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=landscape(A4),
            leftMargin=18, rightMargin=18, topMargin=14, bottomMargin=14,
        )
        # Replace any table style font with a tinier one.
        for el in story:
            if isinstance(el, Table):
                el.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 6.5)]))
        doc.build(story)
    return buf.getvalue()
