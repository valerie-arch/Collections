"""Pipeline-wide constants. Prompt 12 splits some of these out into a
governance.yaml so commission/scoring rules can be tweaked without code
changes; for now everything lives here.
"""

from __future__ import annotations

from api.config import settings


# -- Money / payout --------------------------------------------------------

CURRENCY: str = "GHS"
# Cap on the Bolt weekly deduction per rider (Step 5).
MAX_WEEKLY_DEDUCTION_GHS: int = 420

# -- Matching --------------------------------------------------------------

# rapidfuzz token_sort_ratio threshold for Tier 2 (name match).
NAME_MATCH_THRESHOLD: int = 85
# Keep the last N digits of a phone number for the canonical form.
PHONE_KEEP_LAST: int = 9
# Payment application strategy when one receipt covers multiple invoices.
FIFO: str = "oldest_open_invoice_first"

# -- Invoicing -------------------------------------------------------------

# Spec literal: {Sent, Overdue, Partially Paid, Paid}. Real Zoho exports use
# {Open, Overdue, Closed, Void, Draft}, so we exclude-by-status (next line)
# rather than allow-list. Kept here so other systems with Stripe-style status
# values can be supported by flipping the filter direction later.
BILLED_STATUSES: frozenset[str] = frozenset({"Sent", "Overdue", "Partially Paid", "Paid"})
EXCLUDED_STATUSES: frozenset[str] = frozenset({"void", "voided", "draft"})

# -- Agencies --------------------------------------------------------------

VALID_AGENCIES: frozenset[str] = frozenset({"TSAC", "Hortta", "Unassigned"})
TSA_DEFAULT_AGENCY: str = "TSAC"

# -- Drive folder IDs (mirrored from api/config.py for spec compliance) ----

DRIVE_FOLDER_COLLECTIONS: str = settings.COLLECTIONS_DRIVE_FOLDER_ID
DRIVE_FOLDER_ZOHO: str = settings.ZOHO_INVOICES_DRIVE_FOLDER_ID
