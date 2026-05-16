"""Zoho invoice CSV parser.

Zoho Billing's invoice export has many columns; we only need a small subset.
Each row is a line item — invoices with multiple line items span multiple
rows. We aggregate into one InvoiceRow per Invoice ID, summing the line-item
totals. Cross-file deduping by Invoice ID happens in parse_invoice_folder.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from api.agents.collections_report.engine import InvoiceRow


def _to_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _to_money(s: str | None) -> Decimal:
    if s is None or s == "":
        return Decimal("0")
    cleaned = str(s).replace(",", "").replace("GHS", "").strip()
    try:
        return Decimal(cleaned)
    except Exception:
        return Decimal("0")


def _to_bool(s: str | None) -> bool:
    if not s:
        return False
    return s.strip().lower() in ("true", "yes", "1", "tsa")


# Column aliases — Zoho's export headers have varied across exports.
_INVOICE_ID = ("Invoice ID", "invoice_id")
_INVOICE_NO = ("Invoice Number", "Invoice#", "invoice_number")
_CUSTOMER_ID = ("Customer ID", "customer_id")
_CUSTOMER_NAME = ("Customer Name", "customer_name")
_INVOICE_DATE = ("Invoice Date", "invoice_date", "Date")
_DUE_DATE = ("Due Date", "due_date")
_STATUS = ("Invoice Status", "Status", "status")
_TOTAL = ("Total", "Invoice Total", "total")
_LINE_TOTAL = ("Item Total",)
_BALANCE = ("Balance", "balance", "Outstanding")
_LAST_PAYMENT = ("Last Payment Date",)
_COMPLETED = ("Completed",)
_CHURNED = ("Churned",)
_TSA = ("TSA",)


def _first(row: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return None


def parse_zoho_invoice_csv(path: str | Path) -> list[InvoiceRow]:
    """Read one Zoho invoice CSV and return one InvoiceRow per Invoice ID."""
    path = Path(path)
    by_invoice: dict[str, InvoiceRow] = {}

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            invoice_id = _first(raw, _INVOICE_ID) or _first(raw, _INVOICE_NO)
            if not invoice_id:
                continue

            line_total = _to_money(_first(raw, _LINE_TOTAL) or _first(raw, _TOTAL))

            if invoice_id in by_invoice:
                # Same invoice, additional line item — accumulate the line total.
                by_invoice[invoice_id].total += line_total
                # The status/balance/payment fields are identical across rows
                # of the same invoice; first-seen wins.
                continue

            by_invoice[invoice_id] = InvoiceRow(
                invoice_id=invoice_id,
                invoice_number=_first(raw, _INVOICE_NO) or "",
                customer_id=_first(raw, _CUSTOMER_ID) or "",
                customer_name=_first(raw, _CUSTOMER_NAME) or "",
                invoice_date=_to_date(_first(raw, _INVOICE_DATE)) or date.today(),
                due_date=_to_date(_first(raw, _DUE_DATE)),
                status=(_first(raw, _STATUS) or "").lower(),
                total=line_total,
                balance=_to_money(_first(raw, _BALANCE)),
                last_payment_date=_to_date(_first(raw, _LAST_PAYMENT)),
                is_completed=_to_bool(_first(raw, _COMPLETED)),
                is_churned=_to_bool(_first(raw, _CHURNED)),
                is_tsa=_to_bool(_first(raw, _TSA)),
                source_file=path.name,
            )

    return list(by_invoice.values())


def load_os_fleet_map(rider_fleet_csv: str | Path) -> dict[str, str]:
    """Load {normalized_rider_name: 'Wahu'|'TSA'} from sample_inputs/wahu_os/rider_fleet.csv.

    Built from Wahu_OS_Bikes_and_Riders.xlsx via build_fleet_map.py. The
    Active Rider column there is the source of truth for fleet.
    """
    path = Path(rider_fleet_csv)
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("rider_name") or "").strip().lower()
            fleet = (row.get("fleet") or "").strip()
            if name and fleet in ("Wahu", "TSA"):
                result[name] = fleet
    return result


def load_subscription_status_map(
    subscriptions_csv: str | Path,
) -> dict[str, tuple[str, bool]]:
    """Build {customer_id: (status, is_tsa)} from a Zoho subscriptions export.

    Per-customer status rollup (a customer may hold multiple subscriptions):
      - live or paused on any sub → "active"
      - else cancelled on any sub → "recovery"  (churned, may still owe)
      - else all expired         → "completed"
    is_tsa: true if any subscription has TSA flag set.
    """
    path = Path(subscriptions_csv)
    if not path.exists():
        return {}

    rollup: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cid = (row.get("Customer ID") or "").strip()
            if not cid:
                continue
            status = (row.get("Subscription Status") or "").strip().lower()
            tsa = _to_bool(row.get("TSA"))
            r = rollup.setdefault(cid, {"statuses": set(), "tsa": False})
            r["statuses"].add(status)
            r["tsa"] = r["tsa"] or tsa

    result: dict[str, tuple[str, bool]] = {}
    for cid, info in rollup.items():
        statuses = info["statuses"]
        if statuses & {"live", "paused"}:
            kind = "active"
        elif "cancelled" in statuses:
            kind = "recovery"
        elif "expired" in statuses:
            kind = "completed"
        else:
            kind = "active"
        result[cid] = (kind, info["tsa"])
    return result


def parse_invoice_folder(folder: str | Path) -> list[InvoiceRow]:
    """Parse every *.csv in a folder, dedupe across files by Invoice ID.

    Later files (alphabetical order) win on conflict — so newer exports
    override older snapshots. Important: an invoice paid AFTER an archive
    file was exported will only reflect that payment if a fresher export
    of that period is synced. See docs/google-drive-setup.md.
    """
    folder = Path(folder)
    if not folder.exists():
        return []

    deduped: dict[str, InvoiceRow] = {}
    for csv_path in sorted(folder.glob("*.csv")):
        for row in parse_zoho_invoice_csv(csv_path):
            deduped[row.invoice_id] = row
    return list(deduped.values())
