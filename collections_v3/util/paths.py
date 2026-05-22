"""Universal filename + Drive-path builder for pipeline artifacts.

Locked pattern: {artifact}_{fleet}_{agency}_{period}.{ext}

Period encoding:
    Week     -> wk{ISOweek}             e.g. wk21
    MTD      -> mtd{YYYYMM}             e.g. mtd202605
    Lifetime -> lifetime
    Custom   -> {YYYYMMDD}-{YYYYMMDD}   e.g. 20260501-20260520

Drive target subfolder comes from the artifact registry; QuickBooks
artifacts add a per-week partition (e.g. `QuickBooks Exports/2026-W21`).
"""

from __future__ import annotations

from typing import Optional

from collections_v3.schemas import Period, RunContext
from collections_v3.util import artifacts as artifact_registry


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

def _period_value(ctx: RunContext) -> str:
    p = ctx.period
    return p.value if hasattr(p, "value") else str(p)


def _period_token(ctx: RunContext) -> str:
    p = _period_value(ctx)
    if p == Period.Lifetime.value:
        return "lifetime"
    if p == Period.Week.value:
        if not ctx.end:
            raise ValueError("Week period needs a resolved end date in ctx")
        return f"wk{ctx.end.isocalendar().week:02d}"
    if p == Period.MTD.value:
        if not ctx.end:
            raise ValueError("MTD period needs a resolved end date in ctx")
        return f"mtd{ctx.end.strftime('%Y%m')}"
    if p == Period.Custom.value:
        if not (ctx.start and ctx.end):
            raise ValueError("Custom period needs both start and end in ctx")
        return f"{ctx.start.strftime('%Y%m%d')}-{ctx.end.strftime('%Y%m%d')}"
    raise ValueError(f"Unknown period {p!r}")


def iso_week_token(ctx: RunContext) -> str:
    """`YYYY-Www` for the ctx's end date — used to partition QB exports."""
    if not ctx.end:
        raise ValueError("ISO week token needs a resolved end date in ctx")
    y, w, _ = ctx.end.isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------------------
# Filename + Drive-target builders
# ---------------------------------------------------------------------------

def build_filename(artifact: str, ctx: RunContext, *, ext: Optional[str] = None) -> str:
    """Return `{artifact}_{fleet}_{agency}_{period}.{ext}`.

    `ext` is optional when the artifact's spec has a single legal extension
    (we use that one). When the artifact supports multiple extensions
    (`run_summary` -> md/pdf, `qb_invoices` -> iif/csv) the caller MUST
    pass `ext`. Passing an unknown ext raises.
    """
    spec = artifact_registry.get(artifact)
    if ext is None:
        if len(spec.extensions) != 1:
            raise ValueError(
                f"{artifact!r} supports multiple extensions {spec.extensions}; "
                "pass ext=... explicitly."
            )
        ext = spec.extensions[0]
    elif ext not in spec.extensions:
        raise ValueError(
            f"{artifact!r} does not support ext={ext!r}; legal: {spec.extensions}"
        )

    fleet = ctx.fleet.value if hasattr(ctx.fleet, "value") else ctx.fleet
    agency = ctx.agency.value if hasattr(ctx.agency, "value") else ctx.agency
    return f"{artifact}_{fleet}_{agency}_{_period_token(ctx)}.{ext}"


def drive_target(artifact: str, ctx: RunContext) -> str:
    """Return the subfolder path (under the Collections root) for `artifact`.

    No leading slash. Week-partitioned artifacts get a trailing
    `/YYYY-Www` segment derived from ctx.end.
    """
    spec = artifact_registry.get(artifact)
    if spec.week_partition:
        return f"{spec.subfolder}/{iso_week_token(ctx)}"
    return spec.subfolder
