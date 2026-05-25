import { PageHeader } from "@/components/PageHeader";
import { Tooltip } from "@/components/Tooltip";
import {
  api, InvoicesListQuery, InvoicesListResponse, ReportFleet,
} from "@/lib/api";

export const dynamic = "force-dynamic";

type View = "mtd" | "lifetime" | "custom";
type Status = "active" | "recovery" | "completed" | "all";

const VIEWS: View[] = ["mtd", "lifetime", "custom"];
const STATUSES: Status[] = ["active", "recovery", "completed", "all"];
const FLEETS: ReportFleet[] = ["All", "Wahu", "TSA"];

const VIEW_LABEL: Record<View, string> = {
  mtd: "MTD",
  lifetime: "Lifetime",
  custom: "Custom",
};
const STATUS_LABEL: Record<Status, string> = {
  active: "Active",
  recovery: "Recovery",
  completed: "Completed",
  all: "All",
};

function fmtGhs(n: number) {
  return `GHS ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtGhs0(n: number) {
  return `GHS ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
function fmtPct(n: number) {
  return `${n.toFixed(1)}%`;
}

export default async function InvoicesPage({
  searchParams,
}: {
  searchParams?: {
    view?: string;
    status?: string;
    fleet?: string;
    start?: string;
    end?: string;
    q?: string;
    page?: string;
  };
}) {
  const view: View = (VIEWS as readonly string[]).includes(searchParams?.view ?? "")
    ? (searchParams!.view as View) : "mtd";
  const status: Status = (STATUSES as readonly string[]).includes(searchParams?.status ?? "")
    ? (searchParams!.status as Status) : "active";
  const fleet: ReportFleet = (FLEETS as readonly string[]).includes(searchParams?.fleet ?? "")
    ? (searchParams!.fleet as ReportFleet) : "All";
  const start = searchParams?.start || undefined;
  const end = searchParams?.end || undefined;
  const q = searchParams?.q || undefined;
  const pageNum = Math.max(1, Number(searchParams?.page) || 1);
  const limit = 100;
  const offset = (pageNum - 1) * limit;

  const query: InvoicesListQuery = { view, status, fleet, start, end, q, limit, offset };
  const data = await api.invoicesList(query).catch(() => null);

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Invoices"
        title={data ? `Invoices — ${data.window.label}` : "Invoices"}
        description="Every Zoho invoice in scope. Filter by view (MTD/Lifetime/Custom), subscription status, and fleet. Counts and aging update with the filters."
        actions={
          <FilterChips
            view={view} status={status} fleet={fleet}
            start={start} end={end} q={q}
          />
        }
      />

      {view === "custom" && (
        <form method="get" className="surface p-3 mb-6 flex flex-wrap items-end gap-3 text-xs">
          <input type="hidden" name="view" value="custom" />
          <input type="hidden" name="status" value={status} />
          <input type="hidden" name="fleet" value={fleet} />
          {q && <input type="hidden" name="q" value={q} />}
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">From</label>
            <input type="date" name="start" defaultValue={start}
                   className="border border-canvas-line rounded px-2 py-1.5" />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">To</label>
            <input type="date" name="end" defaultValue={end}
                   className="border border-canvas-line rounded px-2 py-1.5" />
          </div>
          <button type="submit" className="btn-primary">Apply range</button>
        </form>
      )}

      <form method="get" className="surface p-3 mb-6 flex items-center gap-3 text-xs">
        <input type="hidden" name="view" value={view} />
        <input type="hidden" name="status" value={status} />
        <input type="hidden" name="fleet" value={fleet} />
        {start && <input type="hidden" name="start" value={start} />}
        {end && <input type="hidden" name="end" value={end} />}
        <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">Search</span>
        <input type="text" name="q" defaultValue={q} placeholder="rider name, customer id, invoice id"
               className="flex-1 border border-canvas-line rounded px-2 py-1.5" />
        <button type="submit" className="btn-primary">Find</button>
      </form>

      {!data ? (
        <div className="surface p-8 text-center text-sm text-ink-fade">
          No invoice data yet. Sync invoice CSVs from the Reports page first.
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-3 mb-6">
            <CountCard summary={data.summary} />
            <ValueCard summary={data.summary} />
            <AgingCard aging={data.aging} />
          </div>

          <section className="surface overflow-hidden">
            <header className="px-4 py-3 border-b border-canvas-line flex items-center justify-between">
              <h3 className="text-sm font-medium text-ink">Invoice register</h3>
              <span className="text-[11px] text-ink-fade">
                Showing {offset + 1}-{Math.min(offset + data.rows.length, data.summary.total_invoices)} of {data.summary.total_invoices.toLocaleString()}
              </span>
            </header>
            <table className="data-grid">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Rider / Customer</th>
                  <th>Stream</th>
                  <th>Date</th>
                  <th>Due</th>
                  <th>Status</th>
                  <th className="!text-right">Total</th>
                  <th className="!text-right">Balance</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.length === 0 && (
                  <tr><td colSpan={8} className="text-center text-ink-fade py-6">No invoices match the filters.</td></tr>
                )}
                {data.rows.map((r) => (
                  <tr key={r.invoice_id}>
                    <td className="font-mono text-[11px] text-ink-muted">{r.invoice_id}</td>
                    <td>
                      <div className="text-sm text-ink">{r.customer_name}</div>
                      <div className="text-[11px] font-mono text-ink-fade">{r.customer_id}</div>
                    </td>
                    <td className="text-[11px] text-ink-muted">{streamShort(r.stream)}</td>
                    <td className="font-mono text-xs">{r.invoice_date ?? "—"}</td>
                    <td className="font-mono text-xs">{r.due_date ?? "—"}</td>
                    <td className="text-xs capitalize">{r.status || "—"}</td>
                    <td className="font-mono text-sm text-right">{fmtGhs(r.total_ghs)}</td>
                    <td className={`font-mono text-sm text-right ${r.balance_ghs > 0 ? "text-clay-600" : "text-ink-fade"}`}>
                      {fmtGhs(r.balance_ghs)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <Pagination total={data.summary.total_invoices} limit={limit} page={pageNum} query={query} />
        </>
      )}
    </div>
  );
}

function streamShort(s: string): string {
  if (s === "rider_daily") return "Daily debit";
  if (s === "rider_larger") return "Rider catch-up";
  if (s === "b2b_dealer") return "B2B / Dealer";
  return s;
}

// ---------------------------------------------------------------------------
// Filter chips — server-rendered links (no client hooks needed)
// ---------------------------------------------------------------------------

function FilterChips({
  view, status, fleet, start, end, q,
}: {
  view: View; status: Status; fleet: ReportFleet;
  start?: string; end?: string; q?: string;
}) {
  const hrefFor = (
    overrides: Partial<{ view: View; status: Status; fleet: ReportFleet }>,
  ) => {
    const next = { view, status, fleet, ...overrides };
    const params = new URLSearchParams();
    if (next.view !== "mtd") params.set("view", next.view);
    if (next.status !== "active") params.set("status", next.status);
    if (next.fleet !== "All") params.set("fleet", next.fleet);
    if (next.view === "custom" && start) params.set("start", start);
    if (next.view === "custom" && end) params.set("end", end);
    if (q) params.set("q", q);
    return params.toString() ? `?${params.toString()}` : "?";
  };

  return (
    <div className="flex flex-wrap items-center gap-3 justify-end">
      <ChipGroup
        label="View"
        tip={<><strong>View</strong> picks the time window for counts and aging. MTD = first of this month through today. Lifetime = all invoices ever issued. Custom = pick a date range.</>}
        options={VIEWS.map((v) => ({ value: v, label: VIEW_LABEL[v] }))}
        current={view} hrefFor={(v) => hrefFor({ view: v as View })}
      />
      <ChipGroup
        label="Status"
        tip={<><strong>Status</strong> filters by subscription state. Active = currently subscribed. Recovery = churned with outstanding balance. Completed = fully paid out. All = everyone.</>}
        options={STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))}
        current={status} hrefFor={(s) => hrefFor({ status: s as Status })}
      />
      <ChipGroup
        label="Fleet"
        tip={<><strong>Fleet</strong> filters by bike ownership. Wahu = standard riders on Wahu-owned bikes. TSA = riders flagged TSA on the subscription.</>}
        options={FLEETS.map((f) => ({ value: f, label: f }))}
        current={fleet} hrefFor={(f) => hrefFor({ fleet: f as ReportFleet })}
      />
    </div>
  );
}

function ChipGroup({
  label, tip, options, current, hrefFor,
}: {
  label: string;
  tip?: React.ReactNode;
  options: { value: string; label: string }[];
  current: string;
  hrefFor: (v: string) => string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">{label}</span>
      {tip && <Tooltip content={tip} side="bottom" align="start" />}
      <div className="flex gap-0.5 bg-canvas-sunken p-0.5 rounded-md ml-1">
        {options.map((o) => (
          <a
            key={o.value}
            href={hrefFor(o.value)}
            className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
              current === o.value
                ? "bg-canvas-raised text-ink shadow-card"
                : "text-ink-muted hover:text-ink"
            }`}
          >
            {o.label}
          </a>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KPI cards
// ---------------------------------------------------------------------------

function CountCard({ summary }: { summary: InvoicesListResponse["summary"] }) {
  return (
    <section className="surface p-5">
      <div className="flex items-center gap-1.5">
        <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
          Invoices issued
        </div>
        <Tooltip
          side="bottom" align="start"
          content={
            <>
              <strong>Count of invoices generated in the selected
              period.</strong>{" "}
              Track alongside Value invoiced to spot mix shifts — fewer
              invoices but higher value often means a tilt toward B2B /
              dealership billing.
            </>
          }
        />
      </div>
      <div className="mt-1 text-3xl font-display tracking-tightest text-ink">
        {summary.total_invoices.toLocaleString()}
      </div>
      <div className="text-xs text-ink-fade mt-1">{summary.open_count.toLocaleString()} still open</div>
    </section>
  );
}

function ValueCard({ summary }: { summary: InvoicesListResponse["summary"] }) {
  return (
    <section className="surface p-5">
      <div className="flex items-center gap-1.5">
        <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
          Value invoiced
        </div>
        <Tooltip
          side="bottom" align="start"
          content={
            <>
              <strong>Total GHS billed in the selected period.</strong>{" "}
              Top-line billing number — what&apos;s been claimed as owed.
              The clay-tinted line below is the share still outstanding
              (balance &gt; 0 on any of these invoices).
            </>
          }
        />
      </div>
      <div className="mt-1 text-3xl font-display tracking-tightest text-ink">
        {fmtGhs0(summary.total_invoiced_ghs)}
      </div>
      <div className="text-xs text-clay-600 mt-1">{fmtGhs0(summary.total_outstanding_ghs)} outstanding</div>
    </section>
  );
}

function AgingCard({ aging }: { aging: InvoicesListResponse["aging"] }) {
  return (
    <section className="surface p-5">
      <div className="flex items-center gap-1.5">
        <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
          Invoice aging
        </div>
        <Tooltip
          side="bottom" align="start"
          content={
            <>
              <strong>% and GHS of unpaid invoice value sitting in
              each DPD bucket.</strong>{" "}
              DPD = days since the invoice was issued. The trend across
              periods matters more than today&apos;s snapshot — a growing
              31–60 bucket today is a 90+ problem in two months.
            </>
          }
        />
      </div>
      <div className="mt-1 text-3xl font-display tracking-tightest text-ink">
        {fmtGhs0(aging.total_outstanding_ghs)}
      </div>
      <div className="text-xs text-ink-fade mt-1">unpaid balance by DPD</div>
      <div className="mt-4 space-y-2">
        {aging.buckets.length === 0 && (
          <div className="text-[11px] text-ink-fade text-center py-3">No open balances in scope.</div>
        )}
        {aging.buckets.map((b) => (
          <div key={b.label} className="grid grid-cols-[6.5rem_1fr_auto] items-center gap-2 text-[11px]">
            <span className="font-mono text-ink-muted">{b.label}</span>
            <div className="h-1.5 bg-canvas-sunken rounded">
              <div
                className={`h-full rounded ${
                  b.label.startsWith("Current") ? "bg-moss-500"
                  : b.label.includes("365d") ? "bg-clay-500"
                  : "bg-accent-500"
                }`}
                style={{ width: `${Math.min(100, b.pct_of_ghs)}%` }}
              />
            </div>
            <span className="font-mono text-ink whitespace-nowrap">
              {fmtGhs0(b.ghs)} <span className="text-ink-fade">{fmtPct(b.pct_of_ghs)}</span>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

function Pagination({
  total, limit, page, query,
}: {
  total: number; limit: number; page: number; query: InvoicesListQuery;
}) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pages <= 1) return null;
  const mk = (p: number) => {
    const params = new URLSearchParams();
    if (query.view && query.view !== "mtd") params.set("view", query.view);
    if (query.status && query.status !== "active") params.set("status", query.status);
    if (query.fleet && query.fleet !== "All") params.set("fleet", query.fleet);
    if (query.start) params.set("start", query.start);
    if (query.end) params.set("end", query.end);
    if (query.q) params.set("q", query.q);
    if (p !== 1) params.set("page", String(p));
    return params.toString() ? `?${params.toString()}` : "?";
  };
  return (
    <nav className="flex items-center gap-2 mt-6 text-xs">
      <a href={mk(Math.max(1, page - 1))}
         className={`px-2 py-1 rounded ${page === 1 ? "text-ink-fade pointer-events-none" : "hover:bg-canvas-sunken"}`}>
        ← Prev
      </a>
      <span className="text-ink-muted font-mono">{page} / {pages}</span>
      <a href={mk(Math.min(pages, page + 1))}
         className={`px-2 py-1 rounded ${page === pages ? "text-ink-fade pointer-events-none" : "hover:bg-canvas-sunken"}`}>
        Next →
      </a>
    </nav>
  );
}
