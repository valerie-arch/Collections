"use client";

import { useState, useTransition } from "react";
import { FileText, X, Download, FileDown } from "lucide-react";
import { api, ReportView, ReportStatus, ReportFleet } from "@/lib/api";

export function MemoButton({
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
  const [open, setOpen] = useState(false);
  const [memo, setMemo] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const params = {
    view,
    status,
    fleet,
    ...(agency && agency !== "All" ? { agency } : {}),
    ...(view === "custom"
      ? { window_start: windowStart, window_end: windowEnd }
      : {}),
  };

  const openModal = () => {
    setOpen(true);
    setMemo(null);
    setErr(null);
    start(async () => {
      try {
        const res = await api.collectionsMemo(params);
        setMemo(res.memo_text);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "memo generation failed");
      }
    });
  };

  return (
    <>
      <button onClick={openModal} className="btn-secondary">
        <FileText className="w-3.5 h-3.5" />
        Create memo
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 bg-ink/40 backdrop-blur-sm flex items-center justify-center p-6"
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-canvas-raised rounded-xl shadow-floating max-w-3xl w-full max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-canvas-line gap-4">
              <div className="min-w-0">
                <h2 className="text-lg font-display tracking-tightest text-ink">
                  Collections performance memo
                </h2>
                <p className="text-xs text-ink-fade mt-0.5">
                  Preview the brief, then download for distribution.
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <a
                  href={api.collectionsMemoPdfUrl(params)}
                  className="btn-secondary"
                  download
                >
                  <Download className="w-3.5 h-3.5" />
                  PDF
                </a>
                <a
                  href={api.collectionsMemoDocxUrl(params)}
                  className="btn-primary"
                  download
                >
                  <FileDown className="w-3.5 h-3.5" />
                  Google Doc (.docx)
                </a>
                <button
                  onClick={() => setOpen(false)}
                  className="p-1.5 rounded-md hover:bg-canvas-sunken"
                  aria-label="Close"
                >
                  <X className="w-4 h-4 text-ink-muted" />
                </button>
              </div>
            </div>
            <div className="overflow-auto px-6 py-5 flex-1">
              {pending && <div className="text-sm text-ink-fade">Building memo…</div>}
              {err && <div className="text-sm text-clay-600">{err}</div>}
              {memo && (
                <pre className="whitespace-pre-wrap text-sm font-mono text-ink leading-relaxed">
                  {memo}
                </pre>
              )}
            </div>
            <div className="px-6 py-3 border-t border-canvas-line text-[11px] text-ink-fade">
              The <strong>.docx</strong> opens in Google Docs via File → Open → Upload, or
              double-click locally to open in Word/Pages. PDF is print-ready.
            </div>
          </div>
        </div>
      )}
    </>
  );
}
