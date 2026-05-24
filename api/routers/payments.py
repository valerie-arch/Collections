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


@router.get("/list")
def list_payments(
    channel: str = Query("all", pattern="^(all|mtn|telecel|hero|bank|cash|bolt_deduction|unknown)$"),
    start: Optional[date] = None,
    end: Optional[date] = None,
    q: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """Filterable view of all rider payments.

    Sources: the Drive payments folder (MTN, Telecel, Bank, etc.) plus
    Bolt approved-deduction rows synthesized from the weekly Workings
    sheet. The reconciliation pipeline reads the same data — this endpoint
    is the read-only listing for the /payments page.
    """
    from api.agents.payments.parser import parse_folder

    PAYMENTS_LOCAL = Path("sample_inputs/payments")
    rows: list[dict] = []

    # MoMo / bank / cash receipts.
    if PAYMENTS_LOCAL.exists():
        for r in parse_folder(PAYMENTS_LOCAL):
            d = r.date
            rows.append({
                "source": "receipt",
                "channel": r.channel,
                "date": d.isoformat() if d else None,
                "amount_ghs": float(r.amount_ghs) if r.amount_ghs is not None else 0.0,
                "sender_name": (r.raw_name or "").strip(),
                "sender_phone": r.msisdn or "",
                "reference": r.reference or "",
                "narration": r.raw_name or "",
                "source_file": r.source_file,
                "txn_id": r.reference or "",
            })

    # Bolt approved-deduction synthetic receipts (the same ones Step 1
    # appends to the receipts frame). We only have these once a CLI run
    # has happened OR can pull them live from the Bolt Drive folder.
    try:
        from collections_v3.io_.bolt_earnings import (
            load_bolt_earnings, synthesize_bolt_deduction_receipts,
        )
        bolt = load_bolt_earnings()
        if not bolt.empty:
            # We don't have rider_id in this read path (no invoice scoping),
            # but the synthesizer requires it — fake one so the rows pass.
            bolt = bolt.copy()
            if "rider_id" not in bolt.columns:
                bolt["rider_id"] = bolt["rider_name"].astype(str).str.upper().str.replace(" ", "_")
            for r in synthesize_bolt_deduction_receipts(bolt).itertuples(index=False):
                d = getattr(r, "date", None)
                rows.append({
                    "source": "bolt",
                    "channel": "bolt_deduction",
                    "date": d.isoformat() if d else None,
                    "amount_ghs": float(getattr(r, "amount", 0.0) or 0.0),
                    "sender_name": getattr(r, "sender_name", ""),
                    "sender_phone": getattr(r, "sender_phone_canonical", ""),
                    "reference": getattr(r, "reference", ""),
                    "narration": getattr(r, "narration", ""),
                    "source_file": getattr(r, "source_file", ""),
                    "txn_id": getattr(r, "txn_id", ""),
                })
    except Exception as e:  # noqa: BLE001
        logger.warning("could not load Bolt deductions: %s", e)

    # Filters.
    if channel != "all":
        rows = [r for r in rows if r["channel"] == channel]
    if start is not None:
        s = start.isoformat()
        rows = [r for r in rows if r["date"] and r["date"] >= s]
    if end is not None:
        e_iso = end.isoformat()
        rows = [r for r in rows if r["date"] and r["date"] <= e_iso]
    if q:
        needle = q.strip().lower()
        if needle:
            rows = [
                r for r in rows
                if needle in r["sender_name"].lower()
                or needle in r["reference"].lower()
                or needle in r["narration"].lower()
                or needle in r["sender_phone"].lower()
            ]

    # Newest first.
    rows.sort(key=lambda r: r["date"] or "", reverse=True)

    total = len(rows)
    page = rows[offset:offset + limit]
    total_amount = sum(r["amount_ghs"] for r in rows)
    counts_by_channel: dict[str, int] = {}
    amounts_by_channel: dict[str, float] = {}
    for r in rows:
        counts_by_channel[r["channel"]] = counts_by_channel.get(r["channel"], 0) + 1
        amounts_by_channel[r["channel"]] = (
            amounts_by_channel.get(r["channel"], 0.0) + r["amount_ghs"]
        )

    return {
        "total": total,
        "total_amount_ghs": round(total_amount, 2),
        "by_channel": {
            ch: {"count": counts_by_channel[ch],
                 "amount_ghs": round(amounts_by_channel[ch], 2)}
            for ch in sorted(counts_by_channel)
        },
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
