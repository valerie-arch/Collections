"""Opening outstanding balance per rider.

Step 1 "compute opening outstanding per rider" — sum of `amount_due` for
all billed (i.e. non-excluded) invoices, grouped by rider_id. This is the
starting point Step 4 will recompute after each new run of Step 2/3.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd


def opening_outstanding(invoices: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame with columns: rider_id, rider_name, fleet, agency,
    opening_outstanding (Decimal), open_invoice_count.

    `invoices` must include amount_due, rider_id, rider_name, fleet, agency.
    Closed-and-paid invoices (amount_due == 0) still contribute their
    metadata but add zero to the outstanding total.
    """
    if invoices.empty:
        return pd.DataFrame(
            columns=["rider_id", "rider_name", "fleet", "agency",
                     "opening_outstanding", "open_invoice_count"],
        )
    work = invoices.copy()
    work["amount_due"] = work["amount_due"].map(
        lambda v: Decimal(str(v)) if v not in (None, "") else Decimal("0")
    )
    grouped = work.groupby("rider_id", as_index=False).agg(
        rider_name=("rider_name", "first"),
        fleet=("fleet", "first"),
        agency=("agency", "first"),
        opening_outstanding=("amount_due", "sum"),
        open_invoice_count=("amount_due", lambda s: int((s > 0).sum())),
    )
    grouped["opening_outstanding"] = grouped["opening_outstanding"].map(float)
    return grouped.sort_values(
        ["opening_outstanding"], ascending=False
    ).reset_index(drop=True)
