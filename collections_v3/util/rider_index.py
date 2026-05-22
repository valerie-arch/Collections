"""Lookup indexes used by Step 2's three-tier matcher.

Built from the tagged-invoices universe (every billed rider, fleet-tagged)
PLUS optional auxiliary sources for fields the invoices don't carry:
  * Bolt earnings sheet — gives rider phone via the Momo Account column.
  * Bike Fleet sheet — gives bike VIN per rider via Assigned Rider.

The Rider Register slot from the original spec would have phones + bike_reg
in one file; until that ships, we synthesise the same shape from these two.

Index shape:
    name_list           : [(normalized_name, rider_id)]    # for Tier 2 fuzzy
    rider_id_to_name    : {rider_id: rider_name}
    rider_id_to_fleet   : {rider_id: "Wahu" | "TSA"}
    rider_id_to_agency  : {rider_id: "TSAC" | "Hortta" | "Unassigned"}
    phone_to_rider      : {canonical_phone (last 9 digits): rider_id}
    account_to_rider    : {bank account string: rider_id}
    rider_id_set        : {rider_id, ...}        # for ref matching
    bike_reg_to_rider   : {bike_reg upper-case: rider_id}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from collections_v3.io_.bike_fleet import normalize_name
from collections_v3.util.phone import normalize_phone


@dataclass
class RiderIndex:
    name_list: list[tuple[str, str]] = field(default_factory=list)
    rider_id_to_name: dict[str, str] = field(default_factory=dict)
    rider_id_to_fleet: dict[str, str] = field(default_factory=dict)
    rider_id_to_agency: dict[str, str] = field(default_factory=dict)
    phone_to_rider: dict[str, str] = field(default_factory=dict)
    account_to_rider: dict[str, str] = field(default_factory=dict)
    rider_id_set: set[str] = field(default_factory=set)
    bike_reg_to_rider: dict[str, str] = field(default_factory=dict)


def build_index(
    invoices_all: pd.DataFrame,
    *,
    bolt_earnings: Optional[pd.DataFrame] = None,
    bike_fleet_assignments: Optional[pd.DataFrame] = None,
    zoho_payments: Optional[pd.DataFrame] = None,
) -> RiderIndex:
    """Build the lookup index for Step 2.

    `invoices_all` must have: rider_id, rider_name, fleet, agency.
    `bolt_earnings` (optional): rider_name, momo_account — provides phones.
    `bike_fleet_assignments` (optional): rider_name, bike_reg.
    `zoho_payments` (optional): customer_id, customer_name, reference_number,
        payment_mode — used to learn bank account → rider mappings.
    """
    idx = RiderIndex()

    # Primary: rider_id -> name/fleet/agency from invoices.
    if invoices_all is not None and not invoices_all.empty:
        # Take first observation per rider_id; invoices are pre-aggregated.
        first = invoices_all.drop_duplicates(subset=["rider_id"], keep="first")
        for r in first.itertuples(index=False):
            rid = str(r.rider_id).strip()
            if not rid:
                continue
            name = str(r.rider_name).strip()
            idx.rider_id_to_name[rid] = name
            idx.rider_id_to_fleet[rid] = str(r.fleet).strip() if getattr(r, "fleet", None) else ""
            idx.rider_id_to_agency[rid] = str(r.agency).strip() if getattr(r, "agency", None) else ""
            idx.rider_id_set.add(rid)
            if name:
                idx.name_list.append((normalize_name(name), rid))

    # Phones from Bolt — join by rider_name.
    if bolt_earnings is not None and not bolt_earnings.empty:
        name_to_rid = {normalize_name(n): rid
                       for n, rid in zip(
                           [idx.rider_id_to_name[r] for r in idx.rider_id_set],
                           list(idx.rider_id_set),
                       )}
        for r in bolt_earnings.itertuples(index=False):
            name_key = normalize_name(str(r.rider_name))
            rid = name_to_rid.get(name_key)
            if not rid:
                continue
            phone = normalize_phone(str(getattr(r, "momo_account", "")))
            if phone:
                idx.phone_to_rider.setdefault(phone, rid)

    # Bike registrations.
    if bike_fleet_assignments is not None and not bike_fleet_assignments.empty:
        name_to_rid = {normalize_name(n): rid
                       for n, rid in zip(
                           [idx.rider_id_to_name[r] for r in idx.rider_id_set],
                           list(idx.rider_id_set),
                       )}
        for r in bike_fleet_assignments.itertuples(index=False):
            name_key = normalize_name(str(getattr(r, "rider_name", "")))
            rid = name_to_rid.get(name_key)
            if not rid:
                continue
            bike = str(getattr(r, "bike_reg", "")).strip().upper()
            if bike:
                idx.bike_reg_to_rider.setdefault(bike, rid)

    # Bank account associations learnt from Zoho payments history. For any
    # zoho_payment whose payment_mode looks bank-ish and reference_number is
    # a recognisable account string, attach reference_number -> rider.
    if zoho_payments is not None and not zoho_payments.empty:
        for r in zoho_payments.itertuples(index=False):
            mode = str(getattr(r, "payment_mode", "")).strip().lower()
            if not mode or mode in {"mtn", "vodafone", "telecel", "airteltigo"}:
                continue  # mobile-money modes don't yield bank accounts here
            ref = str(getattr(r, "reference_number", "")).strip()
            cust_name = str(getattr(r, "customer_name", "")).strip()
            if not ref or not cust_name:
                continue
            # Look up rider_id by name.
            for n_norm, rid in idx.name_list:
                if n_norm == normalize_name(cust_name):
                    idx.account_to_rider.setdefault(ref, rid)
                    break

    return idx
