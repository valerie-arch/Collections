"use client";

import { useEffect, useState, useTransition } from "react";
import { Plus, X, Search, Check, Wallet, Trash2 } from "lucide-react";
import { api, MatchCandidate, SuspenseItem, SuspenseStatus } from "@/lib/api";

const CHANNELS = ["mtn", "telecel", "hero", "cash", "bank", "other"];

const STATUS_LABEL: Record<SuspenseStatus, string> = {
  open: "Open",
  resolved: "Matched to rider",
  booked: "Booked to suspense a/c",
};

export function SuspenseSection() {
  const [items, setItems] = useState<SuspenseItem[]>([]);
  const [counts, setCounts] = useState({ open: 0, resolved: 0, booked: 0 });
  const [statusFilter, setStatusFilter] =
    useState<SuspenseStatus | "all">("open");
  const [showAdd, setShowAdd] = useState(false);
  const [matchOpen, setMatchOpen] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);

  const reload = () =>
    start(async () => {
      try {
        const data = await api.listSuspenseItems(
          statusFilter === "all" ? undefined : statusFilter,
        );
        setItems(data.items);
        setCounts(data.counts);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "load failed");
      }
    });

  useEffect(() => {
    reload();
  }, [statusFilter]);

  return (
    <section>
      <div className="flex items-center justify-end mb-3">
        <button onClick={() => setShowAdd(true)} className="btn-primary">
          <Plus className="w-3.5 h-3.5" />
          Add suspense item
        </button>
      </div>

      <div className="flex gap-2 mb-3">
        {(["open", "resolved", "booked", "all"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1 text-xs font-medium rounded-md ${
              statusFilter === s
                ? "bg-ink text-canvas-raised"
                : "bg-canvas-sunken text-ink-muted hover:text-ink"
            }`}
          >
            {s === "all" ? "all" : STATUS_LABEL[s as SuspenseStatus]}{" "}
            {s !== "all" && `(${counts[s as SuspenseStatus] ?? 0})`}
          </button>
        ))}
      </div>

      {err && (
        <div className="text-xs text-clay-600 mb-3">{err}</div>
      )}

      <div className="surface overflow-hidden">
        <table className="data-grid">
          <thead>
            <tr>
              <th>Received</th>
              <th>Channel</th>
              <th>Reference</th>
              <th>MSISDN</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Resolution</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center text-ink-fade py-8">
                  No suspense items in <em>{statusFilter}</em>.
                </td>
              </tr>
            )}
            {items.map((s) => (
              <tr key={s.id}>
                <td className="text-xs font-mono text-ink-muted">{s.received_at}</td>
                <td className="text-sm">{s.channel}</td>
                <td className="text-xs font-mono text-ink-muted max-w-[12rem] truncate">
                  {s.channel_reference}
                </td>
                <td className="text-xs font-mono text-ink-muted">
                  {s.msisdn ?? "—"}
                </td>
                <td className="font-mono text-sm">
                  GHS{" "}
                  {s.amount_ghs.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                  })}
                </td>
                <td>
                  <span
                    className={`badge-${
                      s.status === "resolved"
                        ? "success"
                        : s.status === "booked"
                        ? "muted"
                        : "warning"
                    }`}
                  >
                    {STATUS_LABEL[s.status] ?? s.status}
                  </span>
                </td>
                <td className="text-xs">
                  {s.resolved_rider_name ? (
                    <>
                      <div className="text-ink">{s.resolved_rider_name}</div>
                      {s.resolved_invoice_number && (
                        <div className="text-ink-fade font-mono">
                          {s.resolved_invoice_number}
                        </div>
                      )}
                    </>
                  ) : (
                    <span className="text-ink-fade">—</span>
                  )}
                </td>
                <td>
                  <div className="flex items-center gap-2">
                    {s.status === "open" && (
                      <>
                        <button
                          onClick={() => setMatchOpen(s.id)}
                          className="text-xs text-accent-700 hover:text-accent-600 inline-flex items-center gap-1"
                        >
                          <Search className="w-3 h-3" /> Match
                        </button>
                        <BookButton id={s.id} onDone={reload} />
                      </>
                    )}
                    {(s.status === "resolved" || s.status === "booked") && (
                      <button
                        onClick={() =>
                          start(async () => {
                            await api.reopenSuspense(s.id);
                            reload();
                          })
                        }
                        className="text-xs text-ink-muted hover:text-ink"
                      >
                        Reopen
                      </button>
                    )}
                    <DeleteButton id={s.id} onDone={reload} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showAdd && (
        <AddSuspenseModal
          onClose={() => setShowAdd(false)}
          onCreated={() => {
            setShowAdd(false);
            reload();
          }}
        />
      )}

      {matchOpen && (
        <MatchModal
          itemId={matchOpen}
          onClose={() => setMatchOpen(null)}
          onResolved={() => {
            setMatchOpen(null);
            reload();
          }}
        />
      )}
    </section>
  );
}

function AddSuspenseModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({
    channel: "mtn",
    channel_reference: "",
    amount_ghs: "",
    received_at: new Date().toISOString().slice(0, 10),
    msisdn: "",
    note: "",
  });
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);

  const submit = () => {
    setErr(null);
    const amount = parseFloat(form.amount_ghs);
    if (!form.channel_reference.trim() || !amount || amount <= 0) {
      setErr("Reference and a positive amount are required");
      return;
    }
    start(async () => {
      try {
        await api.createSuspense({
          channel: form.channel,
          channel_reference: form.channel_reference.trim(),
          amount_ghs: amount,
          received_at: form.received_at,
          msisdn: form.msisdn.trim() || undefined,
          note: form.note.trim() || undefined,
        });
        onCreated();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "create failed");
      }
    });
  };

  return (
    <Modal title="Add suspense payment" onClose={onClose}>
      <div className="px-5 py-4 space-y-3">
        <Field label="Channel">
          <select
            value={form.channel}
            onChange={(e) => setForm({ ...form, channel: e.target.value })}
            className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          >
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Channel reference (txn ID)">
          <input
            value={form.channel_reference}
            onChange={(e) => setForm({ ...form, channel_reference: e.target.value })}
            className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount (GHS)">
            <input
              type="number"
              step="0.01"
              value={form.amount_ghs}
              onChange={(e) => setForm({ ...form, amount_ghs: e.target.value })}
              className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
            />
          </Field>
          <Field label="Received at">
            <input
              type="date"
              value={form.received_at}
              onChange={(e) => setForm({ ...form, received_at: e.target.value })}
              className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
            />
          </Field>
        </div>
        <Field label="MSISDN (optional)">
          <input
            value={form.msisdn}
            onChange={(e) => setForm({ ...form, msisdn: e.target.value })}
            placeholder="0244..."
            className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          />
        </Field>
        <Field label="Note (optional)">
          <textarea
            rows={2}
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
            className="w-full px-3 py-2 bg-canvas-raised border border-canvas-line rounded-md text-sm
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          />
        </Field>
        {err && <div className="text-xs text-clay-600">{err}</div>}
      </div>
      <div className="px-5 py-3 border-t border-canvas-line flex justify-end gap-2">
        <button onClick={onClose} className="btn-secondary">
          Cancel
        </button>
        <button onClick={submit} disabled={pending} className="btn-primary">
          {pending ? "Saving…" : "Add to suspense"}
        </button>
      </div>
    </Modal>
  );
}

function MatchModal({
  itemId,
  onClose,
  onResolved,
}: {
  itemId: string;
  onClose: () => void;
  onResolved: () => void;
}) {
  const [data, setData] = useState<{
    item: SuspenseItem;
    candidates: MatchCandidate[];
  } | null>(null);
  const [note, setNote] = useState("");
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    start(async () => {
      try {
        setData(await api.matchSuspense(itemId));
      } catch (e) {
        setErr(e instanceof Error ? e.message : "match failed");
      }
    });
  }, [itemId]);

  const resolve = (c: MatchCandidate) => {
    start(async () => {
      try {
        await api.resolveSuspense(itemId, {
          rider_id: c.customer_id,
          rider_name: c.customer_name,
          invoice_number: c.invoice_number,
          note: note.trim() || undefined,
        });
        onResolved();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "resolve failed");
      }
    });
  };

  return (
    <Modal title="Find a match" onClose={onClose} wide>
      {!data ? (
        <div className="p-6 text-sm text-ink-fade">Searching…</div>
      ) : (
        <>
          <div className="px-5 py-3 border-b border-canvas-line bg-canvas-sunken/40 text-xs">
            <span className="text-ink-muted">Payment:</span>{" "}
            <span className="font-mono text-ink">
              GHS{" "}
              {data.item.amount_ghs.toLocaleString(undefined, {
                minimumFractionDigits: 2,
              })}
            </span>{" "}
            <span className="text-ink-muted">via {data.item.channel}</span>{" "}
            <span className="font-mono text-ink-muted">
              ref {data.item.channel_reference}
            </span>{" "}
            <span className="text-ink-muted">on {data.item.received_at}</span>
            {data.item.msisdn && (
              <span className="text-ink-muted"> · {data.item.msisdn}</span>
            )}
          </div>

          <div className="px-5 py-3 flex gap-3 items-center border-b border-canvas-line">
            <label className="text-[10px] uppercase tracking-wider text-ink-fade font-medium">
              Resolution note
            </label>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="optional — what triggered this match"
              className="flex-1 text-xs px-2 py-1 bg-canvas-raised border border-canvas-line rounded-md"
            />
          </div>

          <div className="max-h-[50vh] overflow-auto">
            <table className="data-grid">
              <thead className="sticky top-0">
                <tr>
                  <th>Conf.</th>
                  <th>Rider</th>
                  <th>Invoice</th>
                  <th>Total / Balance</th>
                  <th>Age</th>
                  <th>Reason</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.candidates.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-center text-ink-fade py-8">
                      No invoices within ±GHS 2.00 of this amount. Try escalating
                      or adjust the amount.
                    </td>
                  </tr>
                )}
                {data.candidates.map((c) => (
                  <tr key={`${c.invoice_id}-${c.customer_id}`}>
                    <td>
                      <span
                        className={`badge-${
                          c.confidence === "high"
                            ? "success"
                            : c.confidence === "medium"
                            ? "warning"
                            : "muted"
                        }`}
                      >
                        {c.confidence}
                      </span>
                    </td>
                    <td>
                      <div className="text-sm font-medium text-ink">
                        {c.customer_name}
                      </div>
                      <div className="text-xs text-ink-fade font-mono">
                        {c.customer_id}
                      </div>
                    </td>
                    <td className="text-xs font-mono text-ink-muted">
                      {c.invoice_number}
                      <div className="text-[10px] text-ink-fade">
                        {c.invoice_date}
                      </div>
                    </td>
                    <td className="font-mono text-xs">
                      {c.invoice_total_ghs.toFixed(2)} /{" "}
                      <span className="text-clay-600">
                        {c.invoice_balance_ghs.toFixed(2)}
                      </span>
                    </td>
                    <td className="text-xs text-ink-muted">{c.days_old}d</td>
                    <td className="text-xs text-ink-muted max-w-xs">
                      {c.why_match}
                    </td>
                    <td>
                      <button
                        onClick={() => resolve(c)}
                        disabled={pending}
                        className="text-xs px-2 py-1 bg-moss-500 text-canvas-raised rounded hover:bg-moss-600
                                   inline-flex items-center gap-1"
                      >
                        <Check className="w-3 h-3" /> Assign
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {err && <div className="px-5 py-2 text-xs text-clay-600">{err}</div>}
        </>
      )}
    </Modal>
  );
}

function BookButton({ id, onDone }: { id: string; onDone: () => void }) {
  const [pending, start] = useTransition();
  return (
    <button
      onClick={() => {
        if (
          !confirm(
            "Book this payment to the accounting suspense account?\n\nUse this when no rider/invoice match is possible right now — the cash is acknowledged in the GL but stays unallocated until you reconcile later.",
          )
        )
          return;
        start(async () => {
          await api.bookSuspense(id);
          onDone();
        });
      }}
      disabled={pending}
      className="text-xs text-ink-muted hover:text-ink inline-flex items-center gap-1"
      title="Book to suspense account"
    >
      <Wallet className="w-3 h-3" /> Book to suspense a/c
    </button>
  );
}

function DeleteButton({ id, onDone }: { id: string; onDone: () => void }) {
  const [pending, start] = useTransition();
  return (
    <button
      onClick={() => {
        if (!confirm("Delete this suspense item permanently?")) return;
        start(async () => {
          await api.deleteSuspense(id);
          onDone();
        });
      }}
      disabled={pending}
      className="text-xs text-ink-fade hover:text-clay-600"
      title="Delete"
    >
      <Trash2 className="w-3 h-3" />
    </button>
  );
}

function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 bg-ink/40 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className={`bg-canvas-raised rounded-xl shadow-floating w-full ${wide ? "max-w-4xl" : "max-w-md"} max-h-[85vh] flex flex-col`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-canvas-line">
          <h3 className="text-base font-display tracking-tightest">{title}</h3>
          <button onClick={onClose} className="p-1 hover:bg-canvas-sunken rounded">
            <X className="w-4 h-4 text-ink-muted" />
          </button>
        </div>
        <div className="flex-1 overflow-auto">{children}</div>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-[10px] uppercase tracking-wider text-ink-fade font-medium block mb-1">
        {label}
      </label>
      {children}
    </div>
  );
}
