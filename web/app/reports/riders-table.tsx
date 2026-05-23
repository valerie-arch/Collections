"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { X } from "lucide-react";
import type { CollectionsReport } from "@/lib/api";
import { AgencyCell } from "./agency-cell";

const BAND_TONE: Record<string, string> = {
  A: "bg-moss-500/10 text-moss-600",
  B: "bg-moss-400/10 text-moss-500",
  C: "bg-accent-500/10 text-accent-700",
  D: "bg-accent-600/15 text-accent-700",
  E: "bg-clay-500/10 text-clay-600",
};

const BANDS = ["All", "A", "B", "C", "D", "E"] as const;

type Rider = CollectionsReport["riders"][number];

export function RidersTable({
  riders,
  knownAgencies,
  assignments,
}: {
  riders: Rider[];
  knownAgencies: string[];
  assignments?: Record<string, { agency: string; assigned_at: string; note: string | null }>;
}) {
  const router = useRouter();
  const search = useSearchParams();
  const bandParam = search.get("band") ?? "All";
  const bandFilter = (BANDS as readonly string[]).includes(bandParam) ? bandParam : "All";
  const [q, setQ] = useState("");

  const setBand = (b: string) => {
    const params = new URLSearchParams(search.toString());
    if (b === "All") params.delete("band");
    else params.set("band", b);
    router.replace(`?${params.toString()}`, { scroll: false });
  };

  const filtered = useMemo(() => {
    return riders.filter((r) => {
      if (bandFilter !== "All" && r.risk_band !== bandFilter) return false;
      if (q && !`${r.customer_id} ${r.customer_name}`.toLowerCase().includes(q.toLowerCase()))
        return false;
      return true;
    });
  }, [riders, bandFilter, q]);

  return (
    <div className="surface overflow-hidden" id="riders-table">
      <div className="px-4 py-3 border-b border-canvas-line flex items-center gap-3 bg-canvas-sunken/40 flex-wrap">
        <input
          placeholder="Search customer…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="text-sm bg-canvas-raised border border-canvas-line rounded-md px-3 py-1.5 w-64
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
        />
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
            Band
          </span>
          <div className="flex gap-0.5 bg-canvas-raised border border-canvas-line p-0.5 rounded-md">
            {BANDS.map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBand(b)}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                  bandFilter === b
                    ? "bg-ink text-canvas-raised"
                    : "text-ink-muted hover:text-ink"
                }`}
              >
                {b}
              </button>
            ))}
          </div>
        </div>
        {bandFilter !== "All" && (
          <button
            type="button"
            onClick={() => setBand("All")}
            className="inline-flex items-center gap-1 text-xs text-accent-700 hover:text-accent-600"
          >
            Clear band filter <X className="w-3 h-3" />
          </button>
        )}
        <span className="text-xs text-ink-fade ml-auto">
          {filtered.length} of {riders.length}
        </span>
      </div>

      <div className="overflow-x-auto max-h-[600px]">
        <table className="data-grid">
          <thead className="sticky top-0">
            <tr>
              <th>Customer</th>
              <th>Last invoice</th>
              <th>Last payment</th>
              <th>Inv.</th>
              <th>Open</th>
              <th>Invoiced</th>
              <th>Collected</th>
              <th>Outstanding</th>
              <th>Ratio</th>
              <th>Band</th>
              <th>Agency</th>
              <th>Plans</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={12} className="text-center text-ink-fade py-8">
                  No riders match.
                </td>
              </tr>
            )}
            {filtered.map((r) => (
              <tr key={r.customer_id}>
                <td>
                  <div className="font-medium text-ink">{r.customer_name}</div>
                  <div className="text-xs text-ink-fade font-mono">{r.customer_id}</div>
                </td>
                <td className="text-ink-muted text-sm">
                  {r.last_invoice}
                  <div className="text-xs text-ink-fade">
                    {r.months_since_last_invoice}mo ago
                  </div>
                </td>
                <td className="text-ink-muted text-sm">
                  {r.last_payment_date || <span className="text-ink-fade">—</span>}
                </td>
                <td className="font-mono text-sm">{r.lifetime_invoices}</td>
                <td className="font-mono text-sm">{r.open_invoices}</td>
                <td className="font-mono text-sm">
                  {r.lifetime_invoiced_ghs.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </td>
                <td className="font-mono text-sm text-moss-600">
                  {r.lifetime_collected_ghs.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </td>
                <td className="font-mono text-sm text-clay-600">
                  {r.lifetime_outstanding_ghs.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </td>
                <td className="font-mono text-sm">
                  {(r.collection_ratio * 100).toFixed(1)}%
                </td>
                <td>
                  <span
                    className={`inline-flex items-center justify-center w-7 h-7 rounded-md text-xs font-semibold ${BAND_TONE[r.risk_band] ?? ""}`}
                  >
                    {r.risk_band}
                  </span>
                </td>
                <td>
                  <AgencyCell
                    customerId={r.customer_id}
                    customerName={r.customer_name}
                    currentAgency={r.agency}
                    assignedAt={assignments?.[r.customer_id]?.assigned_at ?? null}
                    knownAgencies={knownAgencies}
                  />
                </td>
                <td className="text-xs text-ink-fade max-w-xs truncate">
                  {r.plans}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
