import { PageHeader } from "@/components/PageHeader";
import { api, InvoicesListQuery, ReportFleet } from "@/lib/api";

export const dynamic = "force-dynamic";

const FLEETS: ReportFleet[] = ["All", "Wahu", "TSA"];
const STATUSES = ["all", "open", "paid", "overdue", "partial"] as const;
type Status = typeof STATUSES[number];

function fmtGhs(n: number) {
  return `GHS ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtGhs0(n: number) {
  return `GHS ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export default async function InvoicesPage({
  searchParams,
}: {
  searchParams?: {
    fleet?: string;
    status?: string;
    start?: string;
    end?: string;
    q?: string;
    page?: string;
  };
}) {
  const fleet: ReportFleet = (FLEETS as readonly string[]).includes(
    searchParams?.fleet ?? "",
  )
    ? (searchParams!.fleet as ReportFleet)
    : "All";
  const status: Status = (STATUSES as readonly string[]).includes(
    searchParams?.status ?? "",
  )
    ? (searchParams!.status as Status)
    : "all";
  const start = searchParams?.start || undefined;
  const end = searchParams?.end || undefined;
  const q = searchParams?.q || undefined;
  const pageNum = Math.max(1, Number(searchParams?.page) || 1);
  const limit = 100;
  const offset = (pageNum - 1) * limit;

  const query: InvoicesListQuery = { fleet, status, start, end, q, limit, offset };
  const data = await api.invoicesList(query).catch(() => null);

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Invoices"
        title="All invoices"
        description="Every billed Zoho invoice with filters. Status, fleet, date range, and free-text search."
      />

      <form method="get" className="surface p-4 mb-6 flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">
            Fleet
          </label>
          <select name="fleet" defaultValue={fleet} className="text-xs border border-canvas-line rounded px-2 py-1.5">
            {FLEETS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">
            Status
          </label>
          <select name="status" defaultValue={status} className="text-xs border border-canvas-line rounded px-2 py-1.5 capitalize">
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">
            From
          </label>
          <input type="date" name="start" defaultValue={start}
                 className="text-xs border border-canvas-line rounded px-2 py-1.5" />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">
            To
          </label>
          <input type="date" name="end" defaultValue={end}
                 className="text-xs border border-canvas-line rounded px-2 py-1.5" />
        </div>
        <div className="flex-1 min-w-[180px]">
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">
            Search
          </label>
          <input type="text" name="q" defaultValue={q} placeholder="rider name, customer id, invoice id"
                 className="w-full text-xs border border-canvas-line rounded px-2 py-1.5" />
        </div>
        <button type="submit" className="btn-primary">Apply</button>
      </form>

      {!data ? (
        <div className="surface p-8 text-center text-sm text-ink-fade">
          No invoice data yet. Sync from the Reports page first.
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-4 mb-6">
            <Stat label="Invoices" value={data.total.toLocaleString()}
                  hint={`${data.open_count.toLocaleString()} open`} />
            <Stat label="Total invoiced" value={fmtGhs0(data.total_invoiced_ghs)} />
            <Stat label="Outstanding" value={fmtGhs0(data.total_outstanding_ghs)} tone="warn" />
            <Stat label="Showing" value={`${offset + 1}-${Math.min(offset + data.rows.length, data.total)}`}
                  hint={`page ${pageNum} of ${Math.max(1, Math.ceil(data.total / limit))}`} />
          </div>

          <section className="surface overflow-hidden">
            <table className="data-grid">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Rider</th>
                  <th>Date</th>
                  <th>Due</th>
                  <th>Status</th>
                  <th className="!text-right">Total</th>
                  <th className="!text-right">Balance</th>
                  <th>Last paid</th>
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
                    <td className="font-mono text-xs">{r.invoice_date ?? "—"}</td>
                    <td className="font-mono text-xs">{r.due_date ?? "—"}</td>
                    <td className="text-xs capitalize">{r.status || "—"}</td>
                    <td className="font-mono text-sm text-right">{fmtGhs(r.total_ghs)}</td>
                    <td className={`font-mono text-sm text-right ${r.balance_ghs > 0 ? "text-clay-600" : "text-ink-fade"}`}>
                      {fmtGhs(r.balance_ghs)}
                    </td>
                    <td className="font-mono text-xs">{r.last_payment_date ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <Pagination total={data.total} limit={limit} page={pageNum} query={query} />
        </>
      )}
    </div>
  );
}

function Stat({
  label, value, hint, tone = "default",
}: {
  label: string; value: string; hint?: string;
  tone?: "default" | "warn" | "good";
}) {
  const color = tone === "warn" ? "text-accent-700" : tone === "good" ? "text-moss-600" : "text-ink";
  return (
    <div className="surface p-4">
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">{label}</div>
      <div className={`mt-1 text-xl font-display tracking-tightest ${color}`}>{value}</div>
      {hint && <div className="text-[11px] text-ink-fade mt-0.5">{hint}</div>}
    </div>
  );
}

function Pagination({
  total, limit, page, query,
}: {
  total: number; limit: number; page: number; query: InvoicesListQuery;
}) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pages <= 1) return null;
  const mk = (p: number) => {
    const params = new URLSearchParams();
    if (query.fleet && query.fleet !== "All") params.set("fleet", query.fleet);
    if (query.status && query.status !== "all") params.set("status", query.status);
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
