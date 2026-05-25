"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, AlertCircle, XCircle, RotateCcw } from "lucide-react";
import { api, PaymentListRow } from "@/lib/api";

function fmtGhs(n: number) {
  return `GHS ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtPct(n: number) {
  return `${(n * 100).toFixed(0)}%`;
}

/**
 * Expanded panel under a payment row. Shows the full reference /
 * narration / source-file metadata, the top-3 rider suggestions for
 * unmatched payments, and accept / not-rider / clear buttons that
 * POST to /api/payments/allocate.
 */
export function AllocationRow({ row }: { row: PaymentListRow }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [pickedRiderId, setPickedRiderId] = useState<string>("");
  const [pickedRiderName, setPickedRiderName] = useState<string>("");
  const [customRiderId, setCustomRiderId] = useState<string>("");
  const [customRiderName, setCustomRiderName] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);

  const sourceFile = row.source_file;
  const lineNo = row.line_no ?? 0;

  const baseMeta = {
    source_file: sourceFile,
    line_no: lineNo,
    sender_name: row.sender_name,
    sender_phone: row.sender_phone,
    amount_ghs: row.amount_ghs,
    payment_date: row.date ?? undefined,
    reference: row.reference,
  };

  const allocate = (rider_id: string, rider_name: string) => {
    if (!rider_id) {
      setErr("Pick a rider first.");
      return;
    }
    setErr(null);
    start(async () => {
      try {
        await api.paymentsAllocate({
          ...baseMeta,
          status: "allocated",
          rider_id,
          rider_name,
        });
        router.refresh();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "allocation failed");
      }
    });
  };

  const markNotRider = () => {
    setErr(null);
    start(async () => {
      try {
        await api.paymentsAllocate({
          ...baseMeta,
          status: "not_rider",
        });
        router.refresh();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "update failed");
      }
    });
  };

  const clearDecision = () => {
    setErr(null);
    start(async () => {
      try {
        await api.paymentsAllocateClear({ source_file: sourceFile, line_no: lineNo });
        router.refresh();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "clear failed");
      }
    });
  };

  const status = row.allocation_status ?? (row.matched ? "auto" : "pending");

  return (
    <div className="bg-canvas-sunken/40 border-t border-canvas-line/40 px-5 py-4 text-xs">
      {/* Always show full payment details */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Meta label="Date" value={row.date ?? "—"} mono />
        <Meta label="Amount" value={fmtGhs(row.amount_ghs)} mono />
        <Meta label="Method" value={row.method || "—"} />
        <Meta label="Channel" value={row.channel || "—"} />
        <Meta label="Sender" value={row.sender_name || "—"} />
        <Meta label="Phone" value={row.sender_phone || "—"} mono />
        <Meta label="Reference" value={row.reference || "—"} mono wrap />
        <Meta label="Txn ID" value={row.txn_id || "—"} mono wrap />
        <Meta label="Source file" value={row.source_file} mono wrap className="col-span-2" />
        {row.narration && (
          <Meta label="Narration" value={row.narration} wrap className="col-span-2" />
        )}
      </div>

      {/* Current allocation state */}
      <div className="mb-4 flex items-center gap-2 flex-wrap text-[11px]">
        {status === "auto" && (
          <span className="inline-flex items-center gap-1 text-moss-600">
            <CheckCircle2 className="w-3 h-3" />
            Auto-matched to <strong>{row.rider_name || row.rider_id}</strong>
          </span>
        )}
        {status === "manually_allocated" && (
          <>
            <span className="inline-flex items-center gap-1 text-moss-600">
              <CheckCircle2 className="w-3 h-3" />
              Manually allocated to <strong>{row.rider_name || row.rider_id}</strong>
            </span>
            {row.decided_by && (
              <span className="text-ink-fade">by {row.decided_by}</span>
            )}
            {row.decided_at && (
              <span className="text-ink-fade font-mono">{row.decided_at.split("T")[0]}</span>
            )}
            <button
              onClick={clearDecision} disabled={pending}
              className="ml-auto inline-flex items-center gap-1 text-ink-muted hover:text-ink"
            >
              <RotateCcw className="w-3 h-3" /> Clear decision
            </button>
          </>
        )}
        {status === "not_rider" && (
          <>
            <span className="inline-flex items-center gap-1 text-clay-600">
              <XCircle className="w-3 h-3" />
              Marked <strong>not a rider payment</strong> — excluded from collections + QB schedule
            </span>
            <button
              onClick={clearDecision} disabled={pending}
              className="ml-auto inline-flex items-center gap-1 text-ink-muted hover:text-ink"
            >
              <RotateCcw className="w-3 h-3" /> Clear decision
            </button>
          </>
        )}
        {status === "pending" && (
          <span className="inline-flex items-center gap-1 text-clay-600">
            <AlertCircle className="w-3 h-3" />
            Unmatched — needs a decision below
          </span>
        )}
      </div>

      {/* Suggestion / decision UI — only when pending */}
      {status === "pending" && (
        <div className="space-y-3">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-2">
              Suggested matches
            </div>
            {(!row.suggestions || row.suggestions.length === 0) ? (
              <div className="text-[11px] text-ink-fade italic">
                No high-confidence suggestions — try the manual rider ID below.
              </div>
            ) : (
              <div className="space-y-1.5">
                {row.suggestions.map((s) => (
                  <div key={s.rider_id}
                       className="flex items-center gap-3 bg-canvas-raised border border-canvas-line/60 rounded px-3 py-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-ink">{s.rider_name}</div>
                      <div className="text-[11px] text-ink-fade">
                        <span className="font-mono">{s.rider_id}</span> ·{" "}
                        <span className="capitalize">{s.reason}</span> ({fmtPct(s.confidence)}) · {s.detail}
                      </div>
                    </div>
                    <button
                      onClick={() => allocate(s.rider_id, s.rider_name)}
                      disabled={pending}
                      className="btn-primary !py-1 !text-[11px]"
                    >
                      Accept
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <details className="text-[11px]">
            <summary className="cursor-pointer text-ink-muted hover:text-ink select-none">
              Pick a different rider
            </summary>
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">
                  Customer ID
                </label>
                <input
                  type="text" value={customRiderId}
                  onChange={(e) => setCustomRiderId(e.target.value)}
                  placeholder="WHR1234"
                  className="border border-canvas-line rounded px-2 py-1.5 font-mono text-[11px]"
                />
              </div>
              <div className="flex-1 min-w-[180px]">
                <label className="block text-[10px] uppercase tracking-wider text-ink-fade font-medium mb-1">
                  Customer name
                </label>
                <input
                  type="text" value={customRiderName}
                  onChange={(e) => setCustomRiderName(e.target.value)}
                  placeholder="optional, for audit"
                  className="w-full border border-canvas-line rounded px-2 py-1.5 text-[11px]"
                />
              </div>
              <button
                onClick={() => allocate(customRiderId.trim(), customRiderName.trim())}
                disabled={pending || !customRiderId.trim()}
                className="btn-primary !py-1 !text-[11px]"
              >
                Allocate
              </button>
            </div>
          </details>

          <div className="pt-2 border-t border-canvas-line/40">
            <button
              onClick={markNotRider}
              disabled={pending}
              className="inline-flex items-center gap-1 text-[11px] text-clay-600 hover:text-clay-700"
            >
              <XCircle className="w-3.5 h-3.5" />
              Not a rider payment (exclude from collections + QB schedule)
            </button>
          </div>
        </div>
      )}

      {err && (
        <div className="mt-3 text-[11px] text-clay-600">{err}</div>
      )}
    </div>
  );
}

function Meta({
  label, value, mono = false, wrap = false, className = "",
}: {
  label: string; value: string;
  mono?: boolean; wrap?: boolean; className?: string;
}) {
  return (
    <div className={className}>
      <div className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </div>
      <div
        className={`mt-0.5 text-[11px] text-ink ${mono ? "font-mono" : ""} ${
          wrap ? "break-all" : "truncate"
        }`}
      >
        {value}
      </div>
    </div>
  );
}
