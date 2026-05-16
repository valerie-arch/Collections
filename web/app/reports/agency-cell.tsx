"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Building2, X } from "lucide-react";
import { api } from "@/lib/api";

const AGENCIES = ["Hortta", "TSAC"] as const;
type Agency = (typeof AGENCIES)[number];

export function AgencyCell({
  customerId,
  customerName,
  currentAgency,
  assignedAt,
}: {
  customerId: string;
  customerName: string;
  currentAgency: string | null;
  assignedAt?: string | null;
  knownAgencies?: string[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [agency, setAgency] = useState<Agency>(
    (AGENCIES as readonly string[]).includes(currentAgency ?? "")
      ? (currentAgency as Agency)
      : "Hortta",
  );
  const [note, setNote] = useState("");
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);

  const close = () => {
    setOpen(false);
    setErr(null);
  };

  const assign = () => {
    setErr(null);
    start(async () => {
      try {
        await api.assignAgency(customerId, agency, note.trim() || undefined);
        close();
        router.refresh();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "assign failed");
      }
    });
  };

  const unassign = () => {
    start(async () => {
      try {
        await api.unassignAgency(customerId);
        close();
        router.refresh();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "unassign failed");
      }
    });
  };

  return (
    <>
      {currentAgency ? (
        <button
          onClick={() => setOpen(true)}
          className="inline-flex flex-col items-start gap-0 px-2 py-1 rounded-md bg-accent-50 text-accent-700
                     hover:bg-accent-100 transition-colors"
          title={assignedAt ? `Assigned ${assignedAt.slice(0, 10)}` : undefined}
        >
          <span className="inline-flex items-center gap-1 text-xs font-medium">
            <Building2 className="w-3 h-3" />
            {currentAgency}
          </span>
          {assignedAt && (
            <span className="text-[10px] text-accent-700/70 font-mono">
              {assignedAt.slice(0, 10)}
            </span>
          )}
        </button>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="text-xs text-ink-fade hover:text-accent-600 inline-flex items-center gap-1"
        >
          <Building2 className="w-3 h-3" /> Assign
        </button>
      )}

      {open && (
        <div
          className="fixed inset-0 z-50 bg-ink/40 backdrop-blur-sm flex items-center justify-center p-6"
          onClick={close}
        >
          <div
            className="bg-canvas-raised rounded-xl shadow-floating w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-canvas-line">
              <div>
                <h3 className="text-base font-display tracking-tightest">
                  {currentAgency ? "Reassign agency" : "Assign collections agency"}
                </h3>
                <p className="text-xs text-ink-fade mt-0.5">
                  {customerName} ({customerId})
                </p>
              </div>
              <button onClick={close} className="p-1 hover:bg-canvas-sunken rounded">
                <X className="w-4 h-4 text-ink-muted" />
              </button>
            </div>

            <div className="px-5 py-4 space-y-3">
              <div>
                <label className="text-[10px] uppercase tracking-wider text-ink-fade font-medium block mb-1">
                  Agency
                </label>
                <select
                  value={agency}
                  onChange={(e) => setAgency(e.target.value as Agency)}
                  className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                             focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
                >
                  {AGENCIES.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[10px] uppercase tracking-wider text-ink-fade font-medium block mb-1">
                  Note (optional)
                </label>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={2}
                  className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                             focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
                />
              </div>

              {err && <div className="text-xs text-clay-600">{err}</div>}
            </div>

            <div className="px-5 py-3 border-t border-canvas-line flex items-center justify-between">
              {currentAgency ? (
                <button
                  onClick={unassign}
                  disabled={pending}
                  className="text-xs text-clay-600 hover:text-clay-500"
                >
                  Remove assignment
                </button>
              ) : (
                <span />
              )}
              <div className="flex gap-2">
                <button onClick={close} className="btn-secondary">
                  Cancel
                </button>
                <button onClick={assign} disabled={pending} className="btn-primary">
                  {pending ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
