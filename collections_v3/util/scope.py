"""Apply `--fleet` and `--agency` filters to invoices to get `riders_in_scope`.

Receipts (MoMo/Telecel/bank) are deliberately NOT filtered — their fleet
is inherited from the matched rider downstream in Step 2. This module
exposes the scope set so callers can intersect invoices/Bolt earnings
without re-implementing the rule.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from collections_v3.schemas import Agency, Fleet, RunContext


@dataclass
class ScopeResult:
    invoices: pd.DataFrame      # filtered to --fleet / --agency
    riders_in_scope: set[str]   # rider_id values present in the filtered invoices


def _filter_value(filter_val) -> str:
    return filter_val.value if hasattr(filter_val, "value") else str(filter_val)


def apply_scope(invoices: pd.DataFrame, ctx: RunContext) -> ScopeResult:
    """Slice `invoices` to honor ctx.fleet and ctx.agency.

    Both filters AND-compose. `All` means no filter on that dimension.
    Requires that `invoices` already has `fleet` and `agency` columns
    populated (i.e. has been through step0's agency tagger).
    """
    fleet = _filter_value(ctx.fleet)
    agency = _filter_value(ctx.agency)
    filtered = invoices
    if fleet != Fleet.All.value:
        filtered = filtered[filtered["fleet"] == fleet]
    if agency != Agency.All.value:
        filtered = filtered[filtered["agency"] == agency]
    return ScopeResult(
        invoices=filtered.reset_index(drop=True),
        riders_in_scope=set(filtered["rider_id"].astype(str).str.strip()),
    )
