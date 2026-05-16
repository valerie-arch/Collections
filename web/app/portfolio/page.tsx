import { Download } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { api, ReportFleet } from "@/lib/api";

export const dynamic = "force-dynamic";

const FLEETS: ReportFleet[] = ["All", "Wahu", "TSA"];

function fmtGhs0(n: number) {
  return `GHS ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
function fmtPct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

export default async function PortfolioPage({
  searchParams,
}: {
  searchParams?: { months?: string; fleet?: string };
}) {
  const monthsBack = Math.min(60, Math.max(3, Number(searchParams?.months) || 24));
  const fleet: ReportFleet = (FLEETS as readonly string[]).includes(searchParams?.fleet ?? "")
    ? (searchParams!.fleet as ReportFleet)
    : "All";
  const data = await api.portfolioTrends(monthsBack, fleet).catch(() => null);

  if (!data || !data.months?.length) {
    return (
      <div className="px-10 py-12 max-w-7xl">
        <PageHeader title="Portfolio trends" description="" />
        <div className="surface p-8 text-center text-sm text-ink-fade">
          No trend data yet. Sync invoice CSVs from the Reports page first.
        </div>
      </div>
    );
  }

  const maxInvoiced = Math.max(...data.months.map((m) => m.invoiced_ghs));
  const latest = data.months[data.months.length - 1];

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Trends"
        title={`Portfolio trends — ${fleet}`}
        description={`${monthsBack}-month rolling view of MRR, collections, active book, and rider rankings. Built from the deduped invoice corpus.`}
        actions={
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
                Fleet
              </span>
              <div className="flex gap-0.5 bg-canvas-sunken p-0.5 rounded-md">
                {FLEETS.map((f) => {
                  const params = new URLSearchParams();
                  if (monthsBack !== 24) params.set("months", String(monthsBack));
                  if (f !== "All") params.set("fleet", f);
                  const href = params.toString() ? `?${params.toString()}` : "?";
                  return (
                    <a
                      key={f}
                      href={href}
                      className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                        fleet === f
                          ? "bg-canvas-raised text-ink shadow-card"
                          : "text-ink-muted hover:text-ink"
                      }`}
                    >
                      {f}
                    </a>
                  );
                })}
              </div>
            </div>
            <a
              href={api.portfolioDownloadUrl(monthsBack, fleet)}
              className="btn-primary"
            >
              <Download className="w-3.5 h-3.5" />
              Download xlsx
            </a>
          </div>
        }
      />

      <div className="grid gap-4 md:grid-cols-4 mb-8">
        <Stat label="Active subscriptions" value={data.cumulative.active.toLocaleString()} />
        <Stat label="In recovery" value={data.cumulative.recovery.toLocaleString()} tone="warning" />
        <Stat label="Completed" value={data.cumulative.completed.toLocaleString()} tone="moss" />
        <Stat
          label="This month MRR"
          value={fmtGhs0(latest.mrr_ghs)}
          hint={`${latest.active_riders} active, ${latest.new_riders} new`}
        />
      </div>

      <section className="surface p-6 mb-8">
        <h2 className="text-lg font-display tracking-tightest mb-4">
          Month-over-month — invoiced (bar) vs collected (overlay)
        </h2>
        <div className="space-y-2">
          {data.months.map((m) => {
            const invoicedPct = maxInvoiced > 0 ? m.invoiced_ghs / maxInvoiced : 0;
            const collectedPct = m.invoiced_ghs > 0 ? m.collected_ghs / m.invoiced_ghs : 0;
            return (
              <div key={m.label} className="grid grid-cols-[8rem_1fr_auto] items-center gap-3 text-xs">
                <div className="font-mono text-ink-muted">{m.label}</div>
                <div className="relative h-5 bg-canvas-sunken rounded">
                  <div
                    className="absolute inset-y-0 left-0 bg-accent-500/60 rounded"
                    style={{ width: `${invoicedPct * 100}%` }}
                  />
                  <div
                    className="absolute inset-y-0 left-0 bg-moss-500 rounded"
                    style={{ width: `${invoicedPct * collectedPct * 100}%` }}
                  />
                </div>
                <div className="flex gap-3 text-[11px] font-mono whitespace-nowrap">
                  <span className="text-accent-700">{fmtGhs0(m.invoiced_ghs)}</span>
                  <span className="text-moss-600">
                    {fmtPct(collectedPct)} collected
                  </span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 text-[11px] text-ink-fade flex items-center gap-4">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm bg-accent-500/60" /> Invoiced
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm bg-moss-500" /> Collected
          </span>
        </div>
      </section>

      <div className="grid gap-6 md:grid-cols-2 mb-8">
        <section className="surface p-6">
          <h2 className="text-lg font-display tracking-tightest mb-4">
            Active riders by month
          </h2>
          <Sparkline values={data.months.map((m) => m.active_riders)} labels={data.months.map((m) => m.label)} />
        </section>
        <section className="surface p-6">
          <h2 className="text-lg font-display tracking-tightest mb-4">
            Outstanding at month-end
          </h2>
          <Sparkline values={data.months.map((m) => m.outstanding_ghs)} labels={data.months.map((m) => m.label)} formatter={fmtGhs0} />
        </section>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <RiderRankingTable
          title="Top 10 — outstanding balance"
          riders={data.top_10_outstanding}
          metric="outstanding"
        />
        <RiderRankingTable
          title="Top 10 — lifetime collected"
          riders={data.top_10_collected_lifetime}
          metric="collected"
        />
        <RiderRankingTable
          title="Bottom 10 — collection ratio"
          riders={data.bottom_10_ratio}
          metric="ratio"
        />
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "warning" | "moss";
}) {
  const color =
    tone === "warning" ? "text-accent-700" : tone === "moss" ? "text-moss-600" : "text-ink";
  return (
    <div className="surface p-5">
      <div className="text-[11px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </div>
      <div className={`mt-1.5 text-2xl font-display tracking-tightest ${color}`}>{value}</div>
      {hint && <div className="text-xs text-ink-fade mt-1">{hint}</div>}
    </div>
  );
}

function Sparkline({
  values,
  labels,
  formatter,
}: {
  values: number[];
  labels: string[];
  formatter?: (n: number) => string;
}) {
  const max = Math.max(...values, 1);
  return (
    <div className="space-y-1">
      {values.map((v, i) => (
        <div key={labels[i]} className="grid grid-cols-[6rem_1fr_auto] items-center gap-3 text-xs">
          <div className="font-mono text-ink-fade text-[10px]">{labels[i]}</div>
          <div className="h-3 bg-canvas-sunken rounded">
            <div
              className="h-full bg-accent-500 rounded"
              style={{ width: `${(v / max) * 100}%` }}
            />
          </div>
          <div className="font-mono text-ink text-[11px] whitespace-nowrap">
            {formatter ? formatter(v) : v.toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}

function RiderRankingTable({
  title,
  riders,
  metric,
}: {
  title: string;
  riders: { customer_id: string; customer_name: string; lifetime_invoiced_ghs: number; lifetime_collected_ghs: number; lifetime_outstanding_ghs: number; collection_ratio: number }[];
  metric: "outstanding" | "collected" | "ratio";
}) {
  return (
    <section className="surface overflow-hidden">
      <div className="px-5 py-3 border-b border-canvas-line">
        <h3 className="text-base font-display tracking-tightest">{title}</h3>
      </div>
      <table className="data-grid">
        <thead>
          <tr>
            <th>Rider</th>
            <th>Invoiced</th>
            <th>{metric === "ratio" ? "Ratio" : metric === "outstanding" ? "Outstanding" : "Collected"}</th>
          </tr>
        </thead>
        <tbody>
          {riders.length === 0 && (
            <tr>
              <td colSpan={3} className="text-center text-ink-fade py-6">
                Not enough data.
              </td>
            </tr>
          )}
          {riders.map((r) => (
            <tr key={r.customer_id}>
              <td>
                <div className="font-medium text-ink text-sm">{r.customer_name}</div>
                <div className="text-xs text-ink-fade font-mono">{r.customer_id}</div>
              </td>
              <td className="font-mono text-sm">{fmtGhs0(r.lifetime_invoiced_ghs)}</td>
              <td className="font-mono text-sm">
                {metric === "ratio"
                  ? fmtPct(r.collection_ratio)
                  : metric === "outstanding"
                  ? fmtGhs0(r.lifetime_outstanding_ghs)
                  : fmtGhs0(r.lifetime_collected_ghs)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
