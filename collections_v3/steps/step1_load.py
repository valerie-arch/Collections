"""Step 1 — Load, filter, normalise.

Pulls all sources for the requested window, applies the agency tagger
(shared with step0), scopes invoices/Bolt earnings down via --fleet and
--agency, leaves receipts unfiltered (their fleet is inherited at match
time in step2), computes opening outstanding per rider, and persists the
rider-agency-history singleton.

Payment data is sourced from:
  * the Drive receipts folder (MTN, Telecel, Bank)
  * the Bolt weekly Payout Workings sheet — `Approved Deduction For Overdue
    Invoice` rows are synthesized into the receipts DataFrame as
    `channel = "bolt_deduction"` and direct-allocated in Step 2.

Zoho is used as an INVOICE source only — Zoho payment exports are
deliberately not loaded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from api.integrations.google_drive import DriveClient, get_drive_client
from collections_v3.io_.bike_fleet import TSAFleet, load_tsa_roster
from collections_v3.io_.bolt_earnings import (
    load_bolt_earnings, synthesize_bolt_deduction_receipts,
)
from collections_v3.io_.receipts import ReceiptsResult, load_from_drive as load_receipts
from collections_v3.io_.zoho_invoices import load_billed_invoices
from collections_v3.io_.zones import ZonesData, load_zones
from collections_v3.schemas import RunContext
from collections_v3.util.agency import assign
from collections_v3.util.agency_history import append_changes
from collections_v3.util.outstanding import opening_outstanding
from collections_v3.util.scope import ScopeResult, apply_scope

logger = logging.getLogger(__name__)


@dataclass
class Step1Result:
    invoices_all: pd.DataFrame        # every billed invoice, agency-tagged
    invoices_in_scope: pd.DataFrame   # filtered by --fleet / --agency
    riders_in_scope: set[str]
    receipts: pd.DataFrame            # UNFILTERED — fleet inherited at match time
    receipts_dedup_removed: int
    zoho_payments: pd.DataFrame       # always empty — Zoho is not a payment source
    bolt_earnings: pd.DataFrame       # may be empty (loader is stub)
    opening_outstanding: pd.DataFrame
    flags: pd.DataFrame
    agency_history_rows_after: int
    sources_used: dict = field(default_factory=dict)


def _tag_invoices(
    invoices: pd.DataFrame, tsa_fleet: TSAFleet, zones: ZonesData
) -> tuple[pd.DataFrame, list[dict]]:
    """Apply the shared agency tagger to every invoice row."""
    fleets: list[str] = []
    agencies: list[str] = []
    addresses: list[str] = []
    flag_rows: list[dict] = []

    for inv in invoices.itertuples(index=False):
        a = assign(inv.rider_name, tsa_fleet, zones)
        fleets.append(a.fleet)
        agencies.append(a.agency)
        addresses.append(a.matched_address)
        for f in a.flags:
            flag_rows.append({
                "flag_type": f,
                "rider_id": inv.rider_id,
                "rider_name": inv.rider_name,
                "fleet_assigned": a.fleet,
                "agency_assigned": a.agency,
                "address": a.matched_address,
            })

    out = invoices.copy()
    out["fleet"] = fleets
    out["agency"] = agencies
    out["address"] = addresses
    out["amount"] = out["amount"].map(float)
    out["amount_due"] = out["amount_due"].map(float)
    return out, flag_rows


def run(
    ctx: RunContext,
    *,
    client: Optional[DriveClient] = None,
    load_receipts_from_drive: bool = True,
) -> Step1Result:
    client = client or get_drive_client()

    logger.info("step1: loading billed Zoho invoices")
    invoices = load_billed_invoices(client=client)
    logger.info("step1: loaded %d billed invoices", len(invoices))

    logger.info("step1: loading TSA bike roster")
    tsa = load_tsa_roster(client=client)
    logger.info("step1: loading Collection Assignment Zones")
    zones = load_zones(client=client)

    tagged, flag_rows = _tag_invoices(invoices, tsa, zones)

    # Apply --fleet / --agency to invoices (receipts stay unfiltered).
    scoped: ScopeResult = apply_scope(tagged, ctx)
    logger.info(
        "step1: scope -> %d invoices / %d unique riders (fleet=%s agency=%s)",
        len(scoped.invoices), len(scoped.riders_in_scope), ctx.fleet, ctx.agency,
    )

    # Receipts — DELIBERATELY unfiltered per spec.
    receipts_result: ReceiptsResult
    if load_receipts_from_drive:
        try:
            receipts_result = load_receipts(client=client)
        except Exception as e:
            logger.warning("step1: receipts load failed (%s) — continuing with empty set", e)
            receipts_result = ReceiptsResult(
                receipts=pd.DataFrame(), sources=[], duplicates_removed=0,
            )
    else:
        receipts_result = ReceiptsResult(
            receipts=pd.DataFrame(), sources=[], duplicates_removed=0,
        )

    # Zoho payments are intentionally NOT loaded. Collections is sourced
    # solely from MTN/Telecel/Bank receipts and Bolt deductions; Zoho is
    # invoice-only.
    zoho_payments = pd.DataFrame()
    bolt = load_bolt_earnings(ctx=ctx, client=client)
    # Bolt is keyed on rider NAME (no rider_id in the sheet), so restrict
    # via rider_name -> rider_id from the in-scope invoices.
    if not bolt.empty and not scoped.invoices.empty:
        name_to_id = dict(
            scoped.invoices[["rider_name", "rider_id"]].astype(str).itertuples(index=False, name=None)
        )
        bolt = bolt[bolt["rider_name"].isin(name_to_id)].copy()
        bolt["rider_id"] = bolt["rider_name"].map(name_to_id)

    # Synthesize Bolt approved-deduction rows as receipts and append to the
    # main receipts frame. Step 2 routes these via the BOLT_DIRECT tier so
    # the fuzzy matcher never sees them (the rider_id is already known).
    bolt_receipts = synthesize_bolt_deduction_receipts(bolt)
    if not bolt_receipts.empty:
        # Align on receipt columns; bolt_receipts has the extra direct_rider_id
        # column which is preserved through concat.
        receipts_result = ReceiptsResult(
            receipts=pd.concat(
                [receipts_result.receipts, bolt_receipts],
                ignore_index=True, sort=False,
            ),
            sources=receipts_result.sources + ["Bolt deductions (synthesized)"],
            duplicates_removed=receipts_result.duplicates_removed,
        )

    # Opening outstanding over the IN-SCOPE invoices.
    outstanding = opening_outstanding(scoped.invoices)

    # Persist rider-agency-history changes (singleton, local-first).
    current = dict(
        scoped.invoices[["rider_id", "agency"]].astype(str).itertuples(index=False, name=None)
    )
    history = append_changes(current)

    return Step1Result(
        invoices_all=tagged,
        invoices_in_scope=scoped.invoices,
        riders_in_scope=scoped.riders_in_scope,
        receipts=receipts_result.receipts,
        receipts_dedup_removed=receipts_result.duplicates_removed,
        zoho_payments=zoho_payments,
        bolt_earnings=bolt,
        opening_outstanding=outstanding,
        flags=pd.DataFrame(flag_rows, columns=[
            "flag_type", "rider_id", "rider_name",
            "fleet_assigned", "agency_assigned", "address",
        ]),
        agency_history_rows_after=len(history),
        sources_used={
            "invoices": "Zoho Drive folder",
            "tsa_roster_tab": tsa.sheet_name,
            "zones_tabs": list(zones.source_tabs.keys()),
            "receipt_files": receipts_result.sources,
        },
    )
