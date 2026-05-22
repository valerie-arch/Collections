"""Step 3 — Manual suspense review.

Three public entry points:

  export(ctx, step2_suspense_df, previous_suspense_df, rider_index,
         invoices_all, out_path)
      Builds the per-receipt decision aids, computes aging, writes the
      XLSX. Carries forward unresolved rows from `previous_suspense_df`,
      bumping their `days_in_suspense`.

  reimport(path, rider_index, invoices_all, today)
      Parses an operator-edited file. Returns:
        accepted   — list[dict] ready to feed into FIFO (one per assigned row)
        rejected   — list[dict] (assignment dropped by soft-match guardrail)
        still_pending — list[dict] (operator left assigned_rider_id blank)

  run(ctx, step2_result, previous_suspense_path, out_path)
      End-to-end orchestrator used by the CLI.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from collections_v3.io_.suspense_persistence import (
    SUSPENSE_COLUMNS, SuspenseRow, read_suspense_xlsx, write_suspense_xlsx,
)
from collections_v3.schemas import RunContext
from collections_v3.util.decision_aids import Candidate, score_candidates
from collections_v3.util.rider_index import RiderIndex
from collections_v3.util.soft_match_guardrail import check_assignment
from collections_v3.util.suspense_aging import aging_bucket, days_in_suspense

logger = logging.getLogger(__name__)


def _norm_date_str(v) -> str:
    """Normalise heterogeneous date inputs (date / Timestamp / str / NaN)
    into a YYYY-MM-DD string so the same receipt produces the same key
    whether it comes from Step 2's DataFrame or an XLSX round-trip."""
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d") if isinstance(v, date) and not isinstance(v, datetime) else v.date().isoformat()
    s = str(v).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return ""
    # Strip an optional trailing time component ("2026-04-30 00:00:00" -> "2026-04-30").
    return s.split(" ")[0]


def _norm_amount_str(v) -> str:
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v).strip()


def _row_key(r) -> tuple:
    """Stable identity for a receipt — txn_id is preferred; falls back to
    the (channel, date, amount, sender_*) tuple for receipts that never
    carried a txn id. All scalar fields normalised to absorb XLSX
    round-trip differences."""
    txn = str(getattr(r, "txn_id", "") or "").strip()
    if txn:
        return ("txn", txn)
    return (
        "tuple",
        str(getattr(r, "channel", "")).strip().lower(),
        _norm_date_str(getattr(r, "date", "")),
        _norm_amount_str(getattr(r, "amount", "")),
        str(getattr(r, "sender_name", "")).strip().lower(),
        str(getattr(r, "reference", "")).strip(),
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _carry_forward_unresolved(
    previous_df: pd.DataFrame, *, today: date,
) -> dict[tuple, dict]:
    """Index of `key -> previously-known {first_seen_at, notes}` for rows
    that the operator left unassigned in the prior run."""
    out: dict[tuple, dict] = {}
    if previous_df.empty:
        return out
    for r in previous_df.itertuples(index=False):
        if str(getattr(r, "assigned_rider_id", "")).strip():
            continue
        first_seen = str(getattr(r, "first_seen_at", "")).strip()
        try:
            fs = datetime.strptime(first_seen, "%Y-%m-%d").date() if first_seen else today
        except ValueError:
            fs = today
        key = _row_key(r)
        out[key] = {"first_seen_at": fs, "notes": str(getattr(r, "notes", "") or "")}
    return out


def _candidates_for(
    receipt_row, rider_index: RiderIndex, invoices_all: pd.DataFrame,
) -> list[Candidate]:
    return score_candidates(
        sender_name=str(getattr(receipt_row, "sender_name", "")),
        sender_phone=str(getattr(receipt_row, "sender_phone_canonical", "")),
        receipt_amount=float(getattr(receipt_row, "amount", 0.0) or 0.0),
        index=rider_index,
        invoices_all=invoices_all,
        top_n=3,
    )


def export(
    ctx: RunContext,
    *,
    step2_suspense: pd.DataFrame,
    previous_suspense: pd.DataFrame,
    rider_index: RiderIndex,
    invoices_all: pd.DataFrame,
    out_path: Path,
    today: Optional[date] = None,
) -> list[SuspenseRow]:
    """Write the new suspense XLSX. Returns the rows written so callers
    can sanity-check counts without re-reading the file."""
    today = today or date.today()
    carry = _carry_forward_unresolved(previous_suspense, today=today)

    rows: list[SuspenseRow] = []
    for r in step2_suspense.itertuples(index=False):
        key = _row_key(r)
        prior = carry.pop(key, None)
        first_seen = prior["first_seen_at"] if prior else today
        notes = prior["notes"] if prior else ""

        days = days_in_suspense(first_seen, today=today)
        bucket = aging_bucket(days)

        cands = _candidates_for(r, rider_index, invoices_all)
        rows.append(SuspenseRow(
            txn_id=str(getattr(r, "txn_id", "") or ""),
            channel=str(getattr(r, "channel", "") or ""),
            date=getattr(r, "date", None),
            amount=float(getattr(r, "amount", 0.0) or 0.0),
            sender_name=str(getattr(r, "sender_name", "") or ""),
            sender_phone_canonical=str(getattr(r, "sender_phone_canonical", "") or ""),
            reference=str(getattr(r, "reference", "") or ""),
            narration=str(getattr(r, "narration", "") or ""),
            source_file=str(getattr(r, "source_file", "") or ""),
            first_seen_at=first_seen,
            days_in_suspense=days,
            aging_bucket=bucket,
            candidates=cands,
            assigned_rider_id="",
            notes=notes,
        ))

    # Anything left in `carry` is a previously-pending row that didn't
    # reappear in this run's Step 2 suspense — it carries forward unchanged
    # (still pending, days bumped via the date math above).
    for key, prior in carry.items():
        # We have only the prior metadata, not the original receipt fields.
        # Find the row in previous_suspense to copy fields from.
        match = previous_suspense.iloc[previous_suspense.apply(
            lambda r: _row_key(r) == key, axis=1
        ).values]
        if match.empty:
            continue
        m = match.iloc[0]
        first_seen = prior["first_seen_at"]
        days = days_in_suspense(first_seen, today=today)
        rows.append(SuspenseRow(
            txn_id=str(m.get("txn_id", "")),
            channel=str(m.get("channel", "")),
            date=m.get("date", None),
            amount=float(m.get("amount", 0.0) or 0.0),
            sender_name=str(m.get("sender_name", "")),
            sender_phone_canonical=str(m.get("sender_phone_canonical", "")),
            reference=str(m.get("reference", "")),
            narration=str(m.get("narration", "")),
            source_file=str(m.get("source_file", "")),
            first_seen_at=first_seen,
            days_in_suspense=days,
            aging_bucket=aging_bucket(days),
            candidates=[],  # we don't re-score carry-forwards w/o the original
            assigned_rider_id="",
            notes=prior["notes"],
        ))

    write_suspense_xlsx(rows, out_path)
    return rows


# ---------------------------------------------------------------------------
# Re-import (operator-edited file)
# ---------------------------------------------------------------------------

def reimport(
    path: Path,
    *,
    rider_index: RiderIndex,
    today: Optional[date] = None,
) -> dict:
    """Parse an operator-edited suspense file.

    Returns:
      accepted     — list[dict] (assignment honored; feed to FIFO)
      rejected     — list[dict] (soft-match guardrail blocked the assignment)
      still_pending — list[dict] (operator left assigned_rider_id blank)
    """
    today = today or date.today()
    df = read_suspense_xlsx(path)
    accepted: list[dict] = []
    rejected: list[dict] = []
    still_pending: list[dict] = []

    for r in df.itertuples(index=False):
        assigned_rid = str(getattr(r, "assigned_rider_id", "")).strip()
        rec = {c: getattr(r, c) for c in SUSPENSE_COLUMNS}
        if not assigned_rid:
            still_pending.append(rec)
            continue

        # Validate rider_id is known.
        if assigned_rid not in rider_index.rider_id_set:
            rejected.append({**rec, "reject_reason": "unknown_rider_id"})
            continue

        # Soft-match guardrail: only triggers when this was a name-only
        # match. Heuristic: if the receipt has no phone AND no reference,
        # treat it as name-only and apply the threshold.
        phone = str(getattr(r, "sender_phone_canonical", "")).strip()
        ref = str(getattr(r, "reference", "")).strip()
        narr = str(getattr(r, "narration", "")).strip()
        if not phone and not ref:
            try:
                amt = float(getattr(r, "amount", 0.0) or 0.0)
            except (TypeError, ValueError):
                amt = 0.0
            gr = check_assignment(
                amount=amt, sender_phone=phone, reference=ref, narration=narr,
            )
            if not gr.accepted:
                rejected.append({**rec, "reject_reason": gr.reason})
                continue

        accepted.append(rec)
    return {
        "accepted": accepted,
        "rejected": rejected,
        "still_pending": still_pending,
    }


# ---------------------------------------------------------------------------
# Orchestrator placeholder — wired by the CLI once Step 4 is plumbed.
# ---------------------------------------------------------------------------

def run(ctx: RunContext) -> None:  # pragma: no cover - CLI hookup tracked separately
    raise NotImplementedError(
        "step3_suspense.run is invoked via export + reimport; the CLI does "
        "the threading. Prompt 7 will wire it to step4_outstanding."
    )
