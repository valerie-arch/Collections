"use client";

import { useState, useTransition } from "react";
import {
  RefreshCw,
  Download,
  DownloadCloud,
  AlertCircle,
  CheckCircle2,
  Send,
} from "lucide-react";
import { api, PaymentReconcileResult } from "@/lib/api";

const CHANNEL_LABEL: Record<string, string> = {
  mtn: "MTN MoMo",
  telecel: "Telecel",
  hero: "Hero",
  bank: "Bank",
  cash: "Cash",
  bolt_deduction: "Bolt deduction",
  unknown: "Unknown",
};

const METHOD_LABEL: Record<string, string> = {
  customer_id: "Customer ID",
  name_overlap: "Name match",
  none: "No match",
};

function fmtGhs(n: number) {
  return `GHS ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function PaymentsClient({ defaultCutoff }: { defaultCutoff: string }) {
  const [cutoff, setCutoff] = useState(defaultCutoff);
  const [result, setResult] = useState<PaymentReconcileResult | null>(null);
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ kind: "ok" | "err" | "info"; text: string } | null>(null);

  const runSync = () => {
    setMsg(null);
    start(async () => {
      try {
        const r = await api.paymentsSync();
        setMsg({
          kind: "ok",
          text: `Drive sync: ${r.downloaded.length} downloaded, ${r.skipped.length} unchanged (${r.total} total).`,
        });
      } catch (e) {
        setMsg({ kind: "err", text: e instanceof Error ? e.message : "Sync failed" });
      }
    });
  };

  const runReconcile = () => {
    setMsg(null);
    start(async () => {
      try {
        const r = await api.paymentsReconcile(cutoff);
        setResult(r);
        setMsg({
          kind: "info",
          text: `${r.matched.length} matched · ${r.unmatched.length} unmatched · ${r.in_scope_payments} of ${r.total_payments} payments in scope.`,
        });
      } catch (e) {
        setMsg({ kind: "err", text: e instanceof Error ? e.message : "Reconcile failed" });
      }
    });
  };

  const pushSuspense = () => {
    if (!result || result.unmatched.length === 0) return;
    if (!confirm(`Push ${result.unmatched.length} unmatched payment(s) to Suspense?`)) return;
    setMsg(null);
    start(async () => {
      try {
        const r = await api.paymentsPushSuspense(cutoff);
        setMsg({
          kind: "ok",
          text: `Pushed ${r.pushed} of ${r.total_unmatched} to Suspense (${r.skipped} skipped).`,
        });
      } catch (e) {
        setMsg({ kind: "err", text: e instanceof Error ? e.message : "Push failed" });
      }
    });
  };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <label className="text-xs uppercase tracking-wider text-ink-fade font-medium">
            Cutoff (only payments on or after)
          </label>
          <input
            type="date"
            value={cutoff}
            onChange={(e) => setCutoff(e.target.value)}
            className="px-3 py-1.5 text-sm bg-canvas-raised border border-canvas-line rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button onClick={runSync} disabled={pending} className="btn-secondary">
            <DownloadCloud className={`w-3.5 h-3.5 ${pending ? "animate-pulse" : ""}`} />
            Sync Drive
          </button>
          <button onClick={runReconcile} disabled={pending} className="btn-primary">
            <RefreshCw className={`w-3.5 h-3.5 ${pending ? "animate-spin" : ""}`} />
            Reconcile
          </button>
          {result && result.matched.length > 0 && (
            <a
              href={api.paymentsScheduleUrl(cutoff)}
              className="btn-secondary"
              target="_blank"
              rel="noreferrer"
            >
              <Download className="w-3.5 h-3.5" />
              Download Zoho schedule
            </a>
          )}
          {result && result.unmatched.length > 0 && (
            <button onClick={pushSuspense} disabled={pending} className="btn-secondary">
              <Send className="w-3.5 h-3.5" />
              Push {result.unmatched.length} to Suspense
            </button>
          )}
        </div>
      </div>

      {msg && (
        <div
          className={`mb-4 rounded-lg border px-3 py-2 text-xs ${
            msg.kind === "ok"
              ? "border-moss-500/30 bg-moss-500/5 text-moss-600"
              : msg.kind === "err"
                ? "border-clay-500/30 bg-clay-500/10 text-clay-600"
                : "border-canvas-line bg-canvas-raised text-ink-muted"
          }`}
        >
          {msg.text}
        </div>
      )}

      {!result ? (
        <div className="surface p-12 text-center">
          <div className="text-sm font-medium text-ink mb-2">
            How this works
          </div>
          <ol className="text-xs text-ink-muted max-w-xl mx-auto text-left list-decimal pl-5 space-y-1.5 mb-6">
            <li>
              Click <strong>Sync Drive</strong> to pull rider payment files
              from the configured Drive folder.
            </li>
            <li>
              Click <strong>Reconcile</strong> to match each payment to a rider
              and allocate it to their oldest open invoice.
            </li>
            <li>
              Download the <strong>Zoho upload schedule</strong> — an Excel
              file Finance can drop straight into Zoho's payment import.
            </li>
            <li>
              Anything that couldn't be matched goes to <strong>Suspense</strong>
              {" "}for manual review.
            </li>
          </ol>
          <button onClick={runReconcile} disabled={pending} className="btn-primary">
            <RefreshCw className={`w-3.5 h-3.5 ${pending ? "animate-spin" : ""}`} />
            Run reconciliation now
          </button>
        </div>
      ) : (
        <>
          {/* Summary tiles */}
          <div className="grid gap-4 md:grid-cols-4 mb-6">
            <Stat
              label="In-scope payments"
              value={result.in_scope_payments.toLocaleString()}
              hint={`of ${result.total_payments} total since cutoff`}
            />
            <Stat
              label="Matched"
              value={result.matched.length.toLocaleString()}
              hint={fmtGhs(result.total_matched_amount_ghs)}
              tone="moss"
            />
            <Stat
              label="Unmatched"
              value={result.unmatched.length.toLocaleString()}
              hint={fmtGhs(result.total_unmatched_amount_ghs)}
              tone="warning"
            />
            <Stat
              label="Match rate"
              value={
                result.in_scope_payments > 0
                  ? `${((result.matched.length / result.in_scope_payments) * 100).toFixed(1)}%`
                  : "—"
              }
              hint={`${result.riders_in_master.toLocaleString()} riders in master`}
            />
          </div>

          {/* Matched table */}
          <section className="surface overflow-hidden mb-8">
            <div className="px-5 py-3 border-b border-canvas-line flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-moss-600" />
              <h3 className="text-base font-display tracking-tightest">
                Matched ({result.matched.length})
              </h3>
              <span className="ml-auto text-xs text-ink-fade">
                Will appear in the Zoho upload schedule
              </span>
            </div>
            <div className="overflow-x-auto max-h-[500px]">
              <table className="data-grid">
                <thead className="sticky top-0">
                  <tr>
                    <th>Date</th>
                    <th>Sender / Narration</th>
                    <th>Channel</th>
                    <th>Amount</th>
                    <th>Matched rider</th>
                    <th>Invoice</th>
                    <th>Applied</th>
                    <th>Method</th>
                  </tr>
                </thead>
                <tbody>
                  {result.matched.length === 0 && (
                    <tr>
                      <td colSpan={8} className="text-center text-ink-fade py-10">
                        No matched payments.
                      </td>
                    </tr>
                  )}
                  {result.matched.map((m) =>
                    (m.allocations.length === 0 ? [{ inv: null }] : m.allocations).map((a: any, i) => (
                      <tr key={`${m.source_file}-${m.line_no}-${i}`}>
                        {i === 0 && (
                          <>
                            <td rowSpan={Math.max(m.allocations.length, 1)} className="font-mono text-xs">
                              {m.payment_date ?? "—"}
                            </td>
                            <td rowSpan={Math.max(m.allocations.length, 1)}>
                              <div className="text-sm font-medium text-ink">{m.raw_name || "—"}</div>
                              {m.msisdn && (
                                <div className="text-[10px] text-ink-fade font-mono">{m.msisdn}</div>
                              )}
                              {m.reference && (
                                <div className="text-[10px] text-ink-fade font-mono">{m.reference}</div>
                              )}
                            </td>
                            <td rowSpan={Math.max(m.allocations.length, 1)}>
                              <span className="badge-muted">{CHANNEL_LABEL[m.channel] ?? m.channel}</span>
                            </td>
                            <td rowSpan={Math.max(m.allocations.length, 1)} className="font-mono text-sm text-moss-600">
                              {fmtGhs(m.amount_ghs)}
                              {m.unapplied_ghs > 0 && (
                                <div className="text-[10px] text-clay-600">
                                  {fmtGhs(m.unapplied_ghs)} overflow
                                </div>
                              )}
                            </td>
                            <td rowSpan={Math.max(m.allocations.length, 1)}>
                              <div className="text-sm font-medium text-ink">{m.rider_name}</div>
                              <div className="text-[10px] font-mono text-ink-fade">{m.rider_id}</div>
                            </td>
                          </>
                        )}
                        <td className="font-mono text-xs">
                          {a.inv === null ? <span className="text-ink-fade">no open invoice</span> : a.invoice_number}
                        </td>
                        <td className="font-mono text-sm">
                          {a.inv === null ? "—" : fmtGhs(a.applied_ghs)}
                        </td>
                        {i === 0 && (
                          <td rowSpan={Math.max(m.allocations.length, 1)}>
                            <span className="badge-muted">{METHOD_LABEL[m.method] ?? m.method}</span>
                            <div className="text-[10px] text-ink-fade font-mono mt-0.5">
                              {(m.confidence * 100).toFixed(0)}%
                            </div>
                          </td>
                        )}
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* Unmatched table */}
          <section className="surface overflow-hidden">
            <div className="px-5 py-3 border-b border-canvas-line flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-accent-700" />
              <h3 className="text-base font-display tracking-tightest">
                Unmatched ({result.unmatched.length})
              </h3>
              <span className="ml-auto text-xs text-ink-fade">
                Pushed to Suspense for manual matching
              </span>
            </div>
            <div className="overflow-x-auto max-h-[500px]">
              <table className="data-grid">
                <thead className="sticky top-0">
                  <tr>
                    <th>Date</th>
                    <th>Sender / Narration</th>
                    <th>Channel</th>
                    <th>Amount</th>
                    <th>Phone</th>
                    <th>Best-guess rider</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {result.unmatched.length === 0 && (
                    <tr>
                      <td colSpan={7} className="text-center text-ink-fade py-10">
                        Nothing unmatched.
                      </td>
                    </tr>
                  )}
                  {result.unmatched.map((u, i) => (
                    <tr key={`${u.source_file}-${u.line_no}-${i}`}>
                      <td className="font-mono text-xs">{u.payment_date ?? "—"}</td>
                      <td>
                        <div className="text-sm font-medium text-ink">{u.raw_name || "—"}</div>
                        {u.reference && (
                          <div className="text-[10px] text-ink-fade font-mono">{u.reference}</div>
                        )}
                      </td>
                      <td>
                        <span className="badge-muted">{CHANNEL_LABEL[u.channel] ?? u.channel}</span>
                      </td>
                      <td className="font-mono text-sm text-clay-600">{fmtGhs(u.amount_ghs)}</td>
                      <td className="font-mono text-xs">{u.msisdn || "—"}</td>
                      <td>
                        {u.best_guess_rider_name ? (
                          <>
                            <div className="text-xs text-ink-muted">{u.best_guess_rider_name}</div>
                            <div className="text-[10px] text-ink-fade font-mono">
                              {(u.best_guess_confidence * 100).toFixed(0)}% — below threshold
                            </div>
                          </>
                        ) : (
                          <span className="text-ink-fade text-xs">none</span>
                        )}
                      </td>
                      <td className="text-[11px] text-ink-fade">{u.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}

function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "warning" | "moss";
}) {
  const color =
    tone === "warning" ? "text-accent-700" : tone === "moss" ? "text-moss-600" : "text-ink";
  return (
    <div className="surface p-5">
      <div className="text-[11px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </div>
      <div className={`mt-1.5 text-2xl font-display tracking-tightest ${color}`}>{value}</div>
      {hint && <div className="text-xs text-ink-fade mt-1">{hint}</div>}
    </div>
  );
}
