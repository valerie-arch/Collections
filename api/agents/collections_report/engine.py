"""Report A — Collections Report engine.

Pure functions. Takes a list of InvoiceRow, returns a ReportData with the
shape needed by the xlsx writer and the /api/reports/collections JSON
endpoint. Supports lifetime, MTD, and custom-window views, plus filtering
by rider status (active / recovery / completed / all) and fleet (Wahu/TSA).

Methodology:
- Active rider = has at least one invoice in the cohort window, NOT Completed
  and NOT Churned in Zoho.
- Recovery rider = Churned in Zoho with outstanding balance > 0 (aged debt).
- Completed rider = Completed in Zoho (subscription expired / paid out).
- All = everyone with any invoice in the window.
- Lifetime invoiced = SUM(Total) for invoices in scope
- Lifetime outstanding = SUM(Balance) for invoices in scope
- Lifetime collected = invoiced - outstanding
- Collection ratio per rider = collected / invoiced
- Risk band: A ≥95%, B 80-95%, C 60-80%, D 30-60%, E <30%
- Ageing bucket: days since invoice date for invoices with Balance > 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Literal, Optional

ViewMode = Literal["lifetime", "mtd", "custom"]
StatusFilter = Literal["active", "recovery", "completed", "all"]
FleetFilter = Literal["All", "Wahu", "TSA"]


MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


@dataclass
class InvoiceRow:
    invoice_id: str
    customer_id: str
    customer_name: str
    invoice_date: date
    due_date: date | None
    status: str
    total: Decimal
    balance: Decimal
    invoice_number: str = ""
    last_payment_date: date | None = None
    is_completed: bool = False
    is_churned: bool = False
    is_tsa: bool = False
    source_file: str = ""

    @property
    def is_open(self) -> bool:
        return self.balance > 0


@dataclass
class RiderScorecard:
    customer_id: str
    customer_name: str
    first_invoice: date
    last_invoice: date
    months_since_last_invoice: int
    lifetime_invoices: int
    open_invoices: int
    lifetime_invoiced_ghs: Decimal
    lifetime_collected_ghs: Decimal
    lifetime_outstanding_ghs: Decimal
    collection_ratio: float
    risk_band: str
    plans: str = ""
    status: str = "active"  # active | recovery | completed
    fleet: str = "Wahu"  # Wahu | TSA
    agency: str | None = None  # 3rd-party collections agency, or None


@dataclass
class AgeingBucket:
    label: str
    open_invoices: int
    outstanding_ghs: Decimal


@dataclass
class BandRow:
    band: str
    riders: int
    outstanding_ghs: Decimal
    definition: str


@dataclass
class ReportData:
    view: ViewMode
    status_filter: StatusFilter
    fleet_filter: FleetFilter
    as_of: date
    window_start: date
    window_end: date
    window_label: str  # human-readable, e.g. "May 2026 (MTD)" or "Mar 1 – May 10, 2026"
    total_rider_population: int
    active_riders: int

    lifetime_invoiced_ghs: Decimal
    lifetime_collected_ghs: Decimal
    lifetime_outstanding_ghs: Decimal
    open_invoice_lines: int
    cash_in_window_ghs: Decimal               # all payments received in window
    cash_applied_to_period_ghs: Decimal       # of which: applied to invoices ISSUED in window
    cash_applied_to_prior_ghs: Decimal        # of which: applied to invoices issued earlier
    riders_paid_in_window: int                # unique riders (in filtered scope) with a payment in window

    risk_bands: list[BandRow]
    ageing: list[AgeingBucket]
    scorecards: list[RiderScorecard]


def _months_between(later: date, earlier: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def _risk_band(ratio: float) -> tuple[str, str]:
    if ratio >= 0.95:
        return "A", "≥95% paid"
    if ratio >= 0.80:
        return "B", "80–95% paid"
    if ratio >= 0.60:
        return "C", "60–80% paid"
    if ratio >= 0.30:
        return "D", "30–60% paid"
    return "E", "<30% paid"


def _ageing_label(days: int) -> str:
    if days <= 30:
        return "Current (0–30d)"
    if days <= 60:
        return "31–60d"
    if days <= 90:
        return "61–90d"
    if days <= 180:
        return "91–180d"
    if days <= 365:
        return "181–365d"
    return "365d+"


_AGEING_ORDER = [
    "Current (0–30d)", "31–60d", "61–90d", "91–180d", "181–365d", "365d+",
]


_LIFETIME_FLOOR = date(2000, 1, 1)  # anchor that comfortably predates the data


def _window_for(view: ViewMode, as_of: date,
                custom_start: date | None, custom_end: date | None) -> tuple[date, date, str]:
    if view == "mtd":
        start = as_of.replace(day=1)
        end = as_of
        label = f"{MONTH_NAMES[as_of.month]} {as_of.year} (MTD, through {as_of.isoformat()})"
        return start, end, label
    if view == "custom":
        start = custom_start or date(as_of.year, 1, 1)
        end = custom_end or as_of
        label = f"{start.isoformat()} → {end.isoformat()} (custom)"
        return start, end, label
    # Lifetime = every invoice ever, all the way back. Cohort = every rider.
    return _LIFETIME_FLOOR, as_of, f"Lifetime (all dates, through {as_of.isoformat()})"


def _rider_status(rider_invoices: list[InvoiceRow]) -> str:
    """Roll up per-invoice flags to one status per rider."""
    if any(i.is_completed for i in rider_invoices):
        return "completed"
    if any(i.is_churned for i in rider_invoices):
        return "recovery"
    return "active"


def _passes_status(rider_status: str, has_outstanding: bool, want: StatusFilter) -> bool:
    if want == "all":
        return True
    if want == "active":
        return rider_status == "active"
    if want == "completed":
        return rider_status == "completed"
    if want == "recovery":
        # Recovery = churned AND still owing money
        return rider_status == "recovery" and has_outstanding
    return True


def _passes_fleet(rider_invoices: list[InvoiceRow], fleet: FleetFilter) -> bool:
    if fleet == "All":
        return True
    is_tsa_rider = any(i.is_tsa for i in rider_invoices)
    if fleet == "TSA":
        return is_tsa_rider
    return not is_tsa_rider


def build_report(
    invoices: Iterable[InvoiceRow],
    *,
    view: ViewMode = "mtd",
    status: StatusFilter = "active",
    fleet: FleetFilter = "All",
    as_of: date | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
    subscription_status_map: dict[str, tuple[str, bool]] | None = None,
    name_fleet_map: dict[str, str] | None = None,
    agency_map: dict[str, str] | None = None,
    agency_filter: str | None = None,
) -> ReportData:
    """Build the report.

    subscription_status_map: {customer_id: (status, is_tsa)} from the Zoho
    subscriptions export. Overrides per-invoice Completed/Churned/TSA flags
    (which are typically empty in invoice exports).

    name_fleet_map: {normalized_customer_name: 'Wahu'|'TSA'} from the Wahu OS
    Bikes_and_Riders sheet. Authoritative for fleet — overrides the
    subscription TSA flag when there's a name match.

    agency_map: {customer_id: agency_name} for riders assigned to 3rd-party
    collections agencies.
    agency_filter: if set, only include riders assigned to that agency.
    """
    invoices = list(invoices)
    as_of = as_of or date.today()
    win_start, win_end, win_label = _window_for(view, as_of, window_start, window_end)

    # Recovery/Completed/All are NOT window-scoped — surface every historical
    # rider in that status. Override the label so it doesn't lie about scope.
    if status != "active":
        win_label = f"All-time {status} (window selector applies to Active only)"

    all_rider_ids = {i.customer_id for i in invoices if i.customer_id}
    total_rider_population = len(all_rider_ids)

    # Cohort gating depends on the status filter:
    #   - Active: must have an invoice in the window (currently engaged)
    #   - Recovery / Completed / All: NOT window-gated — surface every
    #     historical churned or completed rider so they can be worked,
    #     even if their last invoice was years ago.
    if status == "active":
        cohort_ids = {
            i.customer_id for i in invoices
            if win_start <= i.invoice_date <= win_end and i.customer_id
        }
    else:
        cohort_ids = all_rider_ids

    by_rider: dict[str, list[InvoiceRow]] = {}
    for inv in invoices:
        if inv.customer_id in cohort_ids:
            by_rider.setdefault(inv.customer_id, []).append(inv)

    scorecards: list[RiderScorecard] = []
    for cust_id, rider_invoices in by_rider.items():
        # Roll up status + fleet at the rider level. Subscriptions map wins
        # over invoice-derived flags when supplied, since invoice exports
        # routinely omit the Completed/Churned/TSA columns.
        if subscription_status_map and cust_id in subscription_status_map:
            rider_status, rider_is_tsa = subscription_status_map[cust_id]
        else:
            rider_status = _rider_status(rider_invoices)
            rider_is_tsa = any(i.is_tsa for i in rider_invoices)

        # OS rider list is the source of truth for fleet — override when present.
        if name_fleet_map:
            cust_name = rider_invoices[0].customer_name.strip().lower()
            os_fleet = name_fleet_map.get(cust_name)
            if os_fleet == "TSA":
                rider_is_tsa = True
            elif os_fleet == "Wahu":
                rider_is_tsa = False

        # Agency filter (3rd-party collections assignment).
        rider_agency = agency_map.get(cust_id) if agency_map else None
        if agency_filter and rider_agency != agency_filter:
            continue

        # Fleet check uses the resolved is_tsa.
        if fleet == "TSA" and not rider_is_tsa:
            continue
        if fleet == "Wahu" and rider_is_tsa:
            continue

        # Scope determines what numerator/denominator we report on per rider.
        # For Active in MTD/custom view: just the window.
        # For Recovery/Completed/All: always lifetime — historical balances
        # are what matter when triaging non-current riders.
        if status == "active" and view in ("mtd", "custom"):
            scope = [i for i in rider_invoices if win_start <= i.invoice_date <= win_end]
        else:
            scope = rider_invoices
        if not scope:
            continue

        invoiced = sum((i.total for i in scope), Decimal("0"))
        outstanding = sum((i.balance for i in scope), Decimal("0"))
        collected = invoiced - outstanding
        ratio = float(collected / invoiced) if invoiced > 0 else 0.0
        band, _ = _risk_band(ratio)
        first_i = min(i.invoice_date for i in scope)
        last_i = max(i.invoice_date for i in scope)

        if not _passes_status(rider_status, outstanding > 0, status):
            continue

        scorecards.append(RiderScorecard(
            customer_id=cust_id,
            customer_name=scope[0].customer_name,
            first_invoice=first_i,
            last_invoice=last_i,
            months_since_last_invoice=_months_between(as_of, last_i),
            lifetime_invoices=len(scope),
            open_invoices=sum(1 for i in scope if i.is_open),
            lifetime_invoiced_ghs=invoiced,
            lifetime_collected_ghs=collected,
            lifetime_outstanding_ghs=outstanding,
            collection_ratio=ratio,
            risk_band=band,
            status=rider_status,
            fleet="TSA" if rider_is_tsa else "Wahu",
            agency=rider_agency,
        ))

    # Risk band rollup
    bands_idx: dict[str, list[RiderScorecard]] = {b: [] for b in "ABCDE"}
    for s in scorecards:
        bands_idx[s.risk_band].append(s)
    band_defs = {
        "A": "≥95% paid", "B": "80–95% paid", "C": "60–80% paid",
        "D": "30–60% paid", "E": "<30% paid",
    }
    risk_bands = [
        BandRow(
            band=b,
            riders=len(bands_idx[b]),
            outstanding_ghs=sum(
                (s.lifetime_outstanding_ghs for s in bands_idx[b]),
                Decimal("0"),
            ),
            definition=band_defs[b],
        )
        for b in "ABCDE"
    ]

    # Ageing profile — open invoices in scope. Same scope rules as the rider
    # rollups above so the numbers tie out.
    surviving_rider_ids = {s.customer_id for s in scorecards}
    bucket_acc: dict[str, list[InvoiceRow]] = {label: [] for label in _AGEING_ORDER}
    open_lines: list[InvoiceRow] = []
    for cust_id in surviving_rider_ids:
        rider_invoices = by_rider[cust_id]
        if status == "active" and view in ("mtd", "custom"):
            scope = [i for i in rider_invoices if win_start <= i.invoice_date <= win_end]
        else:
            scope = rider_invoices
        for inv in scope:
            if not inv.is_open:
                continue
            days = (as_of - inv.invoice_date).days
            bucket_acc[_ageing_label(days)].append(inv)
            open_lines.append(inv)

    ageing = [
        AgeingBucket(
            label=label,
            open_invoices=len(bucket_acc[label]),
            outstanding_ghs=sum(
                (i.balance for i in bucket_acc[label]),
                Decimal("0"),
            ),
        )
        for label in _AGEING_ORDER
    ]

    total_invoiced = sum((s.lifetime_invoiced_ghs for s in scorecards), Decimal("0"))
    total_collected = sum((s.lifetime_collected_ghs for s in scorecards), Decimal("0"))
    total_outstanding = sum((s.lifetime_outstanding_ghs for s in scorecards), Decimal("0"))

    # Cash-in-window: payments where Last Payment Date falls inside the window.
    # Split it into two:
    #   - cash_applied_to_period_ghs: cash that landed on invoices issued in window
    #   - cash_applied_to_prior_ghs:  cash that landed on invoices issued earlier
    # Sum = cash_in_window_ghs (true cash flow in window).
    cash_in_window = Decimal("0")
    cash_applied_period = Decimal("0")
    cash_applied_prior = Decimal("0")
    paying_rider_ids: set[str] = set()
    for inv in invoices:
        if (
            inv.last_payment_date
            and win_start <= inv.last_payment_date <= win_end
            and inv.customer_id in surviving_rider_ids
        ):
            paid = inv.total - inv.balance
            cash_in_window += paid
            paying_rider_ids.add(inv.customer_id)
            if win_start <= inv.invoice_date <= win_end:
                cash_applied_period += paid
            else:
                cash_applied_prior += paid

    return ReportData(
        view=view,
        status_filter=status,
        fleet_filter=fleet,
        as_of=as_of,
        window_start=win_start,
        window_end=win_end,
        window_label=win_label,
        total_rider_population=total_rider_population,
        active_riders=len(scorecards),
        lifetime_invoiced_ghs=total_invoiced,
        lifetime_collected_ghs=total_collected,
        lifetime_outstanding_ghs=total_outstanding,
        open_invoice_lines=len(open_lines),
        cash_in_window_ghs=cash_in_window,
        cash_applied_to_period_ghs=cash_applied_period,
        cash_applied_to_prior_ghs=cash_applied_prior,
        riders_paid_in_window=len(paying_rider_ids),
        risk_bands=risk_bands,
        ageing=ageing,
        scorecards=sorted(
            scorecards,
            key=lambda s: s.lifetime_outstanding_ghs,
            reverse=True,
        ),
    )
