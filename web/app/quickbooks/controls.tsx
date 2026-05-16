"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Download } from "lucide-react";
import { api, ReportFleet } from "@/lib/api";
import { Tooltip } from "@/components/Tooltip";

const FLEETS: ReportFleet[] = ["All", "Wahu", "TSA"];

export function QbControls({
  type,
  fleet,
  windowStart,
  windowEnd,
}: {
  type: "invoices" | "payments";
  fleet: ReportFleet;
  windowStart: string;
  windowEnd: string;
}) {
  const router = useRouter();
  const search = useSearchParams();

  const setParams = (changes: Record<string, string | null>) => {
    const params = new URLSearchParams(search.toString());
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === "") params.delete(k);
      else params.set(k, v);
    }
    router.push(`?${params.toString()}`);
  };

  return (
    <div className="flex flex-col gap-3 items-end">
      <div className="flex flex-wrap items-center gap-3 justify-end">
        <Segmented
          label="Type"
          tip={
            <>
              <strong>Invoices:</strong> one row per Zoho invoice issued in the
              window. <strong>Payments:</strong> one row per recorded payment
              (Last Payment Date in window).
            </>
          }
          options={[
            { value: "invoices", label: "Invoices" },
            { value: "payments", label: "Payments" },
          ]}
          current={type}
          onChange={(v) => setParams({ type: v })}
        />

        <Segmented
          label="Fleet"
          tip="Maps to QuickBooks 'Class' for separate P&L by fleet."
          options={FLEETS.map((f) => ({ value: f, label: f }))}
          current={fleet}
          onChange={(v) => setParams({ fleet: v })}
        />

        <a
          href={api.qbDownloadUrl({
            type,
            window_start: windowStart,
            window_end: windowEnd,
            fleet,
          })}
          className="btn-primary"
        >
          <Download className="w-3.5 h-3.5" />
          Download xlsx
        </a>
      </div>

      <div className="flex items-center gap-2 text-xs">
        <span className="uppercase tracking-wider text-ink-fade font-medium">
          Window
        </span>
        <input
          type="date"
          value={windowStart}
          onChange={(e) => setParams({ window_start: e.target.value })}
          className="px-2 py-1 bg-canvas-raised border border-canvas-line rounded-md text-sm
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
        />
        <span className="text-ink-fade">→</span>
        <input
          type="date"
          value={windowEnd}
          onChange={(e) => setParams({ window_end: e.target.value })}
          className="px-2 py-1 bg-canvas-raised border border-canvas-line rounded-md text-sm
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
        />
      </div>
    </div>
  );
}

function Segmented({
  label,
  tip,
  options,
  current,
  onChange,
}: {
  label: string;
  tip?: React.ReactNode;
  options: { value: string; label: string }[];
  current: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </span>
      {tip && <Tooltip content={tip} side="bottom" align="start" />}
      <div className="flex gap-0.5 bg-canvas-sunken p-0.5 rounded-md ml-1">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
              current === o.value
                ? "bg-canvas-raised text-ink shadow-card"
                : "text-ink-muted hover:text-ink"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
