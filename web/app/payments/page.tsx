import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { api, PaymentChannel, PaymentsListQuery } from "@/lib/api";

export const dynamic = "force-dynamic";

const CHANNELS: PaymentChannel[] = ["all", "mtn", "telecel", "bank", "bolt_deduction", "hero", "cash", "unknown"];
const CHANNEL_LABEL: Record<string, string> = {
  all: "All channels",
  mtn: "MTN MoMo",
  telecel: "Telecel",
  bank: "Bank",
  bolt_deduction: "Bolt deduction",
  hero: "Hero",
  cash: "Cash",
  unknown: "Unknown",
};

function fmtGhs(n: number) {
  return `GHS ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtGhs0(n: number) {
  return `GHS ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export default async function PaymentsPage({
  searchParams,
}: {
  searchParams?: {
    channel?: string;
    start?: string;
    end?: string;
    q?: string;
    page?: string;
  };
}) {
  const channel: PaymentChannel = (CHANNELS as readonly string[]).includes(
    searchParams?.channel ?? "",
  )
    ? (searchParams!.channel as PaymentChannel)
    : "all";
  const start = searchParams?.start || undefined;
  const end = searchParams?.end || undefined;
  const q = searchParams?.q || undefined;
  const pageNum = Math.max(1, Number(searchParams?.page) || 1);
  const limit = 100;
  const offset = (pageNum - 1) * limit;

  const query: PaymentsListQuery = { channel, start, end, q, limit, offset };
  const data = await api.paymentsList(query).catch(() => null);

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Payments"
        title="All payments"
        description="MTN MoMo, Telecel, Bank, and Bolt approved-deduction rows. Filter by channel, date, or search."
        actions={
          <Link href="/payments/reconcile"
                className="btn-primary inline-flex items-center gap-2">
            Reconcile payments <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        }
      />

      <form method="get" className="surface p-4 mb-6 flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">Channel</label>
          <select name="channel" defaultValue={channel} className="text-xs border border-canvas-line rounded px-2 py-1.5">
            {CHANNELS.map((c) => <option key={c} value={c}>{CHANNEL_LABEL[c]}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">From</label>
          <input type="date" name="start" defaultValue={start}
                 className="text-xs border border-canvas-line rounded px-2 py-1.5" />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">To</label>
          <input type="date" name="end" defaultValue={end}
                 className="text-xs border border-canvas-line rounded px-2 py-1.5" />
        </div>
        <div className="flex-1 min-w-[180px]">
          <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">Search</label>
          <input type="text" name="q" defaultValue={q} placeholder="sender, phone, reference, narration"
                 className="w-full text-xs border border-canvas-line rounded px-2 py-1.5" />
        </div>
        <button type="submit" className="btn-primary">Apply</button>
      </form>

      {!data ? (
        <div className="surface p-8 text-center text-sm text-ink-fade">
          Couldn't load payments. Sync the Drive folder via the Reconcile page first.
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-4 mb-6">
            <Stat label="Payments" value={data.total.toLocaleString()} />
            <Stat label="Total amount" value={fmtGhs0(data.total_amount_ghs)} tone="good" />
            <Stat
              label="Channels"
              value={Object.keys(data.by_channel).length.toString()}
              hint={Object.keys(data.by_channel).map((c) => CHANNEL_LABEL[c] || c).join(", ") || "—"}
            />
            <Stat label="Showing" value={`${offset + 1}-${Math.min(offset + data.rows.length, data.total)}`}
                  hint={`page ${pageNum} of ${Math.max(1, Math.ceil(data.total / limit))}`} />
          </div>

          {Object.keys(data.by_channel).length > 0 && (
            <section className="surface p-4 mb-6">
              <h3 className="text-xs uppercase tracking-wider text-ink-fade font-medium mb-3">By channel</h3>
              <div className="space-y-2">
                {Object.entries(data.by_channel)
                  .sort((a, b) => b[1].amount_ghs - a[1].amount_ghs)
                  .map(([ch, v]) => {
                    const pct = data.total_amount_ghs > 0
                      ? (v.amount_ghs / data.total_amount_ghs) * 100 : 0;
                    return (
                      <div key={ch} className="grid grid-cols-[8rem_1fr_auto] items-center gap-3 text-xs">
                        <span className="text-ink-muted">{CHANNEL_LABEL[ch] || ch}</span>
                        <div className="h-2 bg-canvas-sunken rounded">
                          <div className="h-full bg-accent-500 rounded" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="font-mono whitespace-nowrap">
                          {fmtGhs0(v.amount_ghs)} <span className="text-ink-fade">({v.count})</span>
                        </span>
                      </div>
                    );
                  })}
              </div>
            </section>
          )}

          <section className="surface overflow-hidden">
            <table className="data-grid">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Channel</th>
                  <th>Sender</th>
                  <th>Phone</th>
                  <th>Reference</th>
                  <th className="!text-right">Amount</th>
                  <th>Source file</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.length === 0 && (
                  <tr><td colSpan={7} className="text-center text-ink-fade py-6">No payments match the filters.</td></tr>
                )}
                {data.rows.map((r, i) => (
                  <tr key={`${r.txn_id}-${i}`}>
                    <td className="font-mono text-xs">{r.date ?? "—"}</td>
                    <td className="text-xs">{CHANNEL_LABEL[r.channel] || r.channel}</td>
                    <td className="text-sm">{r.sender_name || "—"}</td>
                    <td className="font-mono text-xs">{r.sender_phone || "—"}</td>
                    <td className="font-mono text-[11px] text-ink-muted">{r.reference || "—"}</td>
                    <td className="font-mono text-sm text-right text-moss-600">{fmtGhs(r.amount_ghs)}</td>
                    <td className="font-mono text-[11px] text-ink-fade truncate max-w-xs">{r.source_file}</td>
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
      {hint && <div className="text-[11px] text-ink-fade mt-0.5 truncate">{hint}</div>}
    </div>
  );
}

function Pagination({
  total, limit, page, query,
}: {
  total: number; limit: number; page: number; query: PaymentsListQuery;
}) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pages <= 1) return null;
  const mk = (p: number) => {
    const params = new URLSearchParams();
    if (query.channel && query.channel !== "all") params.set("channel", query.channel);
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
