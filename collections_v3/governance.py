"""Governance config loader for the three open commission / scoring
questions (spec Prompt 12).

Reads `governance.yaml` at the repo root; falls back to documented
defaults when a value is missing. `load()` returns the config object plus
a list of Q-identifiers that are still using defaults, so the CLI can
print its startup banner.

Every commission / agency-scoring calculation reads from the returned
GovernanceConfig — no magic constants in the steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_PATH = Path("governance.yaml")


class CommissionConfig(BaseModel):
    midweek_switch_attribution: Literal["week_end", "week_start", "prorated"] = "week_end"
    basis: Literal["momo_bank_only", "total_applied", "momo_bank_plus_promises"] = "total_applied"
    compute_in_pipeline: bool = False
    model_config = ConfigDict(extra="forbid")


class AgencyScoringConfig(BaseModel):
    include_bolt_weekly: bool = True
    model_config = ConfigDict(extra="forbid")


class GovernanceConfig(BaseModel):
    commission: CommissionConfig = Field(default_factory=CommissionConfig)
    agency_scoring: AgencyScoringConfig = Field(default_factory=AgencyScoringConfig)
    model_config = ConfigDict(extra="forbid")


@dataclass
class LoadedGovernance:
    config: GovernanceConfig
    # Q-identifiers that are running on the default (i.e. not explicitly
    # overridden in governance.yaml). Used for the CLI banner.
    defaults_in_effect: list[str]
    source_path: Optional[Path]


# Map each Q-identifier to the (section, key) pair that resolves it.
_Q_KEYS: dict[str, tuple[str, str]] = {
    "Q1": ("commission", "midweek_switch_attribution"),
    "Q2": ("commission", "basis"),
    "Q3": ("agency_scoring", "include_bolt_weekly"),
}


def _defaults_in_effect(raw: dict) -> list[str]:
    """Return the Q-identifiers that the file did NOT explicitly set."""
    out: list[str] = []
    for q, (section, key) in _Q_KEYS.items():
        sec = (raw or {}).get(section)
        if not isinstance(sec, dict) or key not in sec:
            out.append(q)
    return out


def load(path: Optional[Path] = None) -> LoadedGovernance:
    """Read `governance.yaml` (or the supplied path) and return a
    LoadedGovernance with the parsed config + list of Qs running on
    defaults.

    If the file doesn't exist or is empty, all Qs use defaults. Invalid
    YAML or schema violations raise so the operator notices."""
    path = path or DEFAULT_PATH
    raw: dict = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text())
        if isinstance(loaded, dict):
            raw = loaded
    config = GovernanceConfig(**raw)
    return LoadedGovernance(
        config=config,
        defaults_in_effect=_defaults_in_effect(raw),
        source_path=path if path.exists() else None,
    )


def banner_text(loaded: LoadedGovernance) -> Optional[str]:
    """The one-line CLI banner from the spec. Returns None when every
    value is explicitly set."""
    if not loaded.defaults_in_effect:
        return None
    return f"governance: defaults in effect for {loaded.defaults_in_effect}"
