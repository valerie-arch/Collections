import { PageHeader } from "@/components/PageHeader";
import {
  api, DashboardPeriod, DashboardSnapshot, ReportFleet,
} from "@/lib/api";

export const dynamic = "force-dynamic";

const PERIODS: DashboardPeriod[] = ["mtd", "lifetime", "custom"];
const PERIOD_LABEL: Record<DashboardPeriod, string> = {
  mtd: "MTD",
  lifetime: "Lifetime",
  custom: "Custom",
};
const FLEETS: ReportFleet[] = ["All", "Wahu", "TSA"];

function fmtGhs0(n: number) {
  return `GHS ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
function fmtPct(n: number) {
  return `${n.toFixed(1)}%`;
}
function fmtInt(n: number) {
  return n.toLocaleString();
}

export default async function PortfolioDashboardPage({
  searchParams,
}: {
  searchParams?: {
    period?: string;
    start?: string;
    end?: string;
    fleet?: string;
  };
}) {
  const period: DashboardPeriod = (PERIODS as readonly string[]).includes(
    searchParams?.period ?? "",
  )
    ? (searchParams!.period as DashboardPeriod)
    : "mtd";
  const fleet: ReportFleet = (FLEETS as readonly string[]).includes(
    searchParams?.fleet ?? "",
  )
    ? (searchParams!.fleet as ReportFleet)
    : "All";

  const data = await api
    .dashboardSnapshot({
      period,
      fleet,
      start: searchParams?.start,
      end: searchParams?.end,
    })
    .catch(() => null);

  if (!data) {
    return (
      <div className="px-10 py-12 max-w-7xl">
        <PageHeader
          title="Portfolio dashboard"
          description="10-KPI view across Behavioral, Financial, and Portfolio layers."
        />
        <div className="surface p-8 text-center text-sm text-ink-fade">
          No invoice data yet. Sync invoice CSVs from the Reports page first.
        </div>
      </div>
    );
  }

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Portfolio dashboard"
        title={`${data.window.label} — ${fleet}`}
        description="Behavioral (early warning) · Financial (this period) · Portfolio (cumulative health)"
        actions={
          <PeriodFleetSelector
            period={period}
            fleet={fleet}
            start={searchParams?.start}
            end={searchParams?.end}
          />
        }
      />

      {/* BEHAVIORAL LAYER */}
      <LayerHeader title="Behavioral" hint="Early warning — what's about to happen" />
      <div className="grid gap-4 md:grid-cols-3 mb-8">
        <ActivePayerCard data={data.behavioral.active_payer_rate} />
        <OnTimeCard data={data.behavioral.on_time_payment_rate} />
        <BlockedCard
          title="Roll rates"
          subtitle="Bucket migration"
          reason={data.behavioral.roll_rates.reason}
        />
      </div>

      {/* FINANCIAL LAYER */}
      <LayerHeader title="Financial" hint="This period — what just happened" />
      <div className="grid gap-4 md:grid-cols-2 mb-8">
        <CollectionsCard data={data.financial.monthly_collections_rate} />
        <MrrCard data={data.financial.mrr} />
      </div>

      {/* PORTFOLIO LAYER */}
      <LayerHeader title="Portfolio" hint="Cumulative health — what's on the books" />
      <div className="grid gap-4 md:grid-cols-2 mb-4">
        <AgingCard data={data.portfolio.aging} />
        <LifetimeCard data={data.portfolio.lifetime_efficiency} />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <BlockedCard
          title="Cure rate"
          subtitle="31+ DPD → Current"
          reason={data.portfolio.cure_rate.reason}
        />
        <NetChargeOffCard data={data.portfolio.net_charge_off} />
        <RecoveryCard data={data.portfolio.recovery_on_churned} />
      </div>

      <div className="mt-8 text-[11px] text-ink-fade font-mono">
        as_of {data.as_of} · invoices loaded: {data.data_sources.invoices.toLocaleString()}{" "}
        · write-off ledger: {data.data_sources.write_off_ledger_loaded ? "yes" : "no"}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Period / Fleet selector
// ---------------------------------------------------------------------------

function PeriodFleetSelector({
  period, fleet, start, end,
}: {
  period: DashboardPeriod;
  fleet: ReportFleet;
  start?: string;
  end?: string;
}) {
  const hrefFor = (overrides: Partial<{
    period: DashboardPeriod; fleet: ReportFleet; start: string; end: string;
  }>) => {
    const next = { period, fleet, start, end, ...overrides };
    const params = new URLSearchParams();
    if (next.period !== "mtd") params.set("period", next.period);
    if (next.fleet !== "All") params.set("fleet", next.fleet);
    if (next.period === "custom" && next.start) params.set("start", next.start);
    if (next.period === "custom" && next.end) params.set("end", next.end);
    return params.toString() ? `?${params.toString()}` : "?";
  };

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
          Period
        </span>
        <div className="flex gap-0.5 bg-canvas-sunken p-0.5 rounded-md">
          {PERIODS.map((p) => (
            <a
              key={p}
              href={hrefFor({ period: p })}
              className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                period === p
                  ? "bg-canvas-raised text-ink shadow-card"
                  : "text-ink-muted hover:text-ink"
              }`}
            >
              {PERIOD_LABEL[p]}
            </a>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
          Fleet
        </span>
        <div className="flex gap-0.5 bg-canvas-sunken p-0.5 rounded-md">
          {FLEETS.map((f) => (
            <a
              key={f}
              href={hrefFor({ fleet: f })}
              className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                fleet === f
                  ? "bg-canvas-raised text-ink shadow-card"
                  : "text-ink-muted hover:text-ink"
              }`}
            >
              {f}
            </a>
          ))}
        </div>
      </div>
      {period === "custom" && (
        <form className="flex items-center gap-2" method="get">
          <input type="hidden" name="period" value="custom" />
          <input type="hidden" name="fleet" value={fleet} />
          <input
            type="date" name="start" defaultValue={start}
            className="text-xs border border-canvas-line rounded px-2 py-1"
          />
          <span className="text-xs text-ink-fade">→</span>
          <input
            type="date" name="end" defaultValue={end}
            className="text-xs border border-canvas-line rounded px-2 py-1"
          />
          <button type="submit" className="btn-primary !py-1">Apply</button>
        </form>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

function LayerHeader({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="mb-3 mt-2 flex items-baseline gap-3">
      <h2 className="text-base font-display tracking-tightest text-ink">{title}</h2>
      <span className="text-[11px] text-ink-fade">{hint}</span>
    </div>
  );
}

function CardShell({
  title, subtitle, children,
}: {
  title: string; subtitle?: string; children: React.ReactNode;
}) {
  return (
    <section className="surface p-5">
      <div className="mb-3">
        <h3 className="text-sm font-medium text-ink">{title}</h3>
        {subtitle && (
          <p className="text-[11px] text-ink-fade mt-0.5">{subtitle}</p>
        )}
      </div>
      {children}
    </section>
  );
}

function BigNumber({
  value, sublabel, tone = "default",
}: {
  value: string; sublabel?: string;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  const color =
    tone === "good" ? "text-moss-600"
    : tone === "warn" ? "text-accent-700"
    : tone === "bad" ? "text-clay-600"
    : "text-ink";
  return (
    <div>
      <div className={`text-3xl font-display tracking-tightest ${color}`}>{value}</div>
      {sublabel && <div className="text-xs text-ink-fade mt-1">{sublabel}</div>}
    </div>
  );
}

function Bar({ pct, tone = "accent" }: { pct: number; tone?: "accent" | "moss" | "clay" }) {
  const cls =
    tone === "moss" ? "bg-moss-500"
    : tone === "clay" ? "bg-clay-500"
    : "bg-accent-500";
  return (
    <div className="h-1.5 bg-canvas-sunken rounded">
      <div className={`h-full ${cls} rounded`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// KPI cards
// ---------------------------------------------------------------------------

function ActivePayerCard({ data }: { data: DashboardSnapshot["behavioral"]["active_payer_rate"] }) {
  return (
    <CardShell title="Active payer rate" subtitle={`Last ${data.lookback_days} days, by tenure`}>
      <BigNumber
        value={fmtPct(data.overall_rate_pct)}
        sublabel={`${fmtInt(data.overall_paying)} of ${fmtInt(data.overall_active)} active riders paid`}
        tone={data.overall_rate_pct >= 70 ? "good" : data.overall_rate_pct >= 50 ? "warn" : "bad"}
      />
      <div className="mt-4 space-y-2">
        {data.by_tenure.map((s) => (
          <div key={s.tenure} className="grid grid-cols-[3.5rem_1fr_auto] items-center gap-2 text-[11px]">
            <span className="font-mono text-ink-muted">{s.tenure}</span>
            <Bar pct={s.rate_pct} tone={s.rate_pct >= 70 ? "moss" : "accent"} />
            <span className="font-mono text-ink whitespace-nowrap">
              {fmtPct(s.rate_pct)} <span className="text-ink-fade">({s.paying_riders}/{s.active_riders})</span>
            </span>
          </div>
        ))}
      </div>
    </CardShell>
  );
}

function OnTimeCard({ data }: { data: DashboardSnapshot["behavioral"]["on_time_payment_rate"] }) {
  return (
    <CardShell title="On-time payment rate" subtitle="Paid on or before invoice due date">
      <BigNumber
        value={fmtPct(data.on_time_pct)}
        sublabel={`${fmtInt(data.on_time_count)} of ${fmtInt(data.total_paid_count)} payments`}
        tone={data.on_time_pct >= 80 ? "good" : data.on_time_pct >= 60 ? "warn" : "bad"}
      />
      <p className="text-[11px] text-ink-fade mt-4 leading-relaxed">{data.note}</p>
    </CardShell>
  );
}

function BlockedCard({ title, subtitle, reason }: { title: string; subtitle: string; reason: string }) {
  return (
    <CardShell title={title} subtitle={subtitle}>
      <div className="border border-dashed border-canvas-line rounded p-3 text-[11px] text-ink-fade leading-relaxed">
        <span className="font-medium text-ink-muted">Data warming up.</span>{" "}
        {reason}
      </div>
    </CardShell>
  );
}

function CollectionsCard({ data }: { data: DashboardSnapshot["financial"]["monthly_collections_rate"] }) {
  const { gross_rate_pct: gross, net_rate_pct: net } = data;
  return (
    <CardShell title="Collections rate" subtitle="Period invoiced vs collected">
      <div className="flex items-end gap-6">
        <BigNumber
          value={fmtPct(gross)}
          sublabel="gross"
          tone={gross >= 85 ? "good" : gross >= 70 ? "warn" : "bad"}
        />
        <div className="text-xs">
          <div className="text-ink-fade">net of write-offs</div>
          <div className="font-mono text-ink text-base">{fmtPct(net)}</div>
        </div>
      </div>
      <div className="mt-4 text-[11px] grid grid-cols-2 gap-x-4 gap-y-1.5">
        <div className="text-ink-fade">Invoiced</div>
        <div className="font-mono text-ink text-right">{fmtGhs0(data.invoiced_ghs)}</div>
        <div className="text-ink-fade">Collected</div>
        <div className="font-mono text-moss-600 text-right">{fmtGhs0(data.collected_ghs)}</div>
        <div className="text-ink-fade">Write-offs</div>
        <div className="font-mono text-clay-600 text-right">{fmtGhs0(data.write_offs_ghs)}</div>
      </div>
      <div className="mt-3 pt-3 border-t border-canvas-line grid grid-cols-3 text-[11px]">
        <div>
          <div className="text-ink-fade">Fully paid</div>
          <div className="font-mono text-moss-600">{fmtInt(data.splits.fully_paid_riders)}</div>
        </div>
        <div>
          <div className="text-ink-fade">Partial</div>
          <div className="font-mono text-accent-700">{fmtInt(data.splits.partial_riders)}</div>
        </div>
        <div>
          <div className="text-ink-fade">No pay</div>
          <div className="font-mono text-clay-600">{fmtInt(data.splits.no_pay_riders)}</div>
        </div>
      </div>
    </CardShell>
  );
}

function MrrCard({ data }: { data: DashboardSnapshot["financial"]["mrr"] }) {
  return (
    <CardShell title="MRR & movement" subtitle="Recurring revenue in window">
      <BigNumber
        value={fmtGhs0(data.current_ghs)}
        sublabel={`${fmtInt(data.active_riders)} active riders this window`}
      />
      <div className="mt-4 grid grid-cols-4 gap-3 text-[11px]">
        <div>
          <div className="text-ink-fade">New</div>
          <div className="font-mono text-moss-600 text-sm">+{fmtGhs0(data.new_ghs)}</div>
          <div className="text-ink-fade font-mono">{fmtInt(data.new_riders)} riders</div>
        </div>
        <div>
          <div className="text-ink-fade">Reactivated</div>
          <div className="font-mono text-moss-600 text-sm">+{fmtGhs0(data.reactivated_ghs)}</div>
        </div>
        <div>
          <div className="text-ink-fade">Churned</div>
          <div className="font-mono text-clay-600 text-sm">-{fmtGhs0(data.churned_ghs)}</div>
          <div className="text-ink-fade font-mono">{fmtInt(data.churned_riders)} riders</div>
        </div>
        <div>
          <div className="text-ink-fade">Net new</div>
          <div className={`font-mono text-sm ${data.net_new_ghs >= 0 ? "text-moss-600" : "text-clay-600"}`}>
            {data.net_new_ghs >= 0 ? "+" : ""}{fmtGhs0(data.net_new_ghs)}
          </div>
        </div>
      </div>
    </CardShell>
  );
}

function AgingCard({ data }: { data: DashboardSnapshot["portfolio"]["aging"] }) {
  return (
    <CardShell
      title="Aging distribution"
      subtitle={`${fmtInt(data.total_riders_with_balance)} riders · ${fmtGhs0(data.total_outstanding_ghs)} outstanding`}
    >
      <div className="space-y-2">
        {data.buckets.map((b) => (
          <div key={b.label} className="grid grid-cols-[6.5rem_1fr_auto] items-center gap-2 text-[11px]">
            <span className="font-mono text-ink-muted">{b.label}</span>
            <Bar
              pct={b.pct_of_ghs}
              tone={b.label.startsWith("Current") ? "moss" : b.label.includes("365d") ? "clay" : "accent"}
            />
            <span className="font-mono text-ink whitespace-nowrap">
              {fmtGhs0(b.ghs)} <span className="text-ink-fade">{fmtPct(b.pct_of_ghs)}</span>
            </span>
          </div>
        ))}
        {data.buckets.length === 0 && (
          <div className="text-[11px] text-ink-fade text-center py-4">No open balances.</div>
        )}
      </div>
    </CardShell>
  );
}

function LifetimeCard({ data }: { data: DashboardSnapshot["portfolio"]["lifetime_efficiency"] }) {
  return (
    <CardShell title="Lifetime efficiency" subtitle="Cumulative collected ÷ invoiced (always lifetime)">
      <BigNumber
        value={fmtPct(data.efficiency_pct)}
        tone={data.efficiency_pct >= 90 ? "good" : data.efficiency_pct >= 75 ? "warn" : "bad"}
      />
      <div className="mt-4 grid grid-cols-3 gap-3 text-[11px]">
        <div>
          <div className="text-ink-fade">Invoiced</div>
          <div className="font-mono text-ink">{fmtGhs0(data.invoiced_ghs)}</div>
        </div>
        <div>
          <div className="text-ink-fade">Collected</div>
          <div className="font-mono text-moss-600">{fmtGhs0(data.collected_ghs)}</div>
        </div>
        <div>
          <div className="text-ink-fade">Outstanding</div>
          <div className="font-mono text-clay-600">{fmtGhs0(data.outstanding_ghs)}</div>
        </div>
      </div>
    </CardShell>
  );
}

function NetChargeOffCard({ data }: { data: DashboardSnapshot["portfolio"]["net_charge_off"] }) {
  if (!data.available) {
    return <BlockedCard title="Net charge-off" subtitle="Annualized" reason={data.reason} />;
  }
  return (
    <CardShell title="Net charge-off" subtitle={`Annualized · window ${data.window_days}d`}>
      <BigNumber
        value={fmtPct(data.annualized_pct)}
        sublabel={`${fmtGhs0(data.net_ghs)} net (${fmtGhs0(data.charge_offs_ghs)} written off, ${fmtGhs0(data.recoveries_ghs)} recovered)`}
        tone={data.annualized_pct <= 2 ? "good" : data.annualized_pct <= 5 ? "warn" : "bad"}
      />
    </CardShell>
  );
}

function RecoveryCard({ data }: { data: DashboardSnapshot["portfolio"]["recovery_on_churned"] }) {
  return (
    <CardShell title="Recovery on churn" subtitle={`${fmtInt(data.cohort_size)} riders churned in window`}>
      {data.cohort_size === 0 ? (
        <div className="text-[11px] text-ink-fade">{data.note}</div>
      ) : (
        <>
          <BigNumber
            value={fmtPct(data.recovery_rate_pct)}
            sublabel={`${fmtGhs0(data.recovered_ghs)} of ${fmtGhs0(data.cohort_outstanding_at_churn_ghs + data.recovered_ghs)} ever recovered`}
            tone={data.recovery_rate_pct >= 30 ? "good" : data.recovery_rate_pct >= 15 ? "warn" : "bad"}
          />
          <div className="mt-3 space-y-1">
            {data.by_days_post_churn.filter((b) => b.ghs > 0).map((b) => (
              <div key={b.bucket} className="grid grid-cols-[4rem_1fr_auto] items-center gap-2 text-[11px]">
                <span className="font-mono text-ink-muted">{b.bucket}</span>
                <Bar pct={(b.ghs / Math.max(...data.by_days_post_churn.map((x) => x.ghs), 1)) * 100} />
                <span className="font-mono text-ink whitespace-nowrap">{fmtGhs0(b.ghs)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </CardShell>
  );
}
