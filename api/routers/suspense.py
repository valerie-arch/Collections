"""Suspense reconciliation endpoints — manual matching of unlinked payments."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from api.agents.collections_report.matcher import find_matches
from api.storage import suspense as store

router = APIRouter()

INVOICES_DIR = Path("sample_inputs/zoho/invoices")


@lru_cache(maxsize=2)
def _load_invoices_cached(mtime_key: float):
    from api.agents.collections_report.parsers import parse_invoice_folder
    return parse_invoice_folder(INVOICES_DIR)


def _load_invoices():
    if not INVOICES_DIR.exists():
        return []
    mtime = max((p.stat().st_mtime for p in INVOICES_DIR.glob("*.csv")), default=0.0)
    return _load_invoices_cached(mtime)


@router.get("/")
def list_items(status: Optional[str] = Query(None, pattern="^(open|resolved|booked)$")) -> dict:
    items = store.list_items(status=status)
    counts = {"open": 0, "resolved": 0, "booked": 0}
    for it in store.list_items():
        st = it.get("status", "open")
        counts[st] = counts.get(st, 0) + 1
    return {"items": items, "counts": counts}


@router.post("/")
def create_item(payload: dict = Body(...)) -> dict:
    try:
        return store.create(
            channel=payload.get("channel", "other"),
            channel_reference=payload.get("channel_reference", ""),
            amount_ghs=float(payload.get("amount_ghs", 0)),
            received_at=payload.get("received_at", date.today().isoformat()),
            msisdn=payload.get("msisdn"),
            note=payload.get("note"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{item_id}/matches")
def matches(item_id: str, tolerance: float = 2.0) -> dict:
    item = store.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="suspense item not found")
    invoices = _load_invoices()
    if not invoices:
        return {"item": item, "candidates": []}
    from decimal import Decimal as D
    tol = max(0.0, min(50.0, float(tolerance)))
    cands = find_matches(
        invoices,
        amount_ghs=item["amount_ghs"],
        msisdn=item.get("msisdn"),
        tolerance=D(str(tol)),
    )
    return {"item": item, "candidates": [asdict(c) for c in cands]}


@router.post("/{item_id}/resolve")
def resolve_item(item_id: str, payload: dict = Body(...)) -> dict:
    try:
        return store.resolve(
            item_id,
            rider_id=payload.get("rider_id", "").strip(),
            rider_name=payload.get("rider_name"),
            invoice_number=payload.get("invoice_number"),
            note=payload.get("note"),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="suspense item not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{item_id}/book")
def book_item(item_id: str, payload: dict = Body(default={})) -> dict:
    """Book the payment to the accounting suspense account."""
    try:
        return store.book_to_suspense_account(item_id, note=payload.get("note"))
    except KeyError:
        raise HTTPException(status_code=404, detail="suspense item not found")


# Legacy alias — old clients calling /escalate still work.
@router.post("/{item_id}/escalate")
def escalate_item_legacy(item_id: str, payload: dict = Body(default={})) -> dict:
    return book_item(item_id, payload)


@router.post("/{item_id}/reopen")
def reopen_item(item_id: str) -> dict:
    try:
        return store.reopen(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="suspense item not found")


@router.delete("/{item_id}")
def delete_item(item_id: str) -> dict:
    removed = store.delete(item_id)
    if not removed:
        raise HTTPException(status_code=404, detail="suspense item not found")
    return {"removed": True}
