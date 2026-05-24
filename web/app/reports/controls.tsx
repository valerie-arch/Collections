"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Download } from "lucide-react";
import { api, ReportFleet, ReportStatus, ReportView } from "@/lib/api";
import { Tooltip } from "@/components/Tooltip";
import { MemoButton } from "./memo-modal";

const VIEWS: { value: ReportView; label: string; tip: React.ReactNode }[] = [
  {
    value: "mtd",
    label: "MTD",
    tip: (
      <>
        <strong>Month to date.</strong> Cohort = riders with at least one
        invoice this calendar month. Numbers reflect <em>only this month&apos;s</em>{" "}
        invoices.
      </>
    ),
  },
  {
    value: "lifetime",
    label: "Lifetime",
    tip: (
      <>
        <strong>Lifetime.</strong> Every rider ever invoiced, with their
        full all-time numbers — no year cutoff.
      </>
    ),
  },
  {
    value: "custom",
    label: "Custom",
    tip: (
      <>
        <strong>Custom window.</strong> Pick a start and end date. Cohort =
        riders with an invoice in that window; numbers cover invoices in the
        window only.
      </>
    ),
  },
];

const FLEETS: { value: ReportFleet; tip: React.ReactNode }[] = [
  { value: "All", tip: "Both Wahu Fleet and TSA riders." },
  { value: "Wahu", tip: "Standard Wahu Fleet — the default." },
  {
    value: "TSA",
    tip: "Riders flagged TSA on their Zoho subscription (separate operating partnership).",
  },
];

const STATUSES: { value: ReportStatus; label: string; tip: React.ReactNode }[] = [
  {
    value: "active",
    label: "Active",
    tip: (
      <>
        <strong>Active.</strong> Subscription is currently live or paused —
        the standard collections book. View toggle (MTD / Lifetime / Custom)
        applies to this tab.
      </>
    ),
  },
  {
    value: "recovery",
    label: "Recovery",
    tip: (
      <>
        <strong>Recovery.</strong> Cancelled (churned) in Zoho{" "}
        <em>and still owe money</em>. These need recovery work.
      </>
    ),
  },
  {
    value: "completed",
    label: "Completed",
    tip: (
      <>
        <strong>Completed.</strong> Subscription has expired — rider paid out
        their full plan. Ready for completion certificate.
      </>
    ),
  },
  {
    value: "all",
    label: "All",
    tip: (
      <>
        <strong>All riders.</strong> Active + Recovery + Completed + edge
        cases. Useful for a top-line total.
      </>
    ),
  },
];

export function ReportControls({
  view,
  status,
  fleet,
  agency,
  windowStart,
  windowEnd,
}: {
  view: ReportView;
  status: ReportStatus;
  fleet: ReportFleet;
  agency: string;
  windowStart: string;
  windowEnd: string;
}) {
  const router = useRouter();
  const search = useSearchParams();
  // Canonical agencies — keep in sync with backend ALLOWED_AGENCIES.
  const agencyOptions = ["Hortta", "TSAC"];

  const setParams = (changes: Record<string, string | null>) => {
    const params = new URLSearchParams(search.toString());
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === "") params.delete(k);
      else params.set(k, v);
    }
    router.push(`?${params.toString()}`);
  };

  const downloadParams = {
    view,
    status,
    fleet,
    ...(agency && agency !== "All" ? { agency } : {}),
    ...(view === "custom"
      ? { window_start: windowStart, window_end: windowEnd }
      : {}),
  };

  return (
    <div className="flex flex-col gap-3 items-end">
      <div className="flex flex-wrap items-center gap-3 justify-end">
        <Segmented
          label="View"
          tip={
            <>
              <strong>View</strong> picks the time window. MTD is this month,
              Lifetime is all-time, Custom lets you pick. Applies to Active
              status only.
            </>
          }
          options={VIEWS}
          current={view}
          onChange={(v) => setParams({ view: v })}
        />
        <Segmented
          label="Status"
          tip={
            <>
              <strong>Status</strong> swaps between rider lifecycle stages.
              Active = currently subscribed, Recovery = churned with debt,
              Completed = fully paid out.
            </>
          }
          options={STATUSES}
          current={status}
          onChange={(v) => setParams({ status: v })}
        />
        <Segmented
          label="Fleet"
          tip="Filter by fleet. Wahu = standard riders; TSA = flagged on the subscription."
          options={FLEETS.map((f) => ({
            value: f.value,
            label: f.value,
            tip: f.tip,
          }))}
          current={fleet}
          onChange={(v) => setParams({ fleet: v })}
        />

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
            Agency
          </span>
          <Tooltip
            content={
              <>
                <strong>Agency</strong> filters to riders assigned to a 3rd-party
                collections agency. Assign or unassign individual riders from
                the agency column in the rider table.
              </>
            }
          />
          <select
            value={agency}
            onChange={(e) => setParams({ agency: e.target.value === "All" ? null : e.target.value })}
            className="text-xs bg-canvas-raised border border-canvas-line rounded-md px-2 py-1
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          >
            <option value="All">All</option>
            {agencyOptions.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>

        <MemoButton
          view={view}
          status={status}
          fleet={fleet}
          agency={agency}
          windowStart={windowStart}
          windowEnd={windowEnd}
        />

        <a
          href={api.collectionsDownloadUrl(downloadParams)}
          className="btn-primary"
        >
          <Download className="w-3.5 h-3.5" />
          Download xlsx
        </a>
      </div>

      {view === "custom" && (
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
      )}
    </div>
  );
}

function Segmented<T extends string>({
  label,
  tip,
  options,
  current,
  onChange,
}: {
  label: string;
  tip?: React.ReactNode;
  options: { value: T; label: string; tip?: React.ReactNode }[];
  current: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </span>
      {tip && (
        <Tooltip content={tip} side="bottom" align="start" />
      )}
      <div className="flex gap-0.5 bg-canvas-sunken p-0.5 rounded-md ml-1">
        {options.map((o) => (
          <span key={o.value} className="relative inline-flex items-center">
            <button
              type="button"
              onClick={() => onChange(o.value)}
              className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                current === o.value
                  ? "bg-canvas-raised text-ink shadow-card"
                  : "text-ink-muted hover:text-ink"
              }`}
              title={typeof o.tip === "string" ? o.tip : undefined}
            >
              {o.label}
            </button>
            {o.tip && typeof o.tip !== "string" && (
              <span className="absolute -right-1 -top-1">
                <Tooltip content={o.tip} side="bottom" align="end" />
              </span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}
