"""Prompt 1 — Pull billed Zoho invoices, split by fleet, attach each rider's
collection agency.

Sources (all in Google Drive):
  - Zoho invoices folder (configured via ZOHO_INVOICES_DRIVE_FOLDER_ID)
  - Bike Fleet sheet — TSA tab's Assigned Rider column drives fleet tagging.
    Every billed customer not on a TSA bike is Wahu fleet.
  - Collection Assignment Zones sheet — Customer Name -> Address lookup AND
    the West Zone (-> Hortta) / East Zone (-> TSAC) tables. TSA fleet -> TSAC
    regardless of zone.

Output: `billed_invoices_by_fleet_agency_{YYYYMMDD}.xlsx` in the Collections
Data Drive folder. Four tabs:

    invoices_Wahu
    invoices_TSA
    by_agency_summary    (pivot: Fleet x Agency -> count, amount, amount_due)
    flags                (no_address / address_not_in_zones)

If today's file already exists in Drive, append `_v{n}`.
"""

from __future__ import annotations

import io
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from api.integrations.google_drive import DriveClient, get_drive_client
from collections_v3.config import TSA_DEFAULT_AGENCY
from collections_v3.io_.bike_fleet import load_tsa_roster
from collections_v3.io_.zones import load_zones
from collections_v3.io_.zoho_invoices import load_billed_invoices
from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.util.agency import (
    FLAG_ADDRESS_NOT_IN_ZONES, FLAG_NO_ADDRESS, Assignment, assign,
)
from collections_v3.util.drive_writer import upload_artifact
from collections_v3.util.paths import build_filename

logger = logging.getLogger(__name__)

ARTIFACT = "billed_invoices_by_fleet_agency"


# Agency assignment lives in collections_v3/util/agency.py so step1 can share
# the same logic. _assign here is a thin re-export for the offline test
# suite that imports it by name.

_assign = assign


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@dataclass
class Step0Result:
    invoices_wahu: pd.DataFrame
    invoices_tsa: pd.DataFrame
    by_agency_summary: pd.DataFrame
    flags: pd.DataFrame
    total_billed: int

    @property
    def split_total(self) -> int:
        return len(self.invoices_wahu) + len(self.invoices_tsa)


def run(*, client: Optional[DriveClient] = None) -> Step0Result:
    client = client or get_drive_client()

    logger.info("loading billed Zoho invoices")
    invoices = load_billed_invoices(client=client)
    logger.info("loaded %d billed invoices", len(invoices))

    logger.info("loading TSA bike roster")
    tsa_fleet = load_tsa_roster(client=client)
    logger.info(
        "TSA tab '%s': %d assigned riders (%d unique)",
        tsa_fleet.sheet_name, tsa_fleet.rider_count, len(tsa_fleet.riders),
    )

    logger.info("loading Collection Assignment Zones")
    zones = load_zones(client=client)
    logger.info(
        "zones: %d addresses, %d zone entries, sources=%s",
        len(zones.addresses), len(zones.neighborhood_to_agency), zones.source_tabs,
    )

    assigned_fleets: list[str] = []
    assigned_agencies: list[str] = []
    assigned_addresses: list[str] = []
    flag_rows: list[dict] = []

    for inv in invoices.itertuples(index=False):
        a = _assign(rider_name=inv.rider_name, tsa_fleet=tsa_fleet, zones=zones)
        assigned_fleets.append(a.fleet)
        assigned_agencies.append(a.agency)
        assigned_addresses.append(a.matched_address)
        for f in a.flags:
            flag_rows.append({
                "flag_type": f,
                "invoice_number": inv.invoice_number,
                "rider_id": inv.rider_id,
                "rider_name": inv.rider_name,
                "fleet_assigned": a.fleet,
                "agency_assigned": a.agency,
                "address": a.matched_address,
                "amount": float(inv.amount),
                "amount_due": float(inv.amount_due),
            })

    enriched = invoices.copy()
    enriched["fleet"] = assigned_fleets
    enriched["agency"] = assigned_agencies
    enriched["address"] = assigned_addresses
    enriched["amount"] = enriched["amount"].map(float)
    enriched["amount_due"] = enriched["amount_due"].map(float)

    output_cols = [
        "invoice_number", "invoice_date", "due_date",
        "rider_id", "rider_name",
        "amount", "amount_due", "status",
        "fleet", "agency", "address",
        "invoice_id", "customer_id_zoho", "source_file",
    ]
    for c in output_cols:
        if c not in enriched.columns:
            enriched[c] = ""

    invoices_wahu = enriched[enriched["fleet"] == "Wahu"][output_cols].reset_index(drop=True)
    invoices_tsa = enriched[enriched["fleet"] == "TSA"][output_cols].reset_index(drop=True)

    bad_tsa = invoices_tsa[invoices_tsa["agency"] != TSA_DEFAULT_AGENCY]
    if not bad_tsa.empty:
        raise AssertionError(
            f"{len(bad_tsa)} TSA invoices did not get agency = {TSA_DEFAULT_AGENCY}; "
            "agency assignment is broken."
        )
    blank_wahu = invoices_wahu[invoices_wahu["agency"].astype(str).str.strip() == ""]
    if not blank_wahu.empty:
        raise AssertionError(
            f"{len(blank_wahu)} Wahu invoices have blank agency; expected real agency "
            "or 'Unassigned'."
        )

    summary = (
        enriched.groupby(["fleet", "agency"], as_index=False)
        .agg(
            invoice_count=("invoice_number", "count"),
            total_amount=("amount", "sum"),
            total_amount_due=("amount_due", "sum"),
        )
        .sort_values(["fleet", "agency"])
        .reset_index(drop=True)
    )

    flags_df = pd.DataFrame(
        flag_rows,
        columns=[
            "flag_type", "invoice_number", "rider_id", "rider_name",
            "fleet_assigned", "agency_assigned", "address",
            "amount", "amount_due",
        ],
    )

    return Step0Result(
        invoices_wahu=invoices_wahu,
        invoices_tsa=invoices_tsa,
        by_agency_summary=summary,
        flags=flags_df,
        total_billed=len(invoices),
    )


# ---------------------------------------------------------------------------
# Output: XLSX + Drive upload (with _v{n} versioning)
# ---------------------------------------------------------------------------

def write_xlsx(result: Step0Result) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        result.invoices_wahu.to_excel(xw, sheet_name="invoices_Wahu", index=False)
        result.invoices_tsa.to_excel(xw, sheet_name="invoices_TSA", index=False)
        result.by_agency_summary.to_excel(xw, sheet_name="by_agency_summary", index=False)
        result.flags.to_excel(xw, sheet_name="flags", index=False)
    return buf.getvalue()


def write_local_copy(payload: bytes, filename: str) -> Path:
    out_dir = Path("artifacts")
    out_dir.mkdir(exist_ok=True)
    path = out_dir / filename
    path.write_bytes(payload)
    return path


def _default_ctx_for_step0() -> RunContext:
    """Step0 runs on the full universe by default. The CLI passes an explicit
    ctx; this helper is the fallback when run_and_publish is called directly."""
    today = date.today()
    return RunContext(
        fleet=Fleet.All, agency=Agency.All, period=Period.MTD,
        start=today.replace(day=1), end=today,
    )


def run_and_publish(*, upload: bool = True, ctx: Optional[RunContext] = None) -> dict:
    ctx = ctx or _default_ctx_for_step0()
    client = get_drive_client() if upload else None
    result = run(client=client)
    payload = write_xlsx(result)

    filename = build_filename(ARTIFACT, ctx)
    local_path = write_local_copy(payload, filename)

    uploaded: dict = {}
    if upload:
        uploaded = upload_artifact(ARTIFACT, ctx, payload, client=client)
        filename = uploaded.get("name", filename)  # honor any _v{n} bump
        # Rewrite the local copy under the same name for consistency.
        local_path = write_local_copy(payload, filename)

    summary = {
        "filename": filename,
        "local_path": str(local_path),
        "drive_id": uploaded.get("id"),
        "drive_link": uploaded.get("webViewLink"),
        "total_billed": result.total_billed,
        "split_total": result.split_total,
        "wahu_count": len(result.invoices_wahu),
        "tsa_count": len(result.invoices_tsa),
        "flag_count": len(result.flags),
    }
    if summary["total_billed"] != summary["split_total"]:
        raise AssertionError(
            f"split_total {summary['split_total']} != total_billed "
            f"{summary['total_billed']} — every billed invoice must land in "
            "exactly one fleet tab."
        )
    return summary


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Prompt 1 — billed invoices by fleet/agency.")
    parser.add_argument(
        "--no-upload", action="store_true",
        help="Skip Drive upload; write local XLSX only.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        summary = run_and_publish(upload=not args.no_upload)
    except Exception as e:
        logger.exception("step0_invoices failed: %s", e)
        return 2
    print(
        "\nbilled_invoices_by_fleet_agency written.\n"
        f"  file        : {summary['filename']}\n"
        f"  local       : {summary['local_path']}\n"
        f"  drive id    : {summary['drive_id']}\n"
        f"  drive link  : {summary['drive_link']}\n"
        f"  billed total: {summary['total_billed']}\n"
        f"  Wahu count  : {summary['wahu_count']}\n"
        f"  TSA count   : {summary['tsa_count']}\n"
        f"  flags       : {summary['flag_count']}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
