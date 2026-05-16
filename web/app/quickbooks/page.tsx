import { PageHeader } from "@/components/PageHeader";
import { api, ReportFleet } from "@/lib/api";
import { QbControls } from "./controls";
import { QbPreviewTable } from "./preview-table";

export const dynamic = "force-dynamic";

const FLEETS: ReportFleet[] = ["All", "Wahu", "TSA"];
const TYPES = ["invoices", "payments"] as const;

function monthStartIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}
function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export default async function QuickBooksPage({
  searchParams,
}: {
  searchParams?: {
    type?: string;
    window_start?: string;
    window_end?: string;
    fleet?: string;
  };
}) {
  const type: "invoices" | "payments" = (TYPES as readonly string[]).includes(searchParams?.type ?? "")
    ? (searchParams!.type as "invoices" | "payments")
    : "invoices";
  const fleet: ReportFleet = (FLEETS as readonly string[]).includes(searchParams?.fleet ?? "")
    ? (searchParams!.fleet as ReportFleet)
    : "All";
  const windowStart = searchParams?.window_start ?? monthStartIso();
  const windowEnd = searchParams?.window_end ?? todayIso();

  const preview = await api
    .qbPreview({
      type,
      window_start: windowStart,
      window_end: windowEnd,
      fleet,
      limit: 50,
    })
    .catch(() => null);

  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Accounting"
        title="QuickBooks accounting entries"
        description="Export invoices or payments for any date range, by fleet. The xlsx is shaped for QuickBooks Online's import templates — see the Methodology sheet in the file for mapping notes."
        actions={
          <QbControls
            type={type}
            fleet={fleet}
            windowStart={windowStart}
            windowEnd={windowEnd}
          />
        }
      />

      {!preview || preview._note ? (
        <div className="surface p-8 text-center text-sm text-ink-fade">
          {preview?._note ?? "Failed to load preview."}
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-3 mb-6">
            <Stat
              label={`${type === "invoices" ? "Invoices" : "Payments"} in window`}
              value={preview.row_count.toLocaleString()}
              hint={`${windowStart} → ${windowEnd}`}
            />
            <Stat
              label={`${type === "invoices" ? "Invoiced" : "Cash received"} (GHS)`}
              value={preview.total_amount_ghs.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            />
            <Stat
              label="QuickBooks Class"
              value={fleet === "All" ? "Wahu + TSA (mixed)" : fleet}
              hint="Each row tags Class for fleet P&L"
            />
          </div>

          <QbPreviewTable type={type} rows={preview.rows} totalRows={preview.row_count} />
        </>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="surface p-5">
      <div className="text-[11px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </div>
      <div className="mt-1.5 text-2xl font-display tracking-tightest text-ink">
        {value}
      </div>
      {hint && <div className="text-xs text-ink-fade mt-1">{hint}</div>}
    </div>
  );
}
