import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { SyncDriveButton } from "@/components/SyncDriveButton";
import { Tooltip } from "@/components/Tooltip";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

async function safe<T>(p: Promise<T>, fallback: T): Promise<T> {
  try {
    return await p;
  } catch {
    return fallback;
  }
}

export default async function Overview() {
  const [trends, outliers, mtd] = await Promise.all([
    safe(api.portfolioTrends(3), null),
    safe(api.listOutliers({ severity: "error", limit: 5 }), null),
    safe(api.reportCollections({ view: "mtd", status: "active" }), null),
  ]);

  const latestMonth = trends?.months?.[trends.months.length - 1];

  return (
    <div className="px-10 py-12 max-w-6xl">
      <PageHeader
        eyebrow="Wahu · Collections"
        title="Portfolio overview"
        description="Snapshot of the active book this month, the recovery list, and outliers that need attention. Sync Drive pulls only what changed since the last sync."
        actions={<SyncDriveButton />}
      />

      <div className="grid gap-4 md:grid-cols-4 mb-10">
        <Stat
          label="Active riders (this month)"
          value={mtd?.active_riders.toLocaleString() ?? "—"}
          hint={
            mtd?.total_rider_population
              ? `${((mtd.active_riders / mtd.total_rider_population) * 100).toFixed(1)}% of ${mtd.total_rider_population} total`
              : undefined
          }
          tip={
            <>
              <strong>Riders with an &quot;active&quot; subscription
              status this month.</strong>{" "}
              Excludes Recovery (churned with debt) and Completed
              (fully paid out). Matches the Active filter on Reports.
            </>
          }
        />
        <Stat
          label="MRR (this month)"
          value={latestMonth ? `GHS ${latestMonth.mrr_ghs.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}
          hint={latestMonth ? `${latestMonth.invoices_issued} invoices issued` : undefined}
          tip={
            <>
              <strong>Monthly Recurring Revenue.</strong>{" "}
              Sum of invoiced amounts in the latest billing month for
              riders currently being billed. Doesn&apos;t count
              one-off charges or B2B invoices.
            </>
          }
        />
        <Stat
          label="Outstanding (active)"
          value={
            mtd?.headlines.lifetime_outstanding_ghs != null
              ? `GHS ${mtd.headlines.lifetime_outstanding_ghs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
              : "—"
          }
          tone="warning"
          tip={
            <>
              <strong>Open balance across all invoices for active
              riders.</strong>{" "}
              The Portfolio dashboard&apos;s Aging card breaks this by
              DPD bucket. Does not include Recovery / Completed riders.
            </>
          }
        />
        <Stat
          label="Critical outliers"
          value={outliers?.counts?._critical?.toLocaleString() ?? outliers?.total?.toString() ?? "—"}
          hint="See Exceptions for details"
          tone="warning"
          tip={
            <>
              <strong>Riders flagged by the auto-detector as needing
              urgent attention.</strong>{" "}
              Mix of large unmatched payments, very old open invoices,
              suspected duplicate riders, and other data-quality
              signals. Full list on the Exceptions page.
            </>
          }
        />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <section className="surface p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-display tracking-tightest">Latest 3 months</h2>
            <Link
              href="/portfolio"
              className="text-sm text-accent-600 hover:text-accent-700 inline-flex items-center gap-1 font-medium"
            >
              Full trends <ArrowUpRight className="w-3.5 h-3.5" />
            </Link>
          </div>
          {trends?.months?.length ? (
            <ul className="divide-y divide-canvas-line/60">
              {trends.months.map((m) => (
                <li key={m.label} className="py-3 flex items-center justify-between gap-4">
                  <div>
                    <div className="text-sm font-medium text-ink">{m.label}</div>
                    <div className="text-xs text-ink-fade mt-0.5">
                      {m.active_riders} active · {m.new_riders} new
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-mono text-ink">
                      GHS {m.invoiced_ghs.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </div>
                    <div className="text-xs text-moss-600">
                      collected {((m.collected_ghs / Math.max(m.invoiced_ghs, 1)) * 100).toFixed(0)}%
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-sm text-ink-fade text-center py-6">No trend data yet.</div>
          )}
        </section>

        <section className="surface p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-display tracking-tightest">Top outliers</h2>
            <Link
              href="/exceptions"
              className="text-sm text-accent-600 hover:text-accent-700 inline-flex items-center gap-1 font-medium"
            >
              View all <ArrowUpRight className="w-3.5 h-3.5" />
            </Link>
          </div>
          {outliers?.items?.length ? (
            <ul className="divide-y divide-canvas-line/60">
              {outliers.items.map((o) => (
                <li key={`${o.category}-${o.invoice_id}-${o.customer_id}`} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm text-ink">{o.title}</div>
                      <div className="text-xs text-ink-fade mt-0.5">
                        {o.customer_name} · {o.category}
                      </div>
                    </div>
                    <span className="text-xs font-mono text-clay-600 shrink-0">
                      GHS {o.amount_ghs.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-sm text-ink-fade text-center py-6">All clear.</div>
          )}
        </section>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  tone = "default",
  tip,
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "warning";
  tip?: React.ReactNode;
}) {
  return (
    <div className="surface p-6">
      <div className="flex items-center gap-1.5">
        <div className="text-xs uppercase tracking-wider text-ink-fade font-medium">
          {label}
        </div>
        {tip && <Tooltip content={tip} side="bottom" align="start" />}
      </div>
      <div
        className={`mt-2 text-2xl font-display tracking-tightest ${
          tone === "warning" ? "text-accent-700" : "text-ink"
        }`}
      >
        {value}
      </div>
      {hint && <div className="text-xs text-ink-fade mt-1">{hint}</div>}
    </div>
  );
}
