"""collections_v3 — rider payment reconciliation and weekly Bolt payout pipeline.

CLI-first pipeline that pulls source data from Google Drive, runs a 6-step
reconciliation, and writes versioned XLSX artifacts back to Drive. The shell
that consumes these artifacts is the existing Next.js dashboard in `web/`.
"""
