"""Data-quality flags artifact (Step 6).

Five categories, one row per finding:
  * riders_without_agency       — agency == 'Unassigned' or blank
  * duplicate_txn_ids           — pre-dedup vs post-dedup count delta
  * missing_phones              — riders in scope with no phone indexed
  * invoices_no_rider_mapping   — invoices with blank rider_id
  * matched_out_of_scope        — count of Step 2's out_of_scope DataFrame
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from collections_v3.util.rider_index import RiderIndex


FLAG_COLUMNS = ["category", "key", "detail"]


def build_flags(
    *,
    invoices_all: pd.DataFrame,
    receipts_dedup_removed: int,
    riders_in_scope: set[str],
    rider_index: RiderIndex,
    out_of_scope_count: int,
) -> pd.DataFrame:
    rows: list[dict] = []

    if invoices_all is not None and not invoices_all.empty:
        # Riders without agency.
        unassigned = invoices_all[
            invoices_all["agency"].astype(str).str.strip().isin({"", "Unassigned"})
        ].drop_duplicates(subset=["rider_id"])
        for r in unassigned.itertuples(index=False):
            rows.append({
                "category": "riders_without_agency",
                "key": str(getattr(r, "rider_id", "")),
                "detail": str(getattr(r, "rider_name", "")),
            })

        # Invoices with no rider mapping.
        no_rider = invoices_all[invoices_all["rider_id"].astype(str).str.strip() == ""]
        for r in no_rider.itertuples(index=False):
            rows.append({
                "category": "invoices_no_rider_mapping",
                "key": str(getattr(r, "invoice_id", "")),
                "detail": str(getattr(r, "rider_name", "")) or "(blank)",
            })

    # Missing phones.
    riders_with_phone = set(rider_index.phone_to_rider.values()) if rider_index else set()
    for rid in sorted(riders_in_scope - riders_with_phone):
        rows.append({
            "category": "missing_phones",
            "key": rid,
            "detail": rider_index.rider_id_to_name.get(rid, "") if rider_index else "",
        })

    # Duplicate txn ids -- aggregate count, one summary row.
    if receipts_dedup_removed and receipts_dedup_removed > 0:
        rows.append({
            "category": "duplicate_txn_ids",
            "key": "(aggregate)",
            "detail": f"{receipts_dedup_removed} duplicate (channel, txn_id) rows dropped",
        })

    # Matched out of scope.
    if out_of_scope_count and out_of_scope_count > 0:
        rows.append({
            "category": "matched_out_of_scope",
            "key": "(aggregate)",
            "detail": f"{out_of_scope_count} receipts matched riders outside active filters",
        })

    return pd.DataFrame(rows, columns=FLAG_COLUMNS)


def write_xlsx(flags_df: pd.DataFrame) -> bytes:
    import io as _io
    buf = _io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        flags_df.to_excel(xw, sheet_name="data_quality", index=False)
        # Per-category counts on a second sheet for quick triage.
        if not flags_df.empty:
            counts = (
                flags_df.groupby("category", as_index=False)
                .size()
                .rename(columns={"size": "count"})
            )
        else:
            counts = pd.DataFrame(columns=["category", "count"])
        counts.to_excel(xw, sheet_name="counts", index=False)
    return buf.getvalue()
