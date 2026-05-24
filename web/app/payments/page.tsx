import Link from "next/link";
import { ArrowRight, CheckCircle2, AlertCircle } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Tooltip } from "@/components/Tooltip";
import {
  api, PaymentChannel, PaymentMatchStatus, PaymentsListQuery,
  PaymentsListResponse, PaymentView,
} from "@/lib/api";

export const dynamic = "force-dynamic";

const VIEWS: PaymentView[] = ["mtd", "lifetime", "custom"];
const VIEW_LABEL: Record<PaymentView, string> = {
  mtd: "MTD", lifetime: "Lifetime", custom: "Custom",
};

const CHANNELS: PaymentChannel[] = ["all", "mtn", "telecel", "bank", "bolt_deduction", "cash", "hero"];
const CHANNEL_LABEL: Record<string, string> = {
  all: "All", mtn: "MTN", telecel: "Telecel", bank: "Bank",
  bolt_deduction: "Bolt", cash: "Cash", hero: "AirtelTigo",
};

const MATCH_STATUSES: PaymentMatchStatus[] = ["all", "matched", "unmatched"];
const MATCH_STATUS_LABEL: Record<PaymentMatchStatus, string> = {
  all: "All", matched: "Matched", unmatched: "Unmatched",
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

export default async function PaymentsPage({
  searchParams,
}: {
  searchParams?: {
    view?: string;
    channel?: string;
    match_status?: string;
    start?: string;
    end?: string;
    q?: string;
    page?: string;
  };
}) {
  const view: PaymentView = (VIEWS as readonly string[]).includes(searchParams?.view ?? "")
    ? (searchParams!.view as PaymentView) : "mtd";
  const channel: PaymentChannel = (CHANNELS as readonly string[]).includes(searchParams?.channel ?? "")
    ? (searchParams!.channel as PaymentChannel) : "all";
  const match_status: PaymentMatchStatus = (MATCH_STATUSES as readonly string[]).includes(
    searchParams?.match_status ?? "",
  )
    ? (searchParams!.match_status as PaymentMatchStatus) : "all";
  const start = searchParams?.start || undefined;
  const end = searchParams?.end || undefined;
  const q = searchParams?.q || undefined;
  const pageNum = Math.max(1, Number(searchParams?.page) || 1);
  const limit = 100;
  const offset = (pageNum - 1) * limit;

  const query: PaymentsListQuery = {
    view, channel, match_status, start, end, q, limit, offset,
  };
  const data = await api.paymentsList(query).catch(() => null);

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Payments"
        title={data ? `Payments — ${data.window.label}` : "Payments"}
        description="Every payment from MTN MoMo, Telecel, AirtelTigo, Bank, Cash, and Bolt deductions. Counts, value, and timeliness update with the filters."
        actions={
          <div className="flex items-center gap-3">
            <FilterChips view={view} channel={channel} match_status={match_status}
                         start={start} end={end} q={q} />
            <Link href="/payments/reconcile"
                  className="btn-primary inline-flex items-center gap-2 ml-2">
              Reconcile <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        }
      />

      {view === "custom" && (
        <form method="get" className="surface p-3 mb-6 flex flex-wrap items-end gap-3 text-xs">
          <input type="hidden" name="view" value="custom" />
          <input type="hidden" name="channel" value={channel} />
          <input type="hidden" name="match_status" value={match_status} />
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
        <input type="hidden" name="channel" value={channel} />
        <input type="hidden" name="match_status" value={match_status} />
        {start && <input type="hidden" name="start" value={start} />}
        {end && <input type="hidden" name="end" value={end} />}
        <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">Search</span>
        <input type="text" name="q" defaultValue={q}
               placeholder="sender, rider name, reference, phone"
               className="flex-1 border border-canvas-line rounded px-2 py-1.5" />
        <button type="submit" className="btn-primary">Find</button>
      </form>

      {!data ? (
        <div className="surface p-8 text-center text-sm text-ink-fade">
          Couldn't load payments. Sync from the Reconcile page first.
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-3 mb-4">
            <CountCard summary={data.summary} />
            <ValueCard summary={data.summary} />
            <RidersCard summary={data.summary} />
          </div>

          <div className="grid gap-4 md:grid-cols-2 mb-6">
            <MethodCard summary={data.summary} />
            <TimelinessCard summary={data.summary} />
          </div>

          <section className="surface overflow-hidden">
            <header className="px-4 py-3 border-b border-canvas-line flex items-center justify-between">
              <h3 className="text-sm font-medium text-ink">Payment register</h3>
              <span className="text-[11px] text-ink-fade">
                Showing {offset + 1}-{Math.min(offset + data.rows.length, data.row_total)} of {data.row_total.toLocaleString()}
              </span>
            </header>
            <table className="data-grid">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Method</th>
                  <th>Sender / Rider</th>
                  <th>Reference</th>
                  <th>Match</th>
                  <th>Timeliness</th>
                  <th className="!text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.length === 0 && (
                  <tr><td colSpan={7} className="text-center text-ink-fade py-6">No payments match the filters.</td></tr>
                )}
                {data.rows.map((r, i) => (
                  <tr key={`${r.txn_id}-${i}`}>
                    <td className="font-mono text-xs">{r.date ?? "—"}</td>
                    <td className="text-xs">{r.method}</td>
                    <td>
                      {r.matched && r.rider_name ? (
                        <>
                          <div className="text-sm text-ink">{r.rider_name}</div>
                          <div className="text-[11px] text-ink-fade">{r.sender_name || "—"}</div>
                        </>
                      ) : (
                        <div className="text-sm text-ink-muted">{r.sender_name || "—"}</div>
                      )}
                    </td>
                    <td className="font-mono text-[11px] text-ink-muted">{r.reference || "—"}</td>
                    <td className="text-xs">
                      {r.matched ? (
                        <span className="inline-flex items-center gap-1 text-moss-600">
                          <CheckCircle2 className="w-3 h-3" /> Matched
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-clay-600">
                          <AlertCircle className="w-3 h-3" /> Unmatched
                        </span>
                      )}
                    </td>
                    <td className="text-[11px] text-ink-muted">
                      {r.matched && r.timeliness !== "Unknown" ? r.timeliness : "—"}
                    </td>
                    <td className="font-mono text-sm text-right text-moss-600">{fmtGhs(r.amount_ghs)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <Pagination total={data.row_total} limit={limit} page={pageNum} query={query} />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter chips
// ---------------------------------------------------------------------------

function FilterChips({
  view, channel, match_status, start, end, q,
}: {
  view: PaymentView; channel: PaymentChannel; match_status: PaymentMatchStatus;
  start?: string; end?: string; q?: string;
}) {
  const hrefFor = (
    overrides: Partial<{ view: PaymentView; channel: PaymentChannel; match_status: PaymentMatchStatus }>,
  ) => {
    const next = { view, channel, match_status, ...overrides };
    const params = new URLSearchParams();
    if (next.view !== "mtd") params.set("view", next.view);
    if (next.channel !== "all") params.set("channel", next.channel);
    if (next.match_status !== "all") params.set("match_status", next.match_status);
    if (next.view === "custom" && start) params.set("start", start);
    if (next.view === "custom" && end) params.set("end", end);
    if (q) params.set("q", q);
    return params.toString() ? `?${params.toString()}` : "?";
  };

  return (
    <div className="flex flex-wrap items-center gap-3 justify-end">
      <ChipGroup
        label="View"
        tip={<><strong>View</strong> picks the time window. MTD = first of this month through today. Lifetime = all payments ever received. Custom = pick a date range.</>}
        options={VIEWS.map((v) => ({ value: v, label: VIEW_LABEL[v] }))}
        current={view} hrefFor={(v) => hrefFor({ view: v as PaymentView })}
      />
      <ChipGroup
        label="Channel"
        tip={<><strong>Channel</strong> narrows the table (not the KPI cards) to one payment rail. MoMo channels: MTN, Telecel, AirtelTigo. Bolt is the weekly approved-deduction synthetic feed.</>}
        options={CHANNELS.map((c) => ({ value: c, label: CHANNEL_LABEL[c] }))}
        current={channel} hrefFor={(c) => hrefFor({ channel: c as PaymentChannel })}
      />
      <ChipGroup
        label="Match"
        tip={<><strong>Match</strong> filters the table by whether the payment was matched to a rider. Unmatched payments are candidates for Suspense.</>}
        options={MATCH_STATUSES.map((s) => ({ value: s, label: MATCH_STATUS_LABEL[s] }))}
        current={match_status} hrefFor={(s) => hrefFor({ match_status: s as PaymentMatchStatus })}
      />
    </div>
  );
}

function ChipGroup({
  label, tip, options, current, hrefFor,
}: {
  label: string; tip?: React.ReactNode;
  options: { value: string; label: string }[];
  current: string; hrefFor: (v: string) => string;
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

function CountCard({ summary }: { summary: PaymentsListResponse["summary"] }) {
  const matchedPct = summary.total_payments > 0
    ? (summary.matched_count / summary.total_payments) * 100 : 0;
  return (
    <section className="surface p-5">
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        Payments received
      </div>
      <div className="mt-1 text-3xl font-display tracking-tightest text-ink">
        {summary.total_payments.toLocaleString()}
      </div>
      <div className="text-xs text-ink-fade mt-1">
        {summary.matched_count.toLocaleString()} matched ·{" "}
        <span className="text-clay-600">{summary.unmatched_count.toLocaleString()} unmatched</span>
      </div>
      <div className="mt-3 h-1.5 bg-canvas-sunken rounded">
        <div className="h-full bg-moss-500 rounded" style={{ width: `${matchedPct}%` }} />
      </div>
    </section>
  );
}

function ValueCard({ summary }: { summary: PaymentsListResponse["summary"] }) {
  return (
    <section className="surface p-5">
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        Value received
      </div>
      <div className="mt-1 text-3xl font-display tracking-tightest text-moss-600">
        {fmtGhs0(summary.total_value_ghs)}
      </div>
      <div className="text-xs text-ink-fade mt-1">
        {fmtGhs0(summary.matched_value_ghs)} applied ·{" "}
        <span className="text-clay-600">{fmtGhs0(summary.unmatched_value_ghs)} in limbo</span>
      </div>
    </section>
  );
}

function RidersCard({ summary }: { summary: PaymentsListResponse["summary"] }) {
  const avgPerRider = summary.unique_paying_riders > 0
    ? summary.matched_value_ghs / summary.unique_paying_riders : 0;
  return (
    <section className="surface p-5">
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        Unique paying riders
      </div>
      <div className="mt-1 text-3xl font-display tracking-tightest text-ink">
        {summary.unique_paying_riders.toLocaleString()}
      </div>
      <div className="text-xs text-ink-fade mt-1">
        avg {fmtGhs0(avgPerRider)} per rider · feeds the dashboard's Active Payer Rate
      </div>
    </section>
  );
}

function MethodCard({ summary }: { summary: PaymentsListResponse["summary"] }) {
  const maxVal = Math.max(1, ...summary.by_method.map((m) => m.value_ghs));
  return (
    <section className="surface p-5">
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        Payments by method
      </div>
      <div className="mt-3 space-y-2">
        {summary.by_method.length === 0 && (
          <div className="text-[11px] text-ink-fade text-center py-3">No payments in window.</div>
        )}
        {summary.by_method.map((m) => (
          <div key={m.method} className="grid grid-cols-[8rem_1fr_auto] items-center gap-3 text-[11px]">
            <span className="text-ink-muted">{m.method}</span>
            <div className="h-1.5 bg-canvas-sunken rounded">
              <div className="h-full bg-accent-500 rounded" style={{ width: `${(m.value_ghs / maxVal) * 100}%` }} />
            </div>
            <span className="font-mono text-ink whitespace-nowrap">
              {fmtGhs0(m.value_ghs)} <span className="text-ink-fade">({m.count.toLocaleString()})</span>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function TimelinessCard({ summary }: { summary: PaymentsListResponse["summary"] }) {
  return (
    <section className="surface p-5">
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        Payment timeliness
      </div>
      <div className="text-[11px] text-ink-fade mt-1">
        Matched payments only · against invoice due_date
      </div>
      <div className="mt-3 space-y-2">
        {summary.timeliness.every((t) => t.count === 0) && (
          <div className="text-[11px] text-ink-fade text-center py-3">No matched payments in window.</div>
        )}
        {summary.timeliness.filter((t) => t.count > 0).map((t) => {
          const tone =
            t.bucket === "Early" || t.bucket === "On-time" ? "bg-moss-500"
            : t.bucket === "30+ days late" ? "bg-clay-500"
            : "bg-accent-500";
          return (
            <div key={t.bucket} className="grid grid-cols-[7rem_1fr_auto] items-center gap-3 text-[11px]">
              <span className="text-ink-muted">{t.bucket}</span>
              <div className="h-1.5 bg-canvas-sunken rounded">
                <div className={`h-full ${tone} rounded`} style={{ width: `${Math.min(100, t.pct_value)}%` }} />
              </div>
              <span className="font-mono text-ink whitespace-nowrap">
                {fmtPct(t.pct_value)} <span className="text-ink-fade">({t.count.toLocaleString()})</span>
              </span>
            </div>
          );
        })}
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
  total: number; limit: number; page: number; query: PaymentsListQuery;
}) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pages <= 1) return null;
  const mk = (p: number) => {
    const params = new URLSearchParams();
    if (query.view && query.view !== "mtd") params.set("view", query.view);
    if (query.channel && query.channel !== "all") params.set("channel", query.channel);
    if (query.match_status && query.match_status !== "all") params.set("match_status", query.match_status);
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
