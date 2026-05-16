import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

const CATEGORY_LABELS: Record<string, string> = {
  very_old_open: "Aged open (>180d)",
  large_balance: "Large open balance",
  status_mismatch: "Status mismatch",
  missing_customer: "Missing customer ID",
  duplicate_invoice: "Duplicate invoice",
  unpaid_recurring: "Unpaid recurring streak",
};

const SEVERITIES = ["all", "error", "warning", "info"];

export default async function ExceptionsPage({
  searchParams,
}: {
  searchParams?: { severity?: string; category?: string };
}) {
  const severity = SEVERITIES.includes(searchParams?.severity ?? "")
    ? searchParams!.severity
    : "all";
  const category = searchParams?.category ?? "";

  const data = await api
    .listOutliers({
      ...(severity && severity !== "all" ? { severity } : {}),
      ...(category ? { category } : {}),
      limit: 500,
    })
    .catch(() => null);

  const categories = data ? Object.keys(data.counts).filter((k) => !k.startsWith("_")) : [];

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Triage"
        title="Exceptions & suspense"
        description="Outliers detected live from the invoice corpus — aged open balances, partial-payment suspense, duplicate invoices, and unpaid recurring streaks."
      />

      {!data || data._note ? (
        <div className="surface p-8 text-center text-sm text-ink-fade">
          {data?._note ?? "Failed to load exceptions."}
        </div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-4 mb-6">
            <Stat label="Critical" value={data.counts._critical ?? 0} tone="danger" />
            <Stat label="Warnings" value={data.counts._warning ?? 0} tone="warning" />
            <Stat label="Info" value={data.counts._info ?? 0} />
            <Stat label="Total outliers" value={data.counts._total ?? data.total ?? 0} />
          </div>

          <div className="flex flex-wrap items-center gap-3 mb-4">
            <FilterChips
              label="Severity"
              current={severity ?? "all"}
              options={SEVERITIES.map((s) => ({ value: s, label: s }))}
              param="severity"
            />
            <FilterChips
              label="Category"
              current={category || "all"}
              options={[
                { value: "all", label: "all" },
                ...categories.map((c) => ({
                  value: c,
                  label: `${CATEGORY_LABELS[c] ?? c} (${data.counts[c] ?? 0})`,
                })),
              ]}
              param="category"
            />
          </div>

          <div className="surface overflow-hidden">
            <table className="data-grid">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Category</th>
                  <th>Customer</th>
                  <th>Invoice</th>
                  <th>Amount (GHS)</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {data.items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center text-ink-fade py-8">
                      No outliers match the current filter.
                    </td>
                  </tr>
                )}
                {data.items.map((o, i) => (
                  <tr key={`${o.category}-${o.invoice_id || i}-${o.customer_id}-${i}`}>
                    <td>
                      <StatusBadge value={o.severity} />
                    </td>
                    <td className="text-sm">
                      {CATEGORY_LABELS[o.category] ?? o.category}
                    </td>
                    <td>
                      <div className="text-sm font-medium text-ink">
                        {o.customer_name || "—"}
                      </div>
                      <div className="text-xs text-ink-fade font-mono">
                        {o.customer_id || "—"}
                      </div>
                    </td>
                    <td className="text-xs font-mono text-ink-muted">
                      {o.invoice_number || o.invoice_id?.slice(-8) || "—"}
                      {o.invoice_date && (
                        <div className="text-[10px] text-ink-fade">{o.invoice_date}</div>
                      )}
                    </td>
                    <td className="font-mono text-sm">
                      {o.amount_ghs.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
                    <td className="text-xs text-ink-muted max-w-md">{o.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "warning" | "danger";
}) {
  const color =
    tone === "danger" ? "text-clay-600" : tone === "warning" ? "text-accent-700" : "text-ink";
  return (
    <div className="surface p-4">
      <div className="text-[11px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-display tracking-tightest ${color}`}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function FilterChips({
  label,
  current,
  options,
  param,
}: {
  label: string;
  current: string;
  options: { value: string; label: string }[];
  param: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </span>
      <div className="flex gap-0.5 bg-canvas-sunken p-0.5 rounded-md">
        {options.map((o) => (
          <a
            key={o.value}
            href={o.value === "all" ? `?` : `?${param}=${o.value}`}
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
