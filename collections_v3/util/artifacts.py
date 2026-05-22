"""Registry of every pipeline artifact.

Locked filename pattern (per spec): {artifact}_{fleet}_{agency}_{period}.{ext}
Per-artifact metadata here pins the subfolder under the Collections Data
Drive root, the legal extensions, and whether the artifact bypasses
versioning (singletons append to a shared file instead).

Two artifacts (qb_invoices, qb_payments) live under a week-partitioned
subfolder like `/QuickBooks Exports/2026-W21/`. Anything else writes
directly to its named subfolder.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    extensions: tuple[str, ...]
    subfolder: str                 # path under COLLECTIONS root, no leading slash
    singleton: bool = False         # singletons append rows; never versioned
    week_partition: bool = False    # subfolder gets a trailing /{ISO-week}


REGISTRY: dict[str, ArtifactSpec] = {
    "billed_invoices_by_fleet_agency": ArtifactSpec(
        name="billed_invoices_by_fleet_agency",
        extensions=("xlsx",),
        subfolder="Invoice Snapshots",
    ),
    "matched_payments": ArtifactSpec(
        name="matched_payments",
        extensions=("xlsx",),
        subfolder="Monthly Matched Payments",
    ),
    "suspense": ArtifactSpec(
        name="suspense",
        extensions=("xlsx",),
        subfolder="Monthly Matched Payments",
    ),
    "rider_outstanding": ArtifactSpec(
        name="rider_outstanding",
        extensions=("xlsx",),
        subfolder="Monthly Matched Payments",
    ),
    "rider_payout_Wahu": ArtifactSpec(
        name="rider_payout_Wahu",
        extensions=("xlsx",),
        subfolder="Weekly Rider Payouts/Wahu",
    ),
    "rider_payout_TSA": ArtifactSpec(
        name="rider_payout_TSA",
        extensions=("xlsx",),
        subfolder="Weekly Rider Payouts/TSA",
    ),
    "agency_performance": ArtifactSpec(
        name="agency_performance",
        extensions=("xlsx",),
        subfolder="Agency Performance",
    ),
    "run_summary": ArtifactSpec(
        name="run_summary",
        extensions=("md", "pdf"),
        subfolder="Weekly Rider Payouts",
    ),
    "rider_agency_history": ArtifactSpec(
        name="rider_agency_history",
        extensions=("xlsx",),
        subfolder="Monthly Matched Payments",
        singleton=True,
    ),
    "data_quality": ArtifactSpec(
        name="data_quality",
        extensions=("xlsx",),
        subfolder="Weekly Rider Payouts",
    ),
    "qb_invoices": ArtifactSpec(
        name="qb_invoices",
        extensions=("iif", "csv"),
        subfolder="QuickBooks Exports",
        week_partition=True,
    ),
    "qb_payments": ArtifactSpec(
        name="qb_payments",
        extensions=("iif", "csv"),
        subfolder="QuickBooks Exports",
        week_partition=True,
    ),
    "qb_upload_log": ArtifactSpec(
        name="qb_upload_log",
        extensions=("xlsx",),
        subfolder="QuickBooks Exports",
        singleton=True,
    ),
}

# The spec lists 13 artifacts; assert here so accidental edits fail loudly.
assert len(REGISTRY) == 13, f"REGISTRY drifted from spec — expected 13, found {len(REGISTRY)}"


def get(artifact: str) -> ArtifactSpec:
    try:
        return REGISTRY[artifact]
    except KeyError:
        raise KeyError(
            f"Unknown artifact {artifact!r}. Known: {sorted(REGISTRY)}"
        ) from None
