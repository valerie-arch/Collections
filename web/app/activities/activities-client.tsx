"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Search, Send, RefreshCw, X, Plus, Trash2, History, FileText,
} from "lucide-react";
import {
  api,
  ActivityAction,
  ActivityItem,
  Recommendation,
} from "@/lib/api";

const ACTIONS: { value: ActivityAction; label: string }[] = [
  { value: "phone_call", label: "Phone call" },
  { value: "immobilisation_request", label: "Immobilisation request" },
  { value: "call_to_guarantor", label: "Call to guarantor" },
  { value: "remobilisation_request", label: "Remobilisation request" },
  { value: "house_visit", label: "House visit" },
  { value: "ebike_recovery", label: "eBike recovery" },
  { value: "legal_action_taken", label: "Legal action taken" },
  { value: "legal_action_update", label: "Legal action update" },
  { value: "to_be_written_off", label: "To be written off" },
  { value: "other", label: "Other" },
];

const ACTION_LABEL: Record<string, string> = Object.fromEntries(
  ACTIONS.map((a) => [a.value, a.label]),
);

const AGENCIES = ["All", "Hortta", "TSAC", "Unassigned"];
const BANDS = ["All", "A", "B", "C", "D", "E"];

const SEV_BADGE: Record<string, string> = {
  critical: "badge-danger",
  warning: "badge-warning",
  info: "badge-muted",
};

const BAND_TONE: Record<string, string> = {
  A: "bg-moss-500/10 text-moss-600",
  B: "bg-moss-400/10 text-moss-500",
  C: "bg-accent-500/10 text-accent-700",
  D: "bg-accent-600/15 text-accent-700",
  E: "bg-clay-500/10 text-clay-600",
};

export function ActivitiesClient({
  initialRecommendations,
  agencyFilter,
  bandFilter,
  searchQuery,
}: {
  initialRecommendations: Recommendation[];
  agencyFilter: string;
  bandFilter: string;
  searchQuery: string;
}) {
  const router = useRouter();
  const search = useSearchParams();
  const [q, setQ] = useState<string>(searchQuery ?? "");
  const [drilldown, setDrilldown] = useState<Recommendation | null>(null);
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const setParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(search.toString());
    if (value === null || value === "" || value === "All") params.delete(key);
    else params.set(key, value);
    router.push(`?${params.toString()}`);
  };

  // Debounce search to URL
  useEffect(() => {
    const t = setTimeout(() => {
      const trimmed = (q ?? "").trim();
      if (trimmed === (searchQuery ?? "").trim()) return;
      setParam("q", trimmed);
    }, 300);
    return () => clearTimeout(t);
  }, [q, searchQuery]);

  const filtered = useMemo(() => {
    let rows = initialRecommendations;
    if (bandFilter && bandFilter !== "All") {
      rows = rows.filter((r) => r.risk_band === bandFilter);
    }
    const needle = (q ?? "").trim().toLowerCase();
    if (needle) {
      rows = rows.filter(
        (r) =>
          (r.customer_name ?? "").toLowerCase().includes(needle) ||
          (r.customer_id ?? "").toLowerCase().includes(needle),
      );
    }
    return rows;
  }, [initialRecommendations, bandFilter, q]);

  const runDaily = () => {
    setMsg(null);
    start(async () => {
      try {
        const r = await api.runDailyActivitiesReport();
        setMsg({
          kind: r.drive.uploaded ? "ok" : "err",
          text: r.drive.uploaded
            ? `Built ${r.activities_count} activities (${r.unique_riders} riders) → archived to Google Drive.`
            : `Built xlsx but Drive upload failed: ${r.drive.reason}`,
        });
      } catch (e) {
        setMsg({ kind: "err", text: e instanceof Error ? e.message : "run failed" });
      }
    });
  };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-fade" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search rider name or ID…"
              className="pl-8 pr-3 py-1.5 text-sm bg-canvas-raised border border-canvas-line rounded-md w-72
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
            />
          </div>

          <FilterChips
            label="Agency"
            options={AGENCIES}
            current={agencyFilter}
            onChange={(v) => setParam("agency", v)}
          />
          <FilterChips
            label="Risk band"
            options={BANDS}
            current={bandFilter}
            onChange={(v) => setParam("band", v)}
          />
        </div>

        <div className="flex items-center gap-2">
          {msg && (
            <span
              className={`text-xs ${msg.kind === "ok" ? "text-moss-600" : "text-clay-600"}`}
            >
              {msg.text}
            </span>
          )}
          <button onClick={runDaily} disabled={pending} className="btn-secondary">
            <Send className={`w-3.5 h-3.5 ${pending ? "animate-pulse" : ""}`} />
            {pending ? "Running…" : "Archive today to Drive"}
          </button>
          <button onClick={() => router.refresh()} className="btn-secondary">
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        </div>
      </div>

      <div className="mb-3 text-xs text-ink-fade">
        Showing <strong>{filtered.length}</strong> of{" "}
        {initialRecommendations.length} riders with outstanding balance
      </div>

      <div className="surface overflow-hidden">
        <div className="overflow-x-auto max-h-[700px]">
          <table className="data-grid">
            <thead className="sticky top-0">
              <tr>
                <th>Rider</th>
                <th>Band</th>
                <th>Open</th>
                <th>Oldest</th>
                <th>Outstanding</th>
                <th>Agency</th>
                <th>Recommended action</th>
                <th>Last activity</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-center text-ink-fade py-10">
                    No riders match these filters.
                  </td>
                </tr>
              )}
              {filtered.map((r) => (
                <tr
                  key={r.customer_id}
                  onClick={() => setDrilldown(r)}
                  className="cursor-pointer hover:bg-canvas-sunken/40 transition-colors"
                >
                  <td>
                    <div className="text-sm font-medium text-ink">
                      {r.customer_name}
                    </div>
                    <div className="text-[10px] font-mono text-ink-fade">
                      {r.customer_id}
                    </div>
                  </td>
                  <td>
                    <span
                      className={`inline-flex items-center justify-center w-7 h-7 rounded-md text-xs font-semibold ${BAND_TONE[r.risk_band] ?? ""}`}
                    >
                      {r.risk_band}
                    </span>
                  </td>
                  <td className="font-mono text-sm">{r.open_invoice_count}</td>
                  <td className="font-mono text-sm">
                    {r.oldest_open_days}
                    <span className="text-ink-fade text-[10px] ml-0.5">d</span>
                  </td>
                  <td className="font-mono text-sm text-clay-600">
                    GHS{" "}
                    {r.outstanding_ghs.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                    })}
                  </td>
                  <td className="text-xs">
                    {r.agency ? (
                      <div>
                        <span className="badge-warning">{r.agency}</span>
                        {r.agency_assigned_at && (
                          <div className="text-[10px] text-ink-fade font-mono mt-0.5">
                            {r.agency_assigned_at.slice(0, 10)}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-ink-fade">—</span>
                    )}
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className={SEV_BADGE[r.severity] ?? "badge-muted"}>
                        {r.severity}
                      </span>
                      <span className="text-sm font-medium text-ink">
                        {ACTION_LABEL[r.recommended_action] ?? r.recommended_action}
                      </span>
                    </div>
                    <div className="text-[11px] text-ink-fade mt-0.5 max-w-md">
                      {r.rationale}
                    </div>
                  </td>
                  <td className="text-xs">
                    {r.last_activity_at ? (
                      <div>
                        <div className="text-ink-muted">
                          {ACTION_LABEL[r.last_activity_action ?? ""] ?? r.last_activity_action}
                        </div>
                        <div className="text-[10px] text-ink-fade font-mono">
                          {r.last_activity_at.slice(0, 10)}
                        </div>
                      </div>
                    ) : (
                      <span className="text-ink-fade">never</span>
                    )}
                  </td>
                  <td>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setDrilldown(r);
                      }}
                      className="text-xs text-accent-700 hover:text-accent-600 inline-flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> Log
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {drilldown && (
        <RiderModal
          recommendation={drilldown}
          onClose={() => setDrilldown(null)}
          onLogged={() => {
            setDrilldown(null);
            router.refresh();
          }}
        />
      )}
    </>
  );
}

function FilterChips({
  label,
  options,
  current,
  onChange,
}: {
  label: string;
  options: string[];
  current: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
        {label}
      </span>
      <div className="flex gap-0.5 bg-canvas-sunken p-0.5 rounded-md">
        {options.map((o) => (
          <button
            key={o}
            onClick={() => onChange(o)}
            className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
              current === o
                ? "bg-canvas-raised text-ink shadow-card"
                : "text-ink-muted hover:text-ink"
            }`}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}

function RiderModal({
  recommendation,
  onClose,
  onLogged,
}: {
  recommendation: Recommendation;
  onClose: () => void;
  onLogged: () => void;
}) {
  const r = recommendation;
  const [history, setHistory] = useState<ActivityItem[] | null>(null);
  const [historyErr, setHistoryErr] = useState<string | null>(null);
  const [form, setForm] = useState({
    action:
      r.recommended_action !== "no_action"
        ? (r.recommended_action as ActivityAction)
        : ("phone_call" as ActivityAction),
    note: "",
  });
  const [saving, startSave] = useTransition();
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .listActivities({ customer_id: r.customer_id })
      .then((d) => setHistory(d.items))
      .catch((e) =>
        setHistoryErr(e instanceof Error ? e.message : "load failed"),
      );
  }, [r.customer_id]);

  const save = () => {
    setSaveErr(null);
    if (!form.note.trim()) {
      setSaveErr("Note is required — every action must be documented");
      return;
    }
    startSave(async () => {
      try {
        await api.createActivity({
          customer_id: r.customer_id,
          customer_name: r.customer_name,
          action: form.action,
          note: form.note.trim(),
        });
        onLogged();
      } catch (e) {
        setSaveErr(e instanceof Error ? e.message : "log failed");
      }
    });
  };

  const deleteActivity = (id: string) => {
    if (!confirm("Delete this activity?")) return;
    api.deleteActivity(id).then(() => {
      setHistory((cur) => (cur ?? []).filter((a) => a.id !== id));
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-ink/40 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="bg-canvas-raised rounded-xl shadow-floating w-full max-w-3xl max-h-[88vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-canvas-line gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-display tracking-tightest text-ink">
              {r.customer_name}
            </h2>
            <div className="text-xs text-ink-fade font-mono mt-0.5">
              {r.customer_id}
            </div>
            <div className="flex flex-wrap gap-3 mt-2 text-xs">
              <span>
                <span className="text-ink-fade">Band:</span>{" "}
                <span
                  className={`inline-flex items-center justify-center w-6 h-6 rounded text-xs font-semibold ${BAND_TONE[r.risk_band] ?? ""}`}
                >
                  {r.risk_band}
                </span>
              </span>
              <span>
                <span className="text-ink-fade">Outstanding:</span>{" "}
                <span className="font-mono text-clay-600">
                  GHS{" "}
                  {r.outstanding_ghs.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                  })}
                </span>
              </span>
              <span>
                <span className="text-ink-fade">Oldest open:</span>{" "}
                <span className="font-mono">{r.oldest_open_days}d</span>
              </span>
              <span>
                <span className="text-ink-fade">Open inv:</span>{" "}
                <span className="font-mono">{r.open_invoice_count}</span>
              </span>
              {r.agency && (
                <span>
                  <span className="text-ink-fade">Agency:</span>{" "}
                  <span className="badge-warning">{r.agency}</span>
                  {r.agency_assigned_at && (
                    <span className="text-ink-fade font-mono ml-1">
                      ({r.agency_assigned_at.slice(0, 10)})
                    </span>
                  )}
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-canvas-sunken rounded">
            <X className="w-4 h-4 text-ink-muted" />
          </button>
        </div>

        {/* SOP recommendation */}
        <div className="px-6 py-3 bg-canvas-sunken/40 border-b border-canvas-line">
          <div className="flex items-start gap-3">
            <FileText className="w-4 h-4 text-accent-700 mt-0.5 shrink-0" />
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
                  SOP §10 recommendation
                </span>
                <span className={SEV_BADGE[r.severity] ?? "badge-muted"}>
                  {r.severity}
                </span>
                <span className="text-sm font-medium text-accent-700">
                  {ACTION_LABEL[r.recommended_action] ?? r.recommended_action}
                </span>
              </div>
              <div className="text-xs text-ink-muted leading-relaxed">
                {r.rationale}
              </div>
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="overflow-auto flex-1 grid md:grid-cols-2 divide-x divide-canvas-line">
          {/* Log new */}
          <div className="px-6 py-5 space-y-3">
            <h3 className="text-sm font-display tracking-tightest text-ink flex items-center gap-2">
              <Plus className="w-3.5 h-3.5" /> Log new activity
            </h3>
            <Field label="Action">
              <select
                value={form.action}
                onChange={(e) =>
                  setForm({ ...form, action: e.target.value as ActivityAction })
                }
                className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
              >
                {ACTIONS.map((a) => (
                  <option key={a.value} value={a.value}>
                    {a.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Note (required)">
              <textarea
                rows={5}
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
                placeholder="What happened? Outcome? Promise-to-pay date? Next step?"
                className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
              />
            </Field>
            {saveErr && <div className="text-xs text-clay-600">{saveErr}</div>}
            <button
              onClick={save}
              disabled={saving}
              className="btn-primary w-full justify-center"
            >
              {saving ? "Saving…" : "Log activity"}
            </button>
          </div>

          {/* History */}
          <div className="px-6 py-5">
            <h3 className="text-sm font-display tracking-tightest text-ink flex items-center gap-2 mb-3">
              <History className="w-3.5 h-3.5" /> Activity history
              <span className="text-[11px] font-normal text-ink-fade">
                ({history?.length ?? 0})
              </span>
            </h3>
            {historyErr && (
              <div className="text-xs text-clay-600 mb-3">{historyErr}</div>
            )}
            {history === null ? (
              <div className="text-xs text-ink-fade">Loading…</div>
            ) : history.length === 0 ? (
              <div className="text-xs text-ink-fade text-center py-6">
                No prior activity for this rider.
              </div>
            ) : (
              <ul className="space-y-3 max-h-[40vh] overflow-auto pr-1">
                {history.map((a) => (
                  <li key={a.id} className="border-l-2 border-accent-500 pl-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-xs font-medium text-ink">
                          {ACTION_LABEL[a.action] ?? a.action}
                        </div>
                        <div className="text-[10px] text-ink-fade font-mono">
                          {a.created_at.replace("T", " ").slice(0, 16)} ·{" "}
                          {a.actor}
                        </div>
                      </div>
                      <button
                        onClick={() => deleteActivity(a.id)}
                        className="text-ink-fade hover:text-clay-600 shrink-0"
                        title="Delete"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                    <div className="text-xs text-ink-muted mt-1 leading-relaxed">
                      {a.note}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-[10px] uppercase tracking-wider text-ink-fade font-medium block mb-1">
        {label}
      </label>
      {children}
    </div>
  );
}
