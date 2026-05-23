"""Collections Report (Report A) — engine + Excel writer.

Pure compute over an InvoiceRow stream. No DB writes. Re-runnable on demand.
"""

from api.agents.collections_report.engine import (
    InvoiceRow,
    RiderScorecard,
    ReportData,
    build_report,
)
from api.agents.collections_report.parsers import (
    load_os_fleet_map,
    load_subscription_status_dates,
    load_subscription_status_map,
    parse_zoho_invoice_csv,
)
from api.agents.collections_report.xlsx_writer import write_report_xlsx

__all__ = [
    "InvoiceRow",
    "RiderScorecard",
    "ReportData",
    "build_report",
    "load_os_fleet_map",
    "load_subscription_status_dates",
    "load_subscription_status_map",
    "parse_zoho_invoice_csv",
    "write_report_xlsx",
]
