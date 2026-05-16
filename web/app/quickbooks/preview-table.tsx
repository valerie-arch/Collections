"use client";

const INVOICE_COLS = [
  "invoice_no", "customer", "invoice_date", "due_date", "terms",
  "item", "description", "quantity", "rate", "amount", "balance",
  "status", "fleet", "currency",
] as const;

const PAYMENT_COLS = [
  "customer", "payment_date", "amount", "payment_method", "reference_no",
  "applied_to_invoice_no", "memo", "fleet", "currency",
] as const;

const HEADER_LABEL: Record<string, string> = {
  invoice_no: "InvoiceNo",
  customer: "Customer",
  invoice_date: "InvoiceDate",
  due_date: "DueDate",
  terms: "Terms",
  item: "Item",
  description: "Description",
  quantity: "Qty",
  rate: "Rate",
  amount: "Amount",
  balance: "Balance",
  status: "Status",
  fleet: "Class",
  currency: "Currency",
  payment_date: "PaymentDate",
  payment_method: "PaymentMethod",
  reference_no: "ReferenceNo",
  applied_to_invoice_no: "AppliedToInvoiceNo",
  memo: "Memo",
};

const NUMERIC_COLS = new Set(["quantity", "rate", "amount", "balance"]);

export function QbPreviewTable({
  type,
  rows,
  totalRows,
}: {
  type: "invoices" | "payments";
  rows: Record<string, any>[];
  totalRows: number;
}) {
  const cols = type === "invoices" ? INVOICE_COLS : PAYMENT_COLS;

  return (
    <div className="surface overflow-hidden">
      <div className="px-4 py-3 border-b border-canvas-line bg-canvas-sunken/40 flex items-center gap-3">
        <span className="text-sm font-display tracking-tightest">
          {type === "invoices" ? "Invoice preview" : "Payment preview"}
        </span>
        <span className="text-xs text-ink-fade">
          showing {rows.length} of {totalRows.toLocaleString()} — download xlsx
          above for the full file
        </span>
      </div>
      <div className="overflow-x-auto max-h-[600px]">
        <table className="data-grid">
          <thead className="sticky top-0">
            <tr>
              {cols.map((c) => (
                <th key={c}>{HEADER_LABEL[c] ?? c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={cols.length}
                  className="text-center text-ink-fade py-8"
                >
                  No {type} match this window/fleet.
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td
                    key={c}
                    className={
                      NUMERIC_COLS.has(c)
                        ? "font-mono text-sm text-right"
                        : "text-sm"
                    }
                  >
                    {NUMERIC_COLS.has(c) && typeof r[c] === "number"
                      ? (r[c] as number).toLocaleString(undefined, {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })
                      : c === "memo"
                      ? (
                          <span className="text-xs text-ink-fade max-w-md inline-block truncate">
                            {r[c]}
                          </span>
                        )
                      : (r[c] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
