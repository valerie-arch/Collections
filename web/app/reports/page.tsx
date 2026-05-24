import { PageHeader } from "@/components/PageHeader";
import { api, ReportFleet, ReportStatus, ReportView } from "@/lib/api";
import { ReportControls } from "./controls";
import { RidersTable } from "./riders-table";
import { BandFilterLink } from "./band-filter-link";
import { Tooltip } from "@/components/Tooltip";

export const dynamic = "force-dynamic";

const VIEWS: ReportView[] = ["mtd", "lifetime", "custom"];
const STATUSES: ReportStatus[] = ["active", "recovery", "completed", "all"];
const FLEETS: ReportFleet[] = ["All", "Wahu", "TSA"];
const MONTH_NAMES = [
  "", "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function fmtGhs(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return `GHS ${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
function fmtPct(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}
function monthStartIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function buildTitle(view: ReportView, status: ReportStatus, windowLabel?: string) {
  const statusName: Record<ReportStatus, string> = {
    active: "Active riders",
    recovery: "Recovery (churned)",
    completed: "Completed riders",
    all: "All riders",
  };
  if (view === "mtd") {
    const now = new Date();
    return `Collections — ${MONTH_NAMES[now.getMonth() + 1]} ${now.getFullYear()} MTD · ${statusName[status]}`;
  }
  if (view === "custom") {
    return `Collections — Custom window · ${statusName[status]}`;
  }
  return `Collections — Lifetime · ${statusName[status]}`;
}

export default async function ReportsPage({
  searchParams,
}: {
  searchParams?: {
    view?: string;
    status?: string;
    fleet?: string;
    agency?: string;
    window_start?: string;
    window_end?: string;
  };
}) {
  const view: ReportView = (VIEWS as readonly string[]).includes(searchParams?.view ?? "")
    ? (searchParams!.view as ReportView)
    : "mtd";
  const status: ReportStatus = (STATUSES as readonly string[]).includes(searchParams?.status ?? "")
    ? (searchParams!.status as ReportStatus)
    : "active";
  const fleet: ReportFleet = (FLEETS as readonly string[]).includes(searchParams?.fleet ?? "")
    ? (searchParams!.fleet as ReportFleet)
    : "All";
  const agency = searchParams?.agency ?? "All";
  const windowStart = searchParams?.window_start ?? monthStartIso();
  const windowEnd = searchParams?.window_end ?? todayIso();

  const [data, agencyData] = await Promise.all([
    api
      .reportCollections({
        view,
        status,
        fleet,
        ...(agency && agency !== "All" ? { agency } : {}),
        ...(view === "custom"
          ? { window_start: windowStart, window_end: windowEnd }
          : {}),
      })
      .catch(() => null),
    api.listAgencies().catch(() => ({ agencies: [] as string[], assignments: {}, count: 0 })),
  ]);

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Report A · Collections"
        title={buildTitle(view, status, data?.window?.label)}
        description={
          data?.window?.label
            ? `${data.window.label}. Toggle status to switch between active, recovery (churned with outstanding), completed, or all riders. Use Custom to pick a date range. Download as Excel anytime.`
            : "Active billing snapshot built from Zoho invoice CSVs."
        }
        actions={
          <ReportControls
            view={view}
            status={status}
            fleet={fleet}
            agency={agency}
            windowStart={windowStart}
            windowEnd={windowEnd}
          />
        }
      />

      {!data || data._note ? (
        <div className="surface p-8 text-center">
          <div className="text-sm font-medium text-ink mb-2">
            {data?._note ?? "Failed to load report"}
          </div>
          <div className="text-xs text-ink-fade">
            Click <span className="font-medium">Sync Drive</span> on the{" "}
            <a href="/" className="underline">Overview</a> page to pull invoice CSVs
            from Google Drive, or drop them into{" "}
            <code className="font-mono text-xs">sample_inputs/zoho/invoices/</code>.
          </div>
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-4 mb-3">
            <Stat
              label={
                status === "recovery"
                  ? "Churned riders w/ debt"
                  : status === "completed"
                  ? "Completed riders"
                  : status === "all"
                  ? "Total riders"
                  : view === "mtd"
                  ? "Active riders (this month)"
                  : "Active riders"
              }
              value={data.active_riders.toLocaleString()}
              hint={
                data.total_rider_population
                  ? `${((data.active_riders / data.total_rider_population) * 100).toFixed(1)}% of ${data.total_rider_population} total`
                  : undefined
              }
            />
            <Stat label="Invoiced (in scope)" value={fmtGhs(data.headlines.lifetime_invoiced_ghs)} />
            <Stat
              label={view === "mtd" || view === "custom" ? "Collected (in scope)" : "Collected"}
              value={fmtGhs(data.headlines.lifetime_collected_ghs)}
              hint={
                view !== "lifetime" && data.headlines.cash_in_window_ghs != null
                  ? `Cash in window: ${fmtGhs(data.headlines.cash_in_window_ghs)}`
                  : undefined
              }
            />
            <Stat
              label="Outstanding"
              value={fmtGhs(data.headlines.lifetime_outstanding_ghs)}
              hint={`Collection ratio ${fmtPct(data.headlines.collection_ratio)}`}
              tone="warning"
            />
          </div>

          {view !== "lifetime" &&
            data.headlines.cash_in_window_ghs != null && (
              <section className="surface p-5 mb-8">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-display tracking-tightest text-ink">
                    Cash flow this period
                  </h3>
                  <span className="text-[11px] text-ink-fade">
                    All payments dated in {data.window?.label}
                  </span>
                </div>
                <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
                  <CashTile
                    label="Cash received"
                    value={data.headlines.cash_in_window_ghs}
                    subtitle="all payments this period (any invoice age)"
                    tone="moss"
                  />
                  <CashTile
                    label="Applied to this period's invoices"
                    value={data.headlines.cash_applied_to_period_ghs ?? 0}
                    subtitle="paid against invoices issued in window"
                  />
                  <CashTile
                    label="Applied to prior invoices"
                    value={data.headlines.cash_applied_to_prior_ghs ?? 0}
                    subtitle="paying down older debt"
                    tone="accent"
                  />
                  <PaymentActivityTile
                    rate={data.headlines.payment_activity_rate ?? 0}
                    paid={data.headlines.riders_paid_in_window ?? 0}
                    total={data.active_riders}
                  />
                </div>
                <p className="text-[11px] text-ink-fade mt-3 leading-relaxed">
                  <span className="font-medium text-ink-muted">Reading this:</span>{" "}
                  the collection ratio above only counts cash applied to this
                  period&apos;s invoices. Cash that paid down older invoices shows
                  here as &quot;Applied to prior&quot; — important for cash forecasting
                  but doesn&apos;t move the current period&apos;s ratio.
                </p>
              </section>
            )}

          <div className="grid gap-6 lg:grid-cols-2 mb-10">
            <section className="surface p-6">
              <div className="flex items-center gap-2 mb-1">
                <h2 className="text-lg font-display tracking-tightest">
                  Risk band breakdown
                </h2>
                <Tooltip
                  content={
                    <>
                      <strong>Risk band</strong> = per-rider lifetime
                      collection ratio (collected ÷ invoiced). A ≥95%, B
                      80–95%, C 60–80%, D 30–60%, E &lt;30%. Watch the D and
                      E riders — they&apos;re drifting toward churn.
                    </>
                  }
                />
              </div>
              <p className="text-xs text-ink-fade mb-4">
                Click a band to filter the rider table below.
              </p>
              <div className="space-y-2">
                {data.bands.map((b) => (
                  <BandFilterLink key={b.band} band={b.band}>
                    <BandRow band={b} />
                  </BandFilterLink>
                ))}
              </div>
            </section>

            <section className="surface p-6">
              <div className="flex items-center gap-2 mb-4">
                <h2 className="text-lg font-display tracking-tightest">
                  Ageing profile (open invoices)
                </h2>
                <Tooltip
                  content={
                    <>
                      <strong>Ageing</strong> = open invoices (balance &gt; 0)
                      grouped by days since the invoice date. 0–30 is normal,
                      31–60 starts to slip, 90+ days needs intervention.
                    </>
                  }
                />
              </div>
              <AgeingProfile ageing={data.ageing} />
            </section>
          </div>

          <section>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-display tracking-tightest">
                Riders ({data.riders.length})
              </h2>
              <span className="text-xs text-ink-fade">
                Click &apos;Download xlsx&apos; above for the filterable Excel
                version.
              </span>
            </div>
            <RidersTable
              riders={data.riders}
              knownAgencies={agencyData.agencies}
              assignments={agencyData.assignments}
            />
          </section>
        </>
      )}
    </div>
  );
}

const BAND_TONE: Record<string, string> = {
  A: "bg-moss-500/10 text-moss-600 border-moss-500/20",
  B: "bg-moss-400/10 text-moss-500 border-moss-400/20",
  C: "bg-accent-500/10 text-accent-700 border-accent-500/20",
  D: "bg-accent-600/15 text-accent-700 border-accent-500/30",
  E: "bg-clay-500/10 text-clay-600 border-clay-500/30",
};

function BandRow({ band }: { band: CollectionsReport["bands"][number] }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 border-b border-canvas-line/60 last:border-b-0">
      <div className="flex items-center gap-3 min-w-0">
        <span
          className={`shrink-0 w-8 h-8 rounded-md border flex items-center justify-center font-display text-sm font-semibold ${BAND_TONE[band.band] ?? ""}`}
        >
          {band.band}
        </span>
        <div className="min-w-0">
          <div className="text-sm font-medium text-ink">
            {band.riders} rider{band.riders === 1 ? "" : "s"}
          </div>
          <div className="text-xs text-ink-fade">{band.definition}</div>
        </div>
      </div>
      <div className="text-sm font-mono text-ink-muted">
        {fmtGhs(band.outstanding_ghs)}
      </div>
    </div>
  );
}

function AgeingProfile({ ageing }: { ageing: CollectionsReport["ageing"] }) {
  const totalOutstanding = ageing.reduce((acc, x) => acc + x.outstanding_ghs, 0);
  return (
    <div className="space-y-2">
      {ageing.map((a) => {
        const pct = totalOutstanding > 0 ? a.outstanding_ghs / totalOutstanding : 0;
        return (
          <div key={a.label} className="space-y-1">
            <div className="flex items-center justify-between text-sm">
              <span className="text-ink-muted">{a.label}</span>
              <span className="font-mono text-ink">
                {fmtGhs(a.outstanding_ghs)}{" "}
                <span className="text-ink-fade text-xs">({a.open_invoices})</span>
              </span>
            </div>
            <div className="h-1.5 bg-canvas-sunken rounded overflow-hidden">
              <div
                className="h-full bg-accent-500"
                style={{ width: `${pct * 100}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AgencySplit({ riders }: { riders: CollectionsReport["riders"] }) {
  const buckets: Record<string, { count: number; outstanding: number }> = {
    Hortta: { count: 0, outstanding: 0 },
    TSAC: { count: 0, outstanding: 0 },
    Unassigned: { count: 0, outstanding: 0 },
  };
  for (const r of riders) {
    const key = r.agency ?? "Unassigned";
    if (!buckets[key]) buckets[key] = { count: 0, outstanding: 0 };
    buckets[key].count += 1;
    buckets[key].outstanding += r.lifetime_outstanding_ghs;
  }
  const total = riders.length || 1;

  return (
    <section className="surface p-6 mb-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-display tracking-tightest">Split by 3rd-party agency</h2>
        <span className="text-xs text-ink-fade">
          Filter to a single agency above; or use the rider-row Assign chip to move riders.
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {(["Hortta", "TSAC", "Unassigned"] as const).map((label) => {
          const b = buckets[label];
          const pct = (b.count / total) * 100;
          const tone =
            label === "Unassigned"
              ? "text-ink"
              : label === "Hortta"
              ? "text-accent-700"
              : "text-moss-600";
          return (
            <div key={label} className="rounded-lg bg-canvas-sunken/50 px-4 py-3">
              <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-ink-fade font-medium">
                <span>{label}</span>
                <span>{pct.toFixed(0)}%</span>
              </div>
              <div className={`mt-1 text-xl font-display tracking-tightest ${tone}`}>
                {b.count.toLocaleString()} rider{b.count === 1 ? "" : "s"}
              </div>
              <div className="text-xs text-ink-fade mt-0.5">
                GHS {b.outstanding.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}{" "}
                outstanding
              </div>
              <div className="h-1.5 mt-2 bg-canvas-line rounded overflow-hidden">
                <div
                  className={`h-full ${
                    label === "Hortta"
                      ? "bg-accent-500"
                      : label === "TSAC"
                      ? "bg-moss-500"
                      : "bg-ink-fade"
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function CashTile({
  label,
  value,
  subtitle,
  tone = "default",
}: {
  label: string;
  value: number;
  subtitle: string;
  tone?: "default" | "moss" | "accent";
}) {
  const color =
    tone === "moss" ? "text-moss-600" : tone === "accent" ? "text-accent-700" : "text-ink";
  return (
    <div className="rounded-lg bg-canvas-sunken/50 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </div>
      <div className={`mt-1 text-xl font-display tracking-tightest ${color}`}>
        {fmtGhs(value)}
      </div>
      <div className="text-[11px] text-ink-fade mt-0.5">{subtitle}</div>
    </div>
  );
}

function PaymentActivityTile({
  rate,
  paid,
  total,
}: {
  rate: number;
  paid: number;
  total: number;
}) {
  return (
    <div className="rounded-lg bg-canvas-sunken/50 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        Payment activity rate
      </div>
      <div className="mt-1 text-xl font-display tracking-tightest text-moss-600">
        {fmtPct(rate)}
      </div>
      <div className="text-[11px] text-ink-fade mt-0.5">
        {paid.toLocaleString()} of {total.toLocaleString()} riders paid in window
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
  tone?: "default" | "warning";
}) {
  return (
    <div className="surface p-5">
      <div className="text-[11px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </div>
      <div
        className={`mt-1.5 text-2xl font-display tracking-tightest ${
          tone === "warning" ? "text-accent-700" : "text-ink"
        }`}
      >
        {value}
      </div>
      {hint && <div className="text-xs text-ink-fade mt-1">{hint}</div>}
    </div>
  );
}

type CollectionsReport = NonNullable<
  Awaited<ReturnType<typeof api.reportCollections>>
>;
