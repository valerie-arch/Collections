"""Payment reconciliation endpoints.

Flow:
  - POST /api/payments/sync           — pull files from Drive
  - GET  /api/payments/reconcile      — run reconciliation, return JSON preview
  - GET  /api/payments/schedule.xlsx  — download the Zoho upload schedule
  - POST /api/payments/push-suspense  — push unmatched into the Suspense queue
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from api.agents.drive_sync import PAYMENTS_LOCAL_DIR, sync_payments
from api.agents.payments import reconcile_payments
from api.agents.payments.xlsx_writer import write_zoho_schedule
from api.config import settings
from api.storage import suspense as suspense_store

logger = logging.getLogger(__name__)

router = APIRouter()


INVOICES_DIR = Path("sample_inputs/zoho/invoices")


def _parse_cutoff(s: Optional[str]) -> date:
    if not s:
        return datetime.fromisoformat(settings.PAYMENTS_CUTOFF_DATE).date()
    return datetime.fromisoformat(s).date()


PAYMENTS_LOCAL = Path("sample_inputs/payments")


def _channel_to_method(ch: str) -> str:
    """Group raw parser channels into Finance-friendly methods."""
    ch = (ch or "").lower()
    if ch in {"mtn", "telecel", "hero"}:
        return "Mobile money"
    if ch == "bank":
        return "Bank transfer"
    if ch == "cash":
        return "Cash"
    if ch == "bolt_deduction":
        return "Bolt deduction"
    return "Other"


def _classify_stream(amount_ghs: float, rider_id: str, sub_map: dict) -> str:
    """Mirror /api/invoices/list stream heuristic so the two pages agree."""
    if rider_id and rider_id not in sub_map:
        return "b2b_dealer"
    if amount_ghs <= 100:
        return "rider_daily"
    return "rider_larger"


def _timeliness_bucket(days_diff: Optional[int]) -> str:
    """Days from due_date to payment_date. Negative = early."""
    if days_diff is None:
        return "Unknown"
    if days_diff < 0:
        return "Early"
    if days_diff == 0:
        return "On-time"
    if days_diff <= 7:
        return "1–7 days late"
    if days_diff <= 30:
        return "8–30 days late"
    return "30+ days late"


TIMELINESS_ORDER = [
    "Early", "On-time", "1–7 days late", "8–30 days late", "30+ days late", "Unknown",
]


@router.get("/list")
def list_payments(
    view: str = Query("mtd", pattern="^(mtd|lifetime|custom)$"),
    channel: str = Query("all", pattern="^(all|mtn|telecel|hero|bank|cash|bolt_deduction|unknown)$"),
    match_status: str = Query("all", pattern="^(all|matched|unmatched)$"),
    start: Optional[date] = None,
    end: Optional[date] = None,
    q: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    as_of: Optional[date] = None,
):
    """Filterable view of all rider payments with 5 dashboard KPIs.

    Runs the reconciliation engine inline so we can mark each row matched/
    unmatched, attach the rider name (when matched), and compute
    payment-timeliness against the invoice's due_date.
    """
    from api.agents.dashboard_v2.compute import resolve_window
    from api.agents.payments import reconcile_payments
    from api.agents.payments.parser import parse_folder
    from api.routers.trends import _load_subscription_map

    today = as_of or date.today()
    window = resolve_window(view, today, start, end)

    # ------------------------------------------------------------------
    # 0) Cold-start cache hydration. On Railway the filesystem is wiped
    # on every deploy, so on the FIRST /payments request after a deploy
    # the local cache is empty and we'd render zero MTN/Telecel/Bank
    # rows. Sync only when the cache is empty so warm requests aren't
    # paying for a full Drive walk. Subsequent users can hit
    # /payments/reconcile to force a refresh when new data arrives.
    # ------------------------------------------------------------------
    cache_empty = (
        not PAYMENTS_LOCAL.exists()
        or not any(p.is_file() and p.suffix.lower() in {".csv", ".xlsx", ".xls"}
                   for p in PAYMENTS_LOCAL.iterdir())
    )
    if cache_empty:
        try:
            sync_payments()
        except Exception as e:  # noqa: BLE001
            logger.warning("cold-start payments sync failed: %s", e)

    # ------------------------------------------------------------------
    # 1) Load raw payments (MoMo / bank / cash receipts) + Bolt synthetic
    # ------------------------------------------------------------------
    rows: list[dict] = []
    if PAYMENTS_LOCAL.exists():
        for r in parse_folder(PAYMENTS_LOCAL):
            d = r.date
            rows.append({
                "source": "receipt",
                "channel": r.channel,
                "method": _channel_to_method(r.channel),
                "date": d.isoformat() if d else None,
                "amount_ghs": float(r.amount_ghs) if r.amount_ghs is not None else 0.0,
                "sender_name": (r.raw_name or "").strip(),
                "sender_phone": r.msisdn or "",
                "reference": r.reference or "",
                "narration": r.raw_name or "",
                "source_file": r.source_file,
                "txn_id": r.reference or "",
                # Filled in after matching:
                "matched": False,
                "rider_id": "",
                "rider_name": "",
                "applied_to_invoice": "",
                "days_late": None,
                "timeliness": "Unknown",
                "stream": "rider_daily",
            })

    try:
        from collections_v3.io_.bolt_earnings import (
            load_bolt_earnings, synthesize_bolt_deduction_receipts,
        )
        bolt = load_bolt_earnings()
        if not bolt.empty:
            bolt = bolt.copy()
            if "rider_id" not in bolt.columns:
                bolt["rider_id"] = bolt["rider_name"].astype(str).str.upper().str.replace(" ", "_")
            for r in synthesize_bolt_deduction_receipts(bolt).itertuples(index=False):
                d = getattr(r, "date", None)
                rows.append({
                    "source": "bolt",
                    "channel": "bolt_deduction",
                    "method": "Bolt deduction",
                    "date": d.isoformat() if d else None,
                    "amount_ghs": float(getattr(r, "amount", 0.0) or 0.0),
                    "sender_name": getattr(r, "sender_name", ""),
                    "sender_phone": getattr(r, "sender_phone_canonical", ""),
                    "reference": getattr(r, "reference", ""),
                    "narration": getattr(r, "narration", ""),
                    "source_file": getattr(r, "source_file", ""),
                    "txn_id": getattr(r, "txn_id", ""),
                    # Bolt deductions ARE pre-matched (rider_id known on sheet).
                    "matched": True,
                    "rider_id": getattr(r, "direct_rider_id", ""),
                    "rider_name": getattr(r, "sender_name", ""),
                    "applied_to_invoice": "",
                    "days_late": None,
                    "timeliness": "Unknown",
                    "stream": "rider_larger",
                })
    except Exception as e:  # noqa: BLE001
        logger.warning("could not load Bolt deductions: %s", e)

    # ------------------------------------------------------------------
    # 2) Reconcile (only receipts; Bolt rows are already matched). Use a
    #    cutoff of date.min so we get matches on the WHOLE corpus — the
    #    view window is applied per-row below.
    # ------------------------------------------------------------------
    sub_map = _load_subscription_map()
    inv_due_by_id: dict[str, Optional[date]] = {}
    try:
        rc = reconcile_payments(
            payments_folder=PAYMENTS_LOCAL,
            invoices_folder=INVOICES_DIR,
            cutoff_date=date(2000, 1, 1),
        )
        # Build invoice_id -> due_date for timeliness math.
        from api.agents.collections_report.parsers import parse_invoice_folder
        for inv in parse_invoice_folder(INVOICES_DIR):
            inv_due_by_id[inv.invoice_id] = inv.due_date

        # Index reconciler output by (source_file, line_no) so we can
        # attach rider info back onto our raw rows. PaymentRow.line_no
        # is stable per source file.
        match_idx: dict[tuple, dict] = {}
        for m in rc.matched:
            key = (m.payment.source_file, m.payment.line_no)
            inv_id = m.allocations[0].invoice_id if m.allocations else ""
            due = inv_due_by_id.get(inv_id)
            pay_date = m.payment.date
            days_diff: Optional[int] = None
            if due and pay_date:
                days_diff = (pay_date - due).days
            match_idx[key] = {
                "rider_id": m.rider_id,
                "rider_name": m.rider_name,
                "applied_to_invoice": inv_id,
                "days_late": days_diff,
                "timeliness": _timeliness_bucket(days_diff),
                "stream": _classify_stream(
                    float(m.payment.amount_ghs or 0.0), m.rider_id, sub_map,
                ),
            }
        for r in rows:
            if r["source"] == "receipt":
                # parse_folder produces source_file with the full local path; the
                # reconciler also uses the local path, so the keys align.
                # line_no isn't carried on our row dicts — re-key by (channel,
                # date, amount, reference) which is stable enough.
                pass
        # Instead of trying to align line_no, re-key by (date, amount, txn_id).
        match_by_proxy: dict[tuple, dict] = {}
        for m in rc.matched:
            p = m.payment
            key = (
                p.date.isoformat() if p.date else "",
                round(float(p.amount_ghs or 0.0), 2),
                (p.reference or "").strip(),
            )
            inv_id = m.allocations[0].invoice_id if m.allocations else ""
            due = inv_due_by_id.get(inv_id)
            days_diff = (
                (p.date - due).days if (p.date and due) else None
            )
            match_by_proxy[key] = {
                "rider_id": m.rider_id,
                "rider_name": m.rider_name,
                "applied_to_invoice": inv_id,
                "days_late": days_diff,
                "timeliness": _timeliness_bucket(days_diff),
                "stream": _classify_stream(
                    float(p.amount_ghs or 0.0), m.rider_id, sub_map,
                ),
            }
        for r in rows:
            if r["source"] != "receipt":
                continue
            key = (r["date"] or "", round(r["amount_ghs"], 2), r["reference"])
            hit = match_by_proxy.get(key)
            if hit:
                r["matched"] = True
                r.update(hit)
    except Exception as e:  # noqa: BLE001
        logger.warning("reconciliation enrichment failed: %s", e)

    # ------------------------------------------------------------------
    # 3) Apply view (date) filter first — KPIs are scoped to the window.
    # ------------------------------------------------------------------
    if view != "lifetime":
        s = window.start.isoformat()
        e_iso = window.end.isoformat()
        rows = [r for r in rows if r["date"] and s <= r["date"] <= e_iso]
    if start is not None and view != "custom":
        rows = [r for r in rows if r["date"] and r["date"] >= start.isoformat()]
    if end is not None and view != "custom":
        rows = [r for r in rows if r["date"] and r["date"] <= end.isoformat()]

    # ------------------------------------------------------------------
    # 4) Compute summary KPIs over the windowed (but not channel-filtered) set.
    # ------------------------------------------------------------------
    summary_rows = rows
    total_payments = len(summary_rows)
    total_value = round(sum(r["amount_ghs"] for r in summary_rows), 2)
    unique_riders = len({
        r["rider_id"] for r in summary_rows if r["matched"] and r["rider_id"]
    })
    matched_count = sum(1 for r in summary_rows if r["matched"])
    matched_value = round(sum(r["amount_ghs"] for r in summary_rows if r["matched"]), 2)
    unmatched_count = total_payments - matched_count
    unmatched_value = round(total_value - matched_value, 2)

    by_method: dict[str, dict] = {}
    for r in summary_rows:
        m = r["method"]
        bucket = by_method.setdefault(m, {"method": m, "count": 0, "value_ghs": 0.0})
        bucket["count"] += 1
        bucket["value_ghs"] += r["amount_ghs"]
    by_method_list = [
        {**b, "value_ghs": round(b["value_ghs"], 2)}
        for b in by_method.values()
    ]
    by_method_list.sort(key=lambda x: -x["value_ghs"])

    timeliness_count: dict[str, int] = {b: 0 for b in TIMELINESS_ORDER}
    timeliness_value: dict[str, float] = {b: 0.0 for b in TIMELINESS_ORDER}
    for r in summary_rows:
        if not r["matched"]:
            continue
        b = r["timeliness"] or "Unknown"
        timeliness_count[b] = timeliness_count.get(b, 0) + 1
        timeliness_value[b] = timeliness_value.get(b, 0.0) + r["amount_ghs"]
    matched_with_known_due = sum(
        v for k, v in timeliness_count.items() if k != "Unknown"
    )
    matched_value_known_due = sum(
        v for k, v in timeliness_value.items() if k != "Unknown"
    )

    def _pct(num: float, den: float) -> float:
        return round((num / den) * 100, 1) if den > 0 else 0.0

    timeliness_breakdown = [
        {
            "bucket": b,
            "count": timeliness_count[b],
            "pct_count": _pct(timeliness_count[b], matched_with_known_due if b != "Unknown" else matched_count),
            "value_ghs": round(timeliness_value[b], 2),
            "pct_value": _pct(timeliness_value[b], matched_value_known_due if b != "Unknown" else matched_value),
        }
        for b in TIMELINESS_ORDER
    ]

    # ------------------------------------------------------------------
    # 5) Apply channel + match_status + search filters to the row list.
    # ------------------------------------------------------------------
    if channel != "all":
        rows = [r for r in rows if r["channel"] == channel]
    if match_status == "matched":
        rows = [r for r in rows if r["matched"]]
    elif match_status == "unmatched":
        rows = [r for r in rows if not r["matched"]]
    if q:
        needle = q.strip().lower()
        if needle:
            rows = [
                r for r in rows
                if needle in r["sender_name"].lower()
                or needle in r["rider_name"].lower()
                or needle in r["reference"].lower()
                or needle in r["narration"].lower()
                or needle in r["sender_phone"].lower()
            ]
    rows.sort(key=lambda r: r["date"] or "", reverse=True)

    row_total = len(rows)
    page = rows[offset:offset + limit]

    return {
        "as_of": today.isoformat(),
        "window": {
            "period": window.period, "start": window.start.isoformat(),
            "end": window.end.isoformat(), "label": window.label,
        },
        "filters": {
            "view": view, "channel": channel, "match_status": match_status,
        },
        "summary": {
            "total_payments": total_payments,
            "total_value_ghs": total_value,
            "unique_paying_riders": unique_riders,
            "matched_count": matched_count,
            "matched_value_ghs": matched_value,
            "unmatched_count": unmatched_count,
            "unmatched_value_ghs": unmatched_value,
            "by_method": by_method_list,
            "timeliness": timeliness_breakdown,
        },
        "row_total": row_total,
        "limit": limit,
        "offset": offset,
        "rows": page,
    }


@router.post("/sync")
def sync_drive() -> dict:
    """Pull every payment file from the configured Drive folder."""
    try:
        result = sync_payments()
        return {"ok": True, **result}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("payments drive sync failed")
        raise HTTPException(status_code=500, detail=f"sync failed: {e}")


def _serialize_result(result) -> dict:
    # Tag each unmatched payment with whether it's already in the Suspense queue
    # so the UI can show "already pushed" instead of looking like a duplicate.
    already_keys: set[str] = set()
    if result.unmatched:
        existing = {it.get("source_key") for it in suspense_store.list_items() if it.get("source_key")}
        for u in result.unmatched:
            k = f"payments:{u.payment.source_file}#{u.payment.line_no}"
            if k in existing:
                already_keys.add(k)

    return {
        "cutoff_date": result.cutoff_date.isoformat(),
        "invoices_corpus_size": result.invoices_corpus_size,
        "riders_in_master": result.riders_in_master,
        "total_payments": result.total_payments,
        "in_scope_payments": result.in_scope_payments,
        "total_matched_amount_ghs": float(result.total_matched_amount_ghs),
        "total_unmatched_amount_ghs": float(result.total_unmatched_amount_ghs),
        "matched": [
            {
                "source_file": m.payment.source_file,
                "line_no": m.payment.line_no,
                "payment_date": m.payment.date.isoformat() if m.payment.date else None,
                "amount_ghs": float(m.payment.amount_ghs),
                "channel": m.payment.channel,
                "raw_name": m.payment.raw_name,
                "msisdn": m.payment.msisdn,
                "reference": m.payment.reference,
                "rider_id": m.rider_id,
                "rider_name": m.rider_name,
                "method": m.method,
                "confidence": round(m.confidence, 3),
                "unapplied_ghs": float(m.unapplied_ghs),
                "allocations": [
                    {
                        "invoice_id": a.invoice_id,
                        "invoice_number": a.invoice_number,
                        "applied_ghs": float(a.applied_ghs),
                        "balance_before_ghs": float(a.invoice_balance_before),
                        "balance_after_ghs": float(a.invoice_balance_after),
                    }
                    for a in m.allocations
                ],
            }
            for m in result.matched
        ],
        "unmatched": [
            {
                "source_file": u.payment.source_file,
                "line_no": u.payment.line_no,
                "payment_date": u.payment.date.isoformat() if u.payment.date else None,
                "amount_ghs": float(u.payment.amount_ghs),
                "channel": u.payment.channel,
                "raw_name": u.payment.raw_name,
                "msisdn": u.payment.msisdn,
                "reference": u.payment.reference,
                "best_guess_rider_name": u.best_guess_rider_name,
                "best_guess_confidence": round(u.best_guess_confidence, 3),
                "reason": u.reason,
                "in_suspense": (
                    f"payments:{u.payment.source_file}#{u.payment.line_no}"
                    in already_keys
                ),
            }
            for u in result.unmatched
        ],
    }


@router.get("/reconcile")
def reconcile(cutoff: Optional[str] = Query(None)) -> dict:
    """Run reconciliation and return a JSON preview."""
    cutoff_date = _parse_cutoff(cutoff)
    result = reconcile_payments(
        payments_folder=PAYMENTS_LOCAL_DIR,
        invoices_folder=INVOICES_DIR,
        cutoff_date=cutoff_date,
    )
    return _serialize_result(result)


@router.get("/schedule.xlsx")
def download_schedule(cutoff: Optional[str] = Query(None)):
    """Return the Zoho upload schedule as an XLSX download."""
    cutoff_date = _parse_cutoff(cutoff)
    result = reconcile_payments(
        payments_folder=PAYMENTS_LOCAL_DIR,
        invoices_folder=INVOICES_DIR,
        cutoff_date=cutoff_date,
    )
    blob = write_zoho_schedule(result)
    today = date.today().isoformat()
    headers = {
        "Content-Disposition": f'attachment; filename="zoho_payment_schedule_{today}.xlsx"',
    }
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


def _source_key(p) -> str:
    """Stable fingerprint per payment row. Used to dedupe across re-runs."""
    return f"payments:{p.source_file}#{p.line_no}"


@router.post("/push-suspense")
def push_unmatched_to_suspense(cutoff: Optional[str] = Query(None)) -> dict:
    """Reconcile and push every unmatched payment into the Suspense queue.

    Idempotent: each payment row is fingerprinted by `source_file#line_no`,
    so re-running this never creates duplicate suspense entries.
    """
    cutoff_date = _parse_cutoff(cutoff)
    result = reconcile_payments(
        payments_folder=PAYMENTS_LOCAL_DIR,
        invoices_folder=INVOICES_DIR,
        cutoff_date=cutoff_date,
    )

    created = 0
    already = 0
    errors = 0
    for u in result.unmatched:
        p = u.payment
        ref = (p.reference or f"{p.source_file}#{p.line_no}").strip()
        key = _source_key(p)

        # Check upfront so the response distinguishes new vs deduped.
        existed_before = suspense_store.find_by_source_key(key) is not None
        try:
            suspense_store.create(
                channel=p.channel or "unknown",
                channel_reference=ref,
                amount_ghs=float(p.amount_ghs),
                received_at=p.date.isoformat() if p.date else date.today().isoformat(),
                msisdn=p.msisdn,
                note=f"Auto-pushed from payments reconcile · sender: {p.raw_name or '—'}",
                source_key=key,
            )
            if existed_before:
                already += 1
            else:
                created += 1
        except Exception as e:
            logger.warning("could not push to suspense: %s", e)
            errors += 1

    return {
        "ok": True,
        "pushed": created,
        "already_in_suspense": already,
        "errors": errors,
        "total_unmatched": len(result.unmatched),
    }
