"""Suspense XLSX writer + operator-edited reader.

The exported file has:
  * Original receipt fields (txn_id, channel, date, amount, sender_*, ref…)
  * `first_seen_at` (set on first appearance; preserved across runs)
  * `days_in_suspense`, `aging_bucket`
  * Three decision-aid columns: candidate_1 / candidate_2 / candidate_3
    (single-line summaries from `Candidate.to_summary_str`)
  * An editable `assigned_rider_id` (operator fills in)
  * A `notes` column (operator can leave context)

On re-read, only `assigned_rider_id` (and the receipt key fields) matter to
the pipeline. Everything else round-trips for the operator's convenience.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from collections_v3.util.decision_aids import Candidate


SUSPENSE_COLUMNS = [
    "txn_id", "channel", "date", "amount",
    "sender_name", "sender_phone_canonical", "reference", "narration",
    "source_file",
    "first_seen_at", "days_in_suspense", "aging_bucket",
    "candidate_1", "candidate_2", "candidate_3",
    "assigned_rider_id", "notes",
]


@dataclass
class SuspenseRow:
    txn_id: str
    channel: str
    date: Optional[date]
    amount: float
    sender_name: str
    sender_phone_canonical: str
    reference: str
    narration: str
    source_file: str
    first_seen_at: date
    days_in_suspense: int
    aging_bucket: str
    candidates: list[Candidate]
    assigned_rider_id: str = ""
    notes: str = ""

    def to_record(self) -> dict:
        cands = self.candidates + [None, None, None]
        return {
            "txn_id": self.txn_id,
            "channel": self.channel,
            "date": self.date,
            "amount": float(self.amount),
            "sender_name": self.sender_name,
            "sender_phone_canonical": self.sender_phone_canonical,
            "reference": self.reference,
            "narration": self.narration,
            "source_file": self.source_file,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else "",
            "days_in_suspense": self.days_in_suspense,
            "aging_bucket": self.aging_bucket,
            "candidate_1": cands[0].to_summary_str() if cands[0] else "",
            "candidate_2": cands[1].to_summary_str() if cands[1] else "",
            "candidate_3": cands[2].to_summary_str() if cands[2] else "",
            "assigned_rider_id": self.assigned_rider_id,
            "notes": self.notes,
        }


def write_suspense_xlsx(rows: Iterable[SuspenseRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [r.to_record() for r in rows]
    df = pd.DataFrame(records, columns=SUSPENSE_COLUMNS)
    df.to_excel(path, index=False, engine="openpyxl")


def read_suspense_xlsx(path: Path) -> pd.DataFrame:
    """Read back an exported (and possibly operator-edited) suspense file."""
    if not path.exists():
        return pd.DataFrame(columns=SUSPENSE_COLUMNS)
    df = pd.read_excel(path, dtype=str, engine="openpyxl")
    for c in SUSPENSE_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[SUSPENSE_COLUMNS].fillna("").astype(str)
    return df
