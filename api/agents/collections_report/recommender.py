"""Per-rider next-action recommender from SOP §10 (Delinquency Management).

The ladder (paraphrased from the docx):

  0–6 days oldest open invoice → reminders (SMS + first call)
  7–13 days, ≥2 prior contacts → immobilisation_request (Head of Collections sign-off)
  14–29 days                    → call_to_guarantor, then immobilisation_request
  30–59 days                    → ebike_recovery (repossession) authorised by HoC + Finance
  60–89 days                    → final demand letter, prepare PAR 90 file
  90–179 days                   → PAR 90 legal process; assignment to external agency is a write-off trigger
  180+ days                     → write-off candidate, formal CFO/CEO review

Special cases:
- Already assigned to Hortta/TSAC: coordinate with collector; no new internal action unless cleared
- Recently immobilised + arrears cleared: remobilisation_request
- Recently logged the same action <48h ago: cool-off (don't recommend the same action)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Optional

from api.agents.collections_report.engine import InvoiceRow, _risk_band


@dataclass
class Recommendation:
    customer_id: str
    customer_name: str
    severity: str            # info | warning | critical
    recommended_action: str  # one of activities.ACTIONS, or "no_action"
    rationale: str
    oldest_open_days: int
    open_invoice_count: int
    outstanding_ghs: float
    agency: Optional[str]
    agency_assigned_at: Optional[str]
    risk_band: str = "A"      # A/B/C/D/E from lifetime collection ratio
    collection_ratio: float = 0.0
    lifetime_invoiced_ghs: float = 0.0
    last_activity_at: Optional[str] = None
    last_activity_action: Optional[str] = None


def _oldest_open_age(invoices: list[InvoiceRow], as_of: date) -> int:
    open_invs = [i for i in invoices if i.balance > 0]
    if not open_invs:
        return 0
    return max((as_of - i.invoice_date).days for i in open_invs)


def _recent_same_action(
    activity_log: list[dict], customer_id: str, action: str, cool_off_hours: int = 48
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cool_off_hours)
    for a in activity_log:
        if a.get("customer_id") != customer_id:
            continue
        if a.get("action") != action:
            continue
        ts = a.get("created_at", "")
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if t >= cutoff:
            return True
    return False


def _last_immobilisation(activity_log: list[dict], customer_id: str) -> Optional[datetime]:
    for a in activity_log:
        if a.get("customer_id") != customer_id:
            continue
        if a.get("action") != "immobilisation_request":
            continue
        try:
            return datetime.fromisoformat(a.get("created_at", "").replace("Z", "+00:00"))
        except Exception:
            continue
    return None


def _last_activity_for(activity_log: list[dict], customer_id: str) -> Optional[dict]:
    latest = None
    for a in activity_log:
        if a.get("customer_id") != customer_id:
            continue
        ts = a.get("created_at", "")
        if latest is None or ts > latest.get("created_at", ""):
            latest = a
    return latest


def recommend_for_rider(
    invoices: list[InvoiceRow],
    *,
    activity_log: list[dict],
    agency: Optional[str] = None,
    agency_assigned_at: Optional[str] = None,
    as_of: Optional[date] = None,
) -> Recommendation:
    """invoices: ALL of this rider's invoices."""
    as_of = as_of or date.today()
    if not invoices:
        raise ValueError("invoices list cannot be empty")
    cust_id = invoices[0].customer_id
    cust_name = invoices[0].customer_name

    open_invs = [i for i in invoices if i.balance > 0]
    outstanding = float(sum((i.balance for i in open_invs), Decimal("0")))
    oldest_days = _oldest_open_age(invoices, as_of)

    # Lifetime collection ratio drives the risk band per SOP.
    lifetime_invoiced = float(sum((i.total for i in invoices), Decimal("0")))
    lifetime_outstanding = float(sum((i.balance for i in invoices), Decimal("0")))
    if lifetime_invoiced > 0:
        ratio = (lifetime_invoiced - lifetime_outstanding) / lifetime_invoiced
    else:
        ratio = 0.0
    band, _ = _risk_band(ratio)

    last_act = _last_activity_for(activity_log, cust_id)
    last_at = last_act.get("created_at") if last_act else None
    last_action = last_act.get("action") if last_act else None

    # Common kwargs threaded into every return so we don't repeat ourselves.
    base = dict(
        customer_id=cust_id,
        customer_name=cust_name,
        oldest_open_days=oldest_days,
        open_invoice_count=len(open_invs),
        outstanding_ghs=outstanding,
        agency=agency,
        agency_assigned_at=agency_assigned_at,
        risk_band=band,
        collection_ratio=ratio,
        lifetime_invoiced_ghs=lifetime_invoiced,
        last_activity_at=last_at,
        last_activity_action=last_action,
    )

    # No debt → no action
    if not open_invs or outstanding <= 0:
        return Recommendation(
            severity="info",
            recommended_action="no_action",
            rationale="No open balance. Rider is current.",
            **{**base, "oldest_open_days": 0, "open_invoice_count": 0, "outstanding_ghs": 0.0},
        )

    # Already with a 3rd-party agency → coordinate, don't duplicate effort
    if agency:
        date_part = ""
        if agency_assigned_at:
            date_part = f" (assigned {agency_assigned_at[:10]})"
        return Recommendation(
            severity="warning",
            recommended_action="other",
            rationale=(
                f"Assigned to {agency}{date_part} — coordinate with the agency. "
                "Per SOP §10.5(B), assignment to an external collector triggered "
                "write-off; no further internal collections action unless the rider "
                "clears arrears."
            ),
            **base,
        )

    # Was recently immobilised? If arrears effectively cleared, recommend remobilisation.
    last_immob = _last_immobilisation(activity_log, cust_id)
    if last_immob is not None and outstanding == 0:
        return Recommendation(
            severity="info",
            recommended_action="remobilisation_request",
            rationale=(
                f"Immobilised on {last_immob.date().isoformat()} but arrears now cleared. "
                "Per SOP §10.2 reversal clause, lift within 2 working hours of reconciliation."
            ),
            **base,
        )

    # Graduated enforcement ladder
    def _make(action: str, severity: str, rationale: str) -> Recommendation:
        # Cool-off: don't recommend the same action we just took within 48h
        if _recent_same_action(activity_log, cust_id, action):
            return Recommendation(
                severity=severity,
                recommended_action="other",
                rationale=(
                    f"Same action ({action}) logged in the last 48h — wait for response. "
                    f"Underlying ladder step: {rationale}"
                ),
                **base,
            )
        return Recommendation(
            severity=severity,
            recommended_action=action,
            rationale=rationale,
            **base,
        )

    if oldest_days <= 6:
        return _make("phone_call", "info",
                     "0–6 days past due: standard reminders (SMS + first call).")
    if oldest_days <= 13:
        return _make("immobilisation_request", "warning",
                     "7–13 days past due: SOP §10.2 immobilisation after ≥2 contact attempts.")
    if oldest_days <= 29:
        return _make("call_to_guarantor", "warning",
                     "14–29 days past due: escalate via guarantor; immobilisation request if no response.")
    if oldest_days <= 59:
        return _make("ebike_recovery", "critical",
                     "30–59 days past due: SOP §10.3 repossession; brief field team and authorise with HoC + Finance.")
    if oldest_days <= 89:
        return _make("house_visit", "critical",
                     "60–89 days past due: final demand letter; field visit to surface PAR 90 evidence.")
    if oldest_days <= 179:
        return _make("other", "critical",
                     "90–179 days past due: PAR 90 legal process (SOP §10.5). Consider assignment to Hortta/TSAC — note this triggers write-off.")
    return _make("other", "critical",
                 "180+ days past due: write-off candidate — formal CFO/CEO review per SOP §10.5(C).")


def recommend_for_all(
    invoices_by_rider: dict[str, list[InvoiceRow]],
    *,
    activity_log: list[dict],
    agency_map: dict[str, dict],
    as_of: Optional[date] = None,
) -> list[Recommendation]:
    """Bulk recommendations sorted critical-first then by outstanding desc."""
    recs: list[Recommendation] = []
    for cid, invs in invoices_by_rider.items():
        agency_rec = agency_map.get(cid) or {}
        recs.append(
            recommend_for_rider(
                invs,
                activity_log=activity_log,
                agency=agency_rec.get("agency"),
                agency_assigned_at=agency_rec.get("assigned_at"),
                as_of=as_of,
            )
        )
    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    recs.sort(key=lambda r: (sev_rank.get(r.severity, 9), -r.outstanding_ghs))
    return recs
