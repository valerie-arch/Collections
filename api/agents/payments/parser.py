"""Flexible payment statement parser.

Handles a wide range of MoMo / bank / Wahu-internal CSV and XLSX shapes by
fuzzy-matching column headers. Each output row is a normalised PaymentRow.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass
class PaymentRow:
    source_file: str
    line_no: int
    date: Optional[date]
    amount_ghs: Decimal
    raw_name: str            # whatever was in the "name" / "narration" / "description" column
    msisdn: Optional[str]    # phone number if found
    reference: str           # txn id / cheque ref / wallet ref
    channel: str             # mtn | telecel | hero | bank | bolt_deduction | cash | unknown
    raw: dict                # original row, for debugging / audit


# Column aliases — case-insensitive substring match.
_DATE_KEYS = ("date", "txn date", "transaction date", "value date", "posted")
_AMOUNT_KEYS = ("amount", "credit", "credit amount", "amount paid", "amount (ghs)", "total")
_NAME_KEYS = ("name", "narration", "description", "details", "customer", "sender", "payer")
_PHONE_KEYS = ("phone", "msisdn", "mobile", "number", "sender phone", "msisdn / phone")
_REF_KEYS = ("reference", "ref", "txn id", "transaction id", "transaction ref", "wallet id", "cheque", "reference number")
_CHANNEL_KEYS = ("channel", "mode", "payment mode", "method", "source")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _find_col(headers: list[str], aliases: tuple[str, ...]) -> Optional[str]:
    norm_headers = [(h, _norm(h)) for h in headers]
    # Exact match first
    for original, n in norm_headers:
        if n in aliases:
            return original
    # Substring match
    for original, n in norm_headers:
        for a in aliases:
            if a in n:
                return original
    return None


def _parse_date(v: str) -> Optional[date]:
    v = (v or "").strip()
    if not v:
        return None
    fmts = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d-%b-%Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    )
    for f in fmts:
        try:
            return datetime.strptime(v[: len(f) + 4], f).date()
        except ValueError:
            continue
    # Last resort: ISO-ish prefix
    try:
        return datetime.fromisoformat(v.split("T")[0]).date()
    except Exception:
        return None


def _parse_amount(v: str) -> Optional[Decimal]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    # Strip currency symbols / commas / parens (parens = negative)
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d\.\-]", "", s)
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if neg:
        d = -d
    return d


_GHANA_PHONE_RE = re.compile(r"(?:\+?233|0)(2\d{8}|5\d{8})")


def _extract_phone(*parts: str) -> Optional[str]:
    for p in parts:
        if not p:
            continue
        m = _GHANA_PHONE_RE.search(str(p))
        if m:
            digits = m.group(1)
            return "0" + digits  # canonical 10-digit Ghanaian form
    return None


def _detect_channel(channel_text: str, name_text: str) -> str:
    blob = f"{channel_text} {name_text}".lower()
    if "mtn" in blob or "momo" in blob or "mobile money" in blob:
        return "mtn"
    if "telecel" in blob or "vodafone" in blob:
        return "telecel"
    if "hero" in blob or "airtel" in blob:
        return "hero"
    if "bolt" in blob:
        return "bolt_deduction"
    if any(t in blob for t in ("bank", "transfer", "absa", "stanbic", "fidelity", "gcb", "ecobank", "cal", "uba")):
        return "bank"
    if "cash" in blob:
        return "cash"
    return "unknown"


def _iter_csv(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def _iter_xlsx(path: Path) -> Iterable[dict]:
    # Lazy import — only loaded if an xlsx is actually present.
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        return
    rows = ws.iter_rows(values_only=True)
    try:
        headers = [str(h or "").strip() for h in next(rows)]
    except StopIteration:
        return
    for r in rows:
        if all(v is None or v == "" for v in r):
            continue
        yield {headers[i]: ("" if v is None else v) for i, v in enumerate(r) if i < len(headers)}


def parse_payment_file(path: str | Path) -> list[PaymentRow]:
    """Parse one payment file (CSV or XLSX). Returns a list of normalised rows."""
    p = Path(path)
    if not p.exists():
        return []

    if p.suffix.lower() in (".xlsx", ".xls"):
        iterator = _iter_xlsx(p)
    else:
        iterator = _iter_csv(p)

    first = next(iter(iterator), None)
    if not first:
        return []

    headers = list(first.keys())
    col_date = _find_col(headers, _DATE_KEYS)
    col_amount = _find_col(headers, _AMOUNT_KEYS)
    col_name = _find_col(headers, _NAME_KEYS)
    col_phone = _find_col(headers, _PHONE_KEYS)
    col_ref = _find_col(headers, _REF_KEYS)
    col_channel = _find_col(headers, _CHANNEL_KEYS)

    if not col_amount:
        logger.warning("payment parser: %s has no amount column; headers=%s", p.name, headers)
        return []

    # Re-stream from the top: combine the first row with the iterator
    def streamer():
        yield first
        for r in iterator:
            yield r

    out: list[PaymentRow] = []
    for i, row in enumerate(streamer(), start=2):  # row 1 = header
        amount = _parse_amount(str(row.get(col_amount, "")))
        if amount is None or amount <= 0:
            continue
        raw_name = str(row.get(col_name, "")).strip() if col_name else ""
        msisdn = _extract_phone(
            str(row.get(col_phone, "")) if col_phone else "",
            raw_name,
            str(row.get(col_ref, "")) if col_ref else "",
        )
        ref = str(row.get(col_ref, "")).strip() if col_ref else ""
        channel = _detect_channel(
            str(row.get(col_channel, "")) if col_channel else "",
            raw_name,
        )
        out.append(
            PaymentRow(
                source_file=p.name,
                line_no=i,
                date=_parse_date(str(row.get(col_date, ""))) if col_date else None,
                amount_ghs=amount,
                raw_name=raw_name,
                msisdn=msisdn,
                reference=ref,
                channel=channel,
                raw=dict(row),
            )
        )
    return out


def parse_folder(folder: str | Path) -> list[PaymentRow]:
    """Parse every CSV/XLSX in a folder."""
    p = Path(folder)
    if not p.exists():
        return []
    out: list[PaymentRow] = []
    for child in sorted(p.iterdir()):
        if child.is_file() and child.suffix.lower() in (".csv", ".xlsx", ".xls"):
            try:
                out.extend(parse_payment_file(child))
            except Exception as e:
                logger.exception("failed to parse %s: %s", child.name, e)
    return out
