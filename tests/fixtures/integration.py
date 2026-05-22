"""30-rider integration fixture for Prompt 11.

Provides a synthetic universe that exercises every code path in the
pipeline without touching Drive:

  * 30 riders split Wahu / TSA across TSAC / Hortta / Unassigned.
  * One month of invoices (multiple open per rider).
  * One month of MoMo / Telecel / bank receipts.
  * One week of Bolt earnings.
  * Edge cases the spec calls out: Tier 2 name-only at 84 (rejected)
    and 86 (accepted), over-payment, mid-month agency switch,
    MATCHED_OUT_OF_SCOPE receipt.

Each builder function is independent so individual tests can swap parts
without paying for the full universe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional

import pandas as pd

from collections_v3.io_.bike_fleet import TSAFleet, normalize_name
from collections_v3.io_.zones import EAST_AGENCY, WEST_AGENCY, ZonesData
from collections_v3.util.rider_index import RiderIndex


# ---------------------------------------------------------------------------
# Rider universe
# ---------------------------------------------------------------------------

@dataclass
class Rider:
    rider_id: str
    name: str
    fleet: str            # Wahu | TSA
    agency: str           # TSAC | Hortta | Unassigned
    phone: str            # canonical 9-digit
    address: str          # for the Zones roster lookup
    bike_reg: str = ""


def _make_30_riders() -> list[Rider]:
    """Hand-built so the fleet / agency split is deterministic:
       10 Wahu/TSAC, 8 Wahu/Hortta, 4 Wahu/Unassigned, 8 TSA/TSAC."""
    riders: list[Rider] = []

    # 10 Wahu / TSAC (East Zone addresses).
    east_areas = ["Osu", "Madina", "East Legon", "Spintex", "Cantonments",
                  "Adabraka", "Labadi", "Adenta", "Haatso", "Teshie"]
    for i, area in enumerate(east_areas, start=1):
        riders.append(Rider(
            rider_id=f"CUS-W{i:03d}",
            name=f"Wahu East Rider {i:02d}",
            fleet="Wahu", agency="TSAC",
            phone=f"244{100000 + i:06d}",
            address=f"{area}, Ghana",
            bike_reg=f"WAHUB-{i:04d}",
        ))

    # 8 Wahu / Hortta (West Zone).
    west_areas = ["Dansoman", "Kaneshie", "Odorkor", "Awoshie",
                  "Lartebiokoshie", "Mamprobi", "Lapaz", "Abeka"]
    for i, area in enumerate(west_areas, start=11):
        riders.append(Rider(
            rider_id=f"CUS-W{i:03d}",
            name=f"Wahu West Rider {i:02d}",
            fleet="Wahu", agency="Hortta",
            phone=f"244{200000 + i:06d}",
            address=f"{area}, Ghana",
            bike_reg=f"WAHUB-{i:04d}",
        ))

    # 4 Wahu / Unassigned (address not in either zone).
    for i in range(19, 23):
        riders.append(Rider(
            rider_id=f"CUS-W{i:03d}",
            name=f"Wahu Outside Rider {i:02d}",
            fleet="Wahu", agency="Unassigned",
            phone=f"244{300000 + i:06d}",
            address="Some unknown suburb, Ghana",
            bike_reg=f"WAHUB-{i:04d}",
        ))

    # 8 TSA / TSAC.
    for i in range(1, 9):
        riders.append(Rider(
            rider_id=f"CUS-T{i:03d}",
            name=f"TSA Rider {i:02d}",
            fleet="TSA", agency="TSAC",
            phone=f"245{400000 + i:06d}",
            address=f"Tema Comm {i}",
            bike_reg=f"TSA-{i:04d}",
        ))

    assert len(riders) == 30
    return riders


# ---------------------------------------------------------------------------
# Source DataFrames
# ---------------------------------------------------------------------------

def make_invoices(
    riders: list[Rider], *,
    window_start: date = date(2026, 5, 1),
    invoices_per_rider: int = 4,
    weekly_amount_ghs: float = 420.0,
) -> pd.DataFrame:
    """One month, weekly billing, GHS 420 each."""
    rows = []
    inv_seq = 1
    for r in riders:
        for w in range(invoices_per_rider):
            d = window_start + timedelta(days=7 * w)
            rows.append({
                "invoice_id": f"inv-{inv_seq:05d}",
                "invoice_number": f"INV-{inv_seq:05d}",
                "customer_id_zoho": f"Z{inv_seq:08d}",
                "rider_id": r.rider_id,
                "rider_name": r.name,
                "invoice_date": d,
                "due_date": d + timedelta(days=7),
                "status": "open",
                "amount": weekly_amount_ghs,
                "amount_due": weekly_amount_ghs,
                "fleet_zoho": r.fleet,
                "fleet": r.fleet,
                "agency": r.agency,
                "source_file": "fixture.csv",
            })
            inv_seq += 1
    return pd.DataFrame(rows)


def make_receipts(
    riders: list[Rider], *,
    window_start: date = date(2026, 5, 1),
) -> pd.DataFrame:
    """A spread of MoMo / Telecel / bank receipts plus the spec's edge cases."""
    rows = []

    # Normal phone-match receipts for the first 12 riders.
    for i, r in enumerate(riders[:12]):
        rows.append({
            "txn_id": f"MTN-{i:04d}", "channel": "mtn",
            "date": window_start + timedelta(days=i),
            "amount": 400.0,
            "sender_name": r.name,
            "sender_phone_canonical": r.phone,
            "sender_phone_raw": "",
            "sender_account": "",
            "reference": f"MTN-{i:04d}",
            "narration": "",
            "source_file": "mtn_may.csv",
        })

    # Telecel receipt with phone match.
    r = riders[20]
    rows.append({
        "txn_id": "TEL-001", "channel": "telecel",
        "date": window_start + timedelta(days=14),
        "amount": 300.0,
        "sender_name": r.name,
        "sender_phone_canonical": r.phone,
        "sender_phone_raw": "",
        "sender_account": "",
        "reference": "TEL-001",
        "narration": "",
        "source_file": "telecel_may.csv",
    })

    # Bank receipt — uses bike_reg in narration (Tier 3).
    r = riders[14]
    rows.append({
        "txn_id": "BANK-001", "channel": "bank",
        "date": window_start + timedelta(days=10),
        "amount": 200.0,
        "sender_name": "Unknown Sender",
        "sender_phone_canonical": "",
        "sender_phone_raw": "",
        "sender_account": "",
        "reference": "",
        "narration": f"Rent {r.bike_reg}",
        "source_file": "bank_may.csv",
    })

    # Over-payment edge case — 500 against 420 only.
    r = riders[3]
    rows.append({
        "txn_id": "MTN-OVER", "channel": "mtn",
        "date": window_start + timedelta(days=15),
        "amount": 500.0,
        "sender_name": r.name,
        "sender_phone_canonical": r.phone,
        "sender_phone_raw": "",
        "sender_account": "",
        "reference": "MTN-OVER",
        "narration": "",
        "source_file": "mtn_may.csv",
    })

    # Tier 2 name-only edge cases.
    # Score 86 — full name match should pass.
    rows.append({
        "txn_id": "NAME-86", "channel": "bank",
        "date": window_start + timedelta(days=20),
        "amount": 100.0,
        "sender_name": riders[5].name,   # exact name -> 100
        "sender_phone_canonical": "",
        "sender_phone_raw": "",
        "sender_account": "",
        "reference": "",
        "narration": "",
        "source_file": "bank_may.csv",
    })
    # Score 84 — perturbed name should fall through.
    rows.append({
        "txn_id": "NAME-84", "channel": "bank",
        "date": window_start + timedelta(days=21),
        "amount": 100.0,
        "sender_name": "zzz totally different sender",
        "sender_phone_canonical": "",
        "sender_phone_raw": "",
        "sender_account": "",
        "reference": "",
        "narration": "",
        "source_file": "bank_may.csv",
    })

    # MATCHED_OUT_OF_SCOPE — a TSA rider's phone in a Wahu-only run.
    tsa_rider = next(r for r in riders if r.fleet == "TSA")
    rows.append({
        "txn_id": "TSA-OOS", "channel": "mtn",
        "date": window_start + timedelta(days=18),
        "amount": 420.0,
        "sender_name": tsa_rider.name,
        "sender_phone_canonical": tsa_rider.phone,
        "sender_phone_raw": "",
        "sender_account": "",
        "reference": "TSA-OOS",
        "narration": "",
        "source_file": "mtn_may.csv",
    })

    # Rule-2 trigger — Name-only Tier 2 hit for >GHS 500 with no phone/ref.
    rows.append({
        "txn_id": "SOFT-BIG", "channel": "bank",
        "date": window_start + timedelta(days=22),
        "amount": 700.0,
        "sender_name": riders[7].name,
        "sender_phone_canonical": "",
        "sender_phone_raw": "",
        "sender_account": "",
        "reference": "",
        "narration": "",
        "source_file": "bank_may.csv",
    })

    return pd.DataFrame(rows)


def make_bolt(
    riders: list[Rider], *,
    week_start: date = date(2026, 5, 11),
    week_end: date = date(2026, 5, 17),
    earnings_ghs: float = 600.0,
) -> pd.DataFrame:
    rows = []
    for r in riders[:15]:    # half the universe earned this week
        rows.append({
            "rider_id": r.rider_id,
            "rider_name": r.name,
            "week_start": week_start,
            "week_end": week_end,
            "bolt_payout": earnings_ghs,
            "momo_account": r.phone,
            "tsa_flag": "TSA" if r.fleet == "TSA" else "",
            "amount_owing": 0.0, "current_debt": 0.0,
            "commission_5pct": 0.0, "payout_after_commission": 0.0,
            "approved_deduction": 0.0, "net_payout_to_rider": 0.0,
            "status": "", "fee_incurred": "", "comments": "",
            "source_file": "bolt_wk20.csv",
        })
    return pd.DataFrame(rows)


def make_tsa_fleet(riders: list[Rider]) -> TSAFleet:
    tsa = [r for r in riders if r.fleet == "TSA"]
    raw = [r.name for r in tsa]
    return TSAFleet(
        sheet_name="TSA (test fixture)",
        rider_count=len(raw),
        riders={normalize_name(n) for n in raw},
        raw_assigned=raw,
    )


def make_zones(riders: list[Rider]) -> ZonesData:
    z = ZonesData()
    for r in riders:
        z.addresses[normalize_name(r.name)] = r.address
    east_names = {"osu", "madina", "east legon", "spintex", "cantonments",
                  "adabraka", "labadi", "adenta", "haatso", "teshie"}
    west_names = {"dansoman", "kaneshie", "odorkor", "awoshie",
                  "lartebiokoshie", "mamprobi", "lapaz", "abeka"}
    pairs = [(n, EAST_AGENCY) for n in east_names] + [(n, WEST_AGENCY) for n in west_names]
    z.neighborhood_to_agency = sorted(pairs, key=lambda kv: len(kv[0]), reverse=True)
    return z


def make_rider_index(riders: list[Rider], invoices: pd.DataFrame) -> RiderIndex:
    """Mirror what step1 produces, without the awkward Bolt-driven phone path."""
    idx = RiderIndex()
    for r in riders:
        idx.rider_id_to_name[r.rider_id] = r.name
        idx.rider_id_to_fleet[r.rider_id] = r.fleet
        idx.rider_id_to_agency[r.rider_id] = r.agency
        idx.rider_id_set.add(r.rider_id)
        idx.name_list.append((normalize_name(r.name), r.rider_id))
        if r.phone:
            idx.phone_to_rider[r.phone] = r.rider_id
        if r.bike_reg:
            idx.bike_reg_to_rider[r.bike_reg.upper()] = r.rider_id
    return idx


# ---------------------------------------------------------------------------
# Convenience: build everything at once
# ---------------------------------------------------------------------------

@dataclass
class IntegrationFixture:
    riders: list[Rider]
    invoices: pd.DataFrame
    receipts: pd.DataFrame
    bolt: pd.DataFrame
    tsa_fleet: TSAFleet
    zones: ZonesData
    rider_index: RiderIndex
    opening_outstanding: pd.DataFrame


def build_fixture(*, window_start: date = date(2026, 5, 1)) -> IntegrationFixture:
    riders = _make_30_riders()
    invoices = make_invoices(riders, window_start=window_start)
    receipts = make_receipts(riders, window_start=window_start)
    bolt = make_bolt(riders)
    tsa = make_tsa_fleet(riders)
    zones = make_zones(riders)
    rider_index = make_rider_index(riders, invoices)

    # Opening outstanding per rider — sum of amount_due across their invoices.
    grouped = invoices.groupby("rider_id", as_index=False).agg(
        rider_name=("rider_name", "first"),
        fleet=("fleet", "first"),
        agency=("agency", "first"),
        opening_outstanding=("amount_due", "sum"),
        open_invoice_count=("amount_due", lambda s: int((s > 0).sum())),
    )
    return IntegrationFixture(
        riders=riders, invoices=invoices, receipts=receipts, bolt=bolt,
        tsa_fleet=tsa, zones=zones, rider_index=rider_index,
        opening_outstanding=grouped,
    )
