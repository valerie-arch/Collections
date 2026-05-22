"""Six operator rules from the spec, each implemented as a callable
guard. Centralising them here gives one canonical place to find the
"why" and prevents the rules from drifting between steps.

Rule 1.  Unfiltered first — a filtered run is refused unless a prior
         universe (--fleet All --agency All) run exists for the same
         period. Override flag is honoured by the CLI.
Rule 2.  Name-only soft matches — a Tier 2 NAME hit with no phone and
         no ref and amount > GHS 500 routes to suspense, not matched.
Rule 3.  Overpayments → rider_credit — enforced inside `apply_fifo`
         (FIFO residual becomes credit; no auto-refund path exists).
Rule 4.  Never overwrite — `next_versioned_filename` is the only path
         that writes Drive artifacts; this guard asserts that.
Rule 5.  Agency re-assignments are forward-only — `agency_at_date()`
         in agency_history.py returns the agency in effect on a given
         date so historical payments stay with the prior agency.
Rule 6.  Single receipt → multiple invoices, no silent rounding —
         enforced by `apply_fifo` working in cents.

Each guard returns a `GuardResult(passed, reason, details)`. Wiring is
left to the caller (CLI / Step 2 / etc.) so this module stays I/O-free
and trivial to unit-test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from collections_v3.config import MAX_WEEKLY_DEDUCTION_GHS
from collections_v3.schemas import Agency, Fleet, Period, RunContext
from collections_v3.util.paths import _period_token


SOFT_MATCH_AMOUNT_THRESHOLD_GHS: float = 500.0


@dataclass
class GuardResult:
    passed: bool
    rule: str
    reason: str = ""
    details: dict | None = None

    def __bool__(self) -> bool:
        return self.passed


# ---------------------------------------------------------------------------
# Rule 1 — Unfiltered first
# ---------------------------------------------------------------------------

def _is_unfiltered(ctx: RunContext) -> bool:
    fleet = ctx.fleet.value if hasattr(ctx.fleet, "value") else ctx.fleet
    agency = ctx.agency.value if hasattr(ctx.agency, "value") else ctx.agency
    return fleet == Fleet.All.value and agency == Agency.All.value


def check_unfiltered_first(
    ctx: RunContext,
    *,
    artifacts_dir: Path = Path("artifacts"),
    allow_override: bool = False,
) -> GuardResult:
    """Refuse a filtered run unless an unfiltered run exists for the same
    period. The universe-run marker is the presence of
    `billed_invoices_by_fleet_agency_All_All_<period>.xlsx` in `artifacts/`.

    Operator can pass `allow_override=True` to bypass (CLI surfaces this as
    `--allow-filtered-first`)."""
    if _is_unfiltered(ctx):
        return GuardResult(passed=True, rule="unfiltered_first")
    if allow_override:
        return GuardResult(
            passed=True, rule="unfiltered_first",
            reason="override flag set", details={"override": True},
        )
    period = _period_token(ctx)
    marker = artifacts_dir / f"billed_invoices_by_fleet_agency_All_All_{period}.xlsx"
    if marker.exists():
        return GuardResult(passed=True, rule="unfiltered_first")
    fleet = ctx.fleet.value if hasattr(ctx.fleet, "value") else ctx.fleet
    agency = ctx.agency.value if hasattr(ctx.agency, "value") else ctx.agency
    return GuardResult(
        passed=False,
        rule="unfiltered_first",
        reason=(
            f"refused: filtered run (fleet={fleet}, agency={agency}) requires "
            f"an unfiltered universe run for period={period} first. "
            f"Expected marker: {marker.name}. "
            f"Override with --allow-filtered-first if you know what you're doing."
        ),
        details={"expected_marker": str(marker)},
    )


# ---------------------------------------------------------------------------
# Rule 2 — Name-only soft match
# ---------------------------------------------------------------------------

def check_name_only_soft_match(
    *,
    tier: str,
    amount: float,
    sender_phone: str,
    reference: str,
    narration: str = "",
    threshold: float = SOFT_MATCH_AMOUNT_THRESHOLD_GHS,
) -> GuardResult:
    """A Tier 2 NAME hit must drop to suspense if amount > threshold and
    no phone / ref / narration is present."""
    if (tier or "").upper() != "NAME":
        return GuardResult(passed=True, rule="name_only_soft_match")
    try:
        amt = float(amount or 0.0)
    except (TypeError, ValueError):
        amt = 0.0
    if amt <= threshold:
        return GuardResult(passed=True, rule="name_only_soft_match")
    if (sender_phone or "").strip() or (reference or "").strip() or (narration or "").strip():
        return GuardResult(passed=True, rule="name_only_soft_match")
    return GuardResult(
        passed=False,
        rule="name_only_soft_match",
        reason=(
            f"name-only Tier 2 match for {amt:.2f} > {threshold:.0f} GHS "
            "with no phone, ref, or narration — pushed to suspense per Rule 2"
        ),
        details={"amount": amt, "threshold": threshold},
    )


# ---------------------------------------------------------------------------
# Rule 4 — Never overwrite (helper used by drive_writer)
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"_v(\d+)\.[A-Za-z0-9]+$", re.IGNORECASE)


def check_never_overwrite(
    *, filename: str, existing_names: set[str],
) -> GuardResult:
    """Returns passed=True when the filename does NOT collide with anything
    in `existing_names`. `next_versioned_filename` already returns a
    non-colliding name; this guard is a second-layer assertion the caller
    can use right before the upload call to be extra-safe."""
    if filename in existing_names:
        return GuardResult(
            passed=False, rule="never_overwrite",
            reason=f"refused: {filename} already exists in target folder",
            details={"filename": filename},
        )
    return GuardResult(passed=True, rule="never_overwrite")
