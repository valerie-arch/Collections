"use client";

import { useState, useTransition } from "react";
import { RefreshCw, CheckCircle2, AlertCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

/**
 * One-click sync of every Drive source the platform reads:
 *   - Zoho invoices (incl. subscriptions)
 *   - Rider payments (MoMo / bank / cash, recurses subfolders)
 *
 * Both backends are idempotent: only files whose Drive modifiedTime
 * has changed since the last sync are re-downloaded. State is kept in
 * .sync_state.json files alongside the cached payloads.
 */
export function SyncDriveButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const runSync = () => {
    setMsg(null);
    start(async () => {
      try {
        const [inv, pay] = await Promise.all([
          api.driveSync(),
          api.paymentsSync(),
        ]);
        const parts: string[] = [];
        parts.push(`Invoices: ${inv.downloaded.length} new, ${inv.skipped.length} up-to-date`);
        if (inv.subscriptions_synced != null) {
          parts.push(`Subscriptions: ${inv.subscriptions_synced} synced`);
        }
        parts.push(`Payments: ${pay.downloaded.length} new, ${pay.skipped.length} up-to-date`);
        setMsg({ kind: "ok", text: parts.join(" · ") });
        router.refresh();
      } catch (e) {
        setMsg({
          kind: "err",
          text: e instanceof Error ? e.message : "sync failed",
        });
      }
    });
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        onClick={runSync}
        disabled={pending}
        className="btn-primary inline-flex items-center gap-2"
      >
        <RefreshCw className={`w-3.5 h-3.5 ${pending ? "animate-spin" : ""}`} />
        {pending ? "Syncing…" : "Sync Drive"}
      </button>
      {msg && (
        <div
          className={`text-[11px] max-w-md text-right inline-flex items-start gap-1.5 ${
            msg.kind === "ok" ? "text-moss-600" : "text-clay-600"
          }`}
        >
          {msg.kind === "ok"
            ? <CheckCircle2 className="w-3 h-3 mt-0.5 shrink-0" />
            : <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" />}
          <span>{msg.text}</span>
        </div>
      )}
    </div>
  );
}
