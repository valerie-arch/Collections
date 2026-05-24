/**
 * Typed API client for the Wahu Collections backend.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export type ReportView = "mtd" | "lifetime" | "custom";
export type ReportStatus = "active" | "recovery" | "completed" | "all";
export type ReportFleet = "All" | "Wahu" | "TSA";

type ReportQuery = {
  view?: ReportView;
  status?: ReportStatus;
  fleet?: ReportFleet;
  agency?: string;
  window_start?: string;
  window_end?: string;
};

function qs(params: Record<string, string | undefined>): string {
  const filtered = Object.entries(params).filter(([, v]) => v) as [string, string][];
  return new URLSearchParams(filtered).toString();
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  // Reports
  reportCollections: (params: ReportQuery = {}) =>
    request<CollectionsReport>(`/api/reports/collections?${qs(params as any)}`),
  collectionsDownloadUrl: (params: ReportQuery = {}) =>
    `${BASE}/api/reports/collections/download?${qs(params as any)}`,
  collectionsMemo: (params: ReportQuery = {}) =>
    request<MemoResponse>(`/api/reports/collections/memo?${qs(params as any)}`),
  collectionsMemoPdfUrl: (params: ReportQuery = {}) =>
    `${BASE}/api/reports/collections/memo.pdf?${qs(params as any)}`,
  collectionsMemoDocxUrl: (params: ReportQuery = {}) =>
    `${BASE}/api/reports/collections/memo.docx?${qs(params as any)}`,

  // Trends
  portfolioTrends: (months_back = 24, fleet: ReportFleet = "All") =>
    request<TrendsResponse>(
      `/api/trends/portfolio?months_back=${months_back}&fleet=${fleet}`,
    ),
  portfolioDownloadUrl: (months_back = 24, fleet: ReportFleet = "All") =>
    `${BASE}/api/trends/portfolio/download?months_back=${months_back}&fleet=${fleet}`,

  // Dashboard v2 — 10 KPIs
  dashboardSnapshot: (params: DashboardSnapshotQuery = {}) =>
    request<DashboardSnapshot>(
      `/api/dashboard-v2/snapshot?${qs(params as any)}`,
    ),

  // Dashboard v2 trends — Collections Rate, MRR Movement, Charge-off, Lifetime Efficiency
  dashboardTrends: (params: DashboardTrendsQuery = {}) =>
    request<DashboardTrends>(
      `/api/dashboard-v2/trends?${qs(params as any)}`,
    ),

  // Invoices listing (filterable)
  invoicesList: (params: InvoicesListQuery = {}) =>
    request<InvoicesListResponse>(`/api/invoices/list?${qs(params as any)}`),

  // Payments listing (filterable, MTN/Telecel/Bank/Bolt)
  paymentsList: (params: PaymentsListQuery = {}) =>
    request<PaymentsListResponse>(`/api/payments/list?${qs(params as any)}`),

  // Drive
  driveSync: () =>
    request<{
      folder_id: string;
      filter: string;
      total: number;
      downloaded: string[];
      skipped: string[];
      subscriptions_folder_id?: string;
      subscriptions_synced?: number;
      subscriptions_error?: string | null;
    }>(`/api/drives/sync`, { method: "POST" }),
  driveStatus: () =>
    request<{
      local_folder: string;
      file_count: number;
      total_size_bytes: number;
      files: { name: string; size_bytes: number; modified_at: number }[];
    }>(`/api/drives/status`),

  // Agencies
  listAgencies: () =>
    request<{
      assignments: Record<string, { agency: string; assigned_at: string; note: string | null }>;
      agencies: string[];
      count: number;
    }>(`/api/agencies/`),
  assignAgency: (customer_id: string, agency: string, note?: string) =>
    request<{ customer_id: string; agency: string; assigned_at: string; note: string | null }>(
      `/api/agencies/assign`,
      { method: "POST", body: JSON.stringify({ customer_id, agency, note }) },
    ),
  unassignAgency: (customer_id: string) =>
    request<{ customer_id: string; removed: boolean }>(
      `/api/agencies/unassign`,
      { method: "POST", body: JSON.stringify({ customer_id }) },
    ),

  // Collections activities (logged actions on riders) + SOP §10 recommender
  listActivities: (params: {
    customer_id?: string;
    action?: string;
    agency?: string;
    since?: string;
    until?: string;
  } = {}) =>
    request<{ items: ActivityItem[]; count: number; actions: string[] }>(
      `/api/activities/?${qs(params as any)}`,
    ),
  createActivity: (payload: {
    customer_id: string;
    customer_name: string;
    action: ActivityAction;
    note: string;
    actor?: string;
  }) =>
    request<ActivityItem>(`/api/activities/`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteActivity: (id: string) =>
    request<{ removed: boolean }>(`/api/activities/${id}`, { method: "DELETE" }),
  listRecommendations: (params: { agency?: string; limit?: number } = {}) =>
    request<{ items: Recommendation[]; total?: number; _note?: string }>(
      `/api/activities/recommendations?${qs(params as any)}`,
    ),
  recommendationFor: (customer_id: string) =>
    request<Recommendation>(`/api/activities/recommendations/${customer_id}`),
  runDailyActivitiesReport: (day?: string) =>
    request<{
      day: string;
      activities_count: number;
      unique_riders: number;
      xlsx_bytes: number;
      filename: string;
      drive: { uploaded: boolean; webViewLink?: string; reason?: string };
    }>(`/api/activities/run-daily${day ? `?day=${day}` : ""}`, { method: "POST" }),

  // QuickBooks export
  qbPreview: (params: {
    type: "invoices" | "payments";
    window_start: string;
    window_end: string;
    fleet?: ReportFleet;
    limit?: number;
  }) =>
    request<QbPreviewResponse>(`/api/quickbooks/?${qs(params as any)}`),
  qbDownloadUrl: (params: {
    type: "invoices" | "payments";
    window_start: string;
    window_end: string;
    fleet?: ReportFleet;
  }) =>
    `${BASE}/api/quickbooks/download?${qs(params as any)}`,

  // Exceptions
  listOutliers: (params: { category?: string; severity?: string; limit?: number } = {}) =>
    request<OutliersResponse>(
      `/api/exceptions/outliers?${qs(params as any)}`,
    ),

  // Suspense reconciliation (manual matching of unlinked payments)
  listSuspenseItems: (status?: SuspenseStatus) =>
    request<{
      items: SuspenseItem[];
      counts: { open: number; resolved: number; booked: number };
    }>(`/api/suspense/${status ? `?status=${status}` : ""}`),
  createSuspense: (payload: {
    channel: string;
    channel_reference: string;
    amount_ghs: number;
    received_at: string;
    msisdn?: string;
    note?: string;
  }) =>
    request<SuspenseItem>(`/api/suspense/`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  matchSuspense: (id: string, tolerance = 2.0) =>
    request<{ item: SuspenseItem; candidates: MatchCandidate[] }>(
      `/api/suspense/${id}/matches?tolerance=${tolerance}`,
    ),
  resolveSuspense: (id: string, payload: {
    rider_id: string;
    rider_name?: string;
    invoice_number?: string;
    note?: string;
  }) =>
    request<SuspenseItem>(`/api/suspense/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  bookSuspense: (id: string, note?: string) =>
    request<SuspenseItem>(`/api/suspense/${id}/book`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  reopenSuspense: (id: string) =>
    request<SuspenseItem>(`/api/suspense/${id}/reopen`, { method: "POST" }),
  deleteSuspense: (id: string) =>
    request<{ removed: boolean }>(`/api/suspense/${id}`, { method: "DELETE" }),

  // Payment reconciliation
  paymentsSync: () =>
    request<{
      ok: boolean;
      folder_id: string;
      total: number;
      downloaded: string[];
      skipped: string[];
    }>(`/api/payments/sync`, { method: "POST" }),
  paymentsReconcile: (cutoff?: string) =>
    request<PaymentReconcileResult>(
      `/api/payments/reconcile${cutoff ? `?cutoff=${cutoff}` : ""}`,
    ),
  paymentsScheduleUrl: (cutoff?: string) =>
    `${BASE}/api/payments/schedule.xlsx${cutoff ? `?cutoff=${cutoff}` : ""}`,
  paymentsPushSuspense: (cutoff?: string) =>
    request<{
      ok: boolean;
      pushed: number;
      already_in_suspense: number;
      errors: number;
      total_unmatched: number;
    }>(
      `/api/payments/push-suspense${cutoff ? `?cutoff=${cutoff}` : ""}`,
      { method: "POST" },
    ),
};

export type MatchedPayment = {
  source_file: string;
  line_no: number;
  payment_date: string | null;
  amount_ghs: number;
  channel: string;
  raw_name: string;
  msisdn: string | null;
  reference: string;
  rider_id: string;
  rider_name: string;
  method: string;
  confidence: number;
  unapplied_ghs: number;
  allocations: {
    invoice_id: string;
    invoice_number: string;
    applied_ghs: number;
    balance_before_ghs: number;
    balance_after_ghs: number;
  }[];
};

export type UnmatchedPayment = {
  source_file: string;
  line_no: number;
  payment_date: string | null;
  amount_ghs: number;
  channel: string;
  raw_name: string;
  msisdn: string | null;
  reference: string;
  best_guess_rider_name: string;
  best_guess_confidence: number;
  reason: string;
  in_suspense: boolean;
};

export type PaymentReconcileResult = {
  cutoff_date: string;
  invoices_corpus_size: number;
  riders_in_master: number;
  total_payments: number;
  in_scope_payments: number;
  total_matched_amount_ghs: number;
  total_unmatched_amount_ghs: number;
  matched: MatchedPayment[];
  unmatched: UnmatchedPayment[];
};

export type ActivityAction =
  | "phone_call"
  | "immobilisation_request"
  | "call_to_guarantor"
  | "remobilisation_request"
  | "house_visit"
  | "ebike_recovery"
  | "legal_action_taken"
  | "legal_action_update"
  | "to_be_written_off"
  | "other";

export type ActivityItem = {
  id: string;
  customer_id: string;
  customer_name: string;
  action: ActivityAction;
  note: string;
  actor: string;
  agency: string | null;
  created_at: string;
};

export type Recommendation = {
  customer_id: string;
  customer_name: string;
  severity: "info" | "warning" | "critical";
  recommended_action: ActivityAction | "no_action";
  rationale: string;
  oldest_open_days: number;
  open_invoice_count: number;
  outstanding_ghs: number;
  agency: string | null;
  agency_assigned_at: string | null;
  risk_band: string;
  collection_ratio: number;
  lifetime_invoiced_ghs: number;
  last_activity_at: string | null;
  last_activity_action: string | null;
};

export type SuspenseStatus = "open" | "resolved" | "booked";

export type SuspenseItem = {
  id: string;
  channel: string;
  channel_reference: string;
  msisdn: string | null;
  amount_ghs: number;
  received_at: string;
  status: SuspenseStatus;
  note: string | null;
  resolved_rider_id: string | null;
  resolved_rider_name: string | null;
  resolved_invoice_number: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
  created_at: string;
};

export type MatchCandidate = {
  customer_id: string;
  customer_name: string;
  invoice_id: string;
  invoice_number: string;
  invoice_date: string;
  invoice_total_ghs: number;
  invoice_balance_ghs: number;
  days_old: number;
  confidence: "high" | "medium" | "low";
  why_match: string;
};

export type ExceptionRow = {
  exception_id: string;
  run_id: string;
  step: number;
  severity: string;
  status: string;
  error_code: string | null;
  message: string;
  context: unknown;
  created_at: string | null;
};

export type SuspenseRow = {
  suspense_id: string;
  run_date: string;
  channel: string;
  channel_reference: string | null;
  amount_ghs: number | null;
  msisdn: string | null;
  status: string;
  rider_id: string | null;
  invoice_id: string | null;
  created_at: string | null;
};

export type CollectionsReport = {
  report: string;
  view: ReportView;
  status_filter: ReportStatus;
  fleet: ReportFleet;
  as_of?: string;
  window?: { start: string; end: string; label: string };
  active_riders: number;
  total_rider_population?: number;
  headlines: {
    lifetime_invoiced_ghs?: number;
    lifetime_collected_ghs?: number;
    lifetime_outstanding_ghs?: number;
    open_invoice_lines?: number;
    cash_in_window_ghs?: number;
    cash_applied_to_period_ghs?: number;
    cash_applied_to_prior_ghs?: number;
    riders_paid_in_window?: number;
    payment_activity_rate?: number;
    collection_ratio?: number;
  };
  bands: { band: string; riders: number; outstanding_ghs: number; definition: string }[];
  ageing: { label: string; open_invoices: number; outstanding_ghs: number }[];
  riders: {
    customer_id: string;
    customer_name: string;
    first_invoice: string;
    last_invoice: string;
    last_payment_date: string | null;
    months_since_last_invoice: number;
    lifetime_invoices: number;
    open_invoices: number;
    lifetime_invoiced_ghs: number;
    lifetime_collected_ghs: number;
    lifetime_outstanding_ghs: number;
    collection_ratio: number;
    risk_band: string;
    status: string;
    fleet: string;
    agency: string | null;
    plans: string;
  }[];
  _note?: string;
};

export type MemoResponse = {
  view: ReportView;
  status_filter: ReportStatus;
  fleet: ReportFleet;
  as_of: string;
  window_label: string;
  memo_text: string;
};

export type TrendsResponse = {
  as_of: string;
  fleet: ReportFleet;
  cumulative: { active: number; completed: number; recovery: number };
  months: {
    label: string;
    year: number;
    month: number;
    invoiced_ghs: number;
    collected_ghs: number;
    outstanding_ghs: number;
    active_riders: number;
    new_riders: number;
    invoices_issued: number;
    mrr_ghs: number;
  }[];
  top_10_outstanding: RiderRanking[];
  bottom_10_ratio: RiderRanking[];
  top_10_collected_lifetime: RiderRanking[];
};

export type RiderRanking = {
  customer_id: string;
  customer_name: string;
  lifetime_invoiced_ghs: number;
  lifetime_collected_ghs: number;
  lifetime_outstanding_ghs: number;
  collection_ratio: number;
};

export type QbPreviewResponse = {
  type: "invoices" | "payments";
  fleet: ReportFleet;
  window_start?: string;
  window_end?: string;
  row_count: number;
  total_amount_ghs: number;
  rows: Record<string, any>[];
  _note?: string;
};

// ---------------------------------------------------------------------------
// Dashboard v2 — 10 KPIs
// ---------------------------------------------------------------------------

export type DashboardPeriod = "mtd" | "lifetime" | "custom";

export type DashboardSnapshotQuery = {
  period?: DashboardPeriod;
  start?: string;        // YYYY-MM-DD
  end?: string;
  fleet?: ReportFleet;
  as_of?: string;
};

export type TenureSegment = {
  tenure: string;
  active_riders: number;
  paying_riders: number;
  rate_pct: number;
};

export type ActivePayerRate = {
  overall_rate_pct: number;
  overall_paying: number;
  overall_active: number;
  by_tenure: TenureSegment[];
  lookback_days: number;
};

export type OnTimeRate = {
  on_time_pct: number;
  on_time_count: number;
  total_paid_count: number;
  note: string;
};

export type BlockedKpi = { available: false; reason: string };

export type CollectionSplits = {
  fully_paid_riders: number;
  partial_riders: number;
  no_pay_riders: number;
};

export type MonthlyCollectionsRate = {
  invoiced_ghs: number;
  collected_ghs: number;
  gross_rate_pct: number;
  write_offs_ghs: number;
  net_rate_pct: number;
  splits: CollectionSplits;
};

export type MrrSnapshot = {
  current_ghs: number;
  new_ghs: number;
  churned_ghs: number;
  reactivated_ghs: number;
  net_new_ghs: number;
  active_riders: number;
  new_riders: number;
  churned_riders: number;
};

export type AgingBucket = {
  label: string;
  rider_count: number;
  open_invoice_count: number;
  ghs: number;
  pct_of_ghs: number;
};

export type AgingDistribution = {
  as_of: string;
  buckets: AgingBucket[];
  total_outstanding_ghs: number;
  total_riders_with_balance: number;
};

export type LifetimeEfficiency = {
  invoiced_ghs: number;
  collected_ghs: number;
  outstanding_ghs: number;
  efficiency_pct: number;
};

export type NetChargeOff = {
  available: boolean;
  charge_offs_ghs: number;
  recoveries_ghs: number;
  net_ghs: number;
  avg_outstanding_ghs: number;
  annualized_pct: number;
  window_days: number;
  reason: string;
};

export type RecoveryByDays = { bucket: string; ghs: number };

export type RecoveryOnChurned = {
  cohort_size: number;
  cohort_outstanding_at_churn_ghs: number;
  recovered_ghs: number;
  recovery_rate_pct: number;
  by_days_post_churn: RecoveryByDays[];
  note: string;
};

export type DashboardSnapshot = {
  as_of: string;
  fleet: ReportFleet;
  window: {
    period: DashboardPeriod;
    start: string;
    end: string;
    label: string;
  };
  data_sources: {
    invoices: number;
    write_off_ledger_loaded: boolean;
    subscriptions_loaded: boolean;
  };
  behavioral: {
    active_payer_rate: ActivePayerRate;
    on_time_payment_rate: OnTimeRate;
    roll_rates: BlockedKpi;
  };
  financial: {
    monthly_collections_rate: MonthlyCollectionsRate;
    mrr: MrrSnapshot;
  };
  portfolio: {
    aging: AgingDistribution;
    lifetime_efficiency: LifetimeEfficiency;
    cure_rate: BlockedKpi;
    net_charge_off: NetChargeOff;
    recovery_on_churned: RecoveryOnChurned;
  };
};

// ---------------------------------------------------------------------------
// Dashboard v2 — Trends section
// ---------------------------------------------------------------------------

export type DashboardLookback = "3m" | "6m" | "12m" | "all";

export type DashboardTrendsQuery = {
  lookback?: DashboardLookback;
  fleet?: ReportFleet;
  as_of?: string;
};

export type CollectionsRatePoint = {
  label: string;
  year: number;
  month: number;
  invoiced_ghs: number;
  collected_ghs: number;
  rate_pct: number;
};

export type MrrMovementPoint = {
  label: string;
  year: number;
  month: number;
  opening_ghs: number;
  new_ghs: number;
  reactivated_ghs: number;
  churned_ghs: number;
  closing_ghs: number;
  net_new_ghs: number;
};

export type ChargeOffPoint = {
  label: string;
  year: number;
  month: number;
  charge_offs_ghs: number;
  recoveries_ghs: number;
  net_ghs: number;
};

export type LifetimeEfficiencyPoint = {
  label: string;
  year: number;
  month: number;
  cumulative_invoiced_ghs: number;
  cumulative_collected_ghs: number;
  efficiency_pct: number;
};

export type DashboardTrends = {
  as_of: string;
  fleet: ReportFleet;
  lookback: DashboardLookback;
  axis: { labels: string[] };
  collections_rate: {
    target_pct: number;
    points: CollectionsRatePoint[];
  };
  mrr_movement: {
    points: MrrMovementPoint[];
  };
  charge_off: {
    available: boolean;
    points: ChargeOffPoint[];
    reason: string;
  };
  lifetime_efficiency: {
    points: LifetimeEfficiencyPoint[];
  };
};

// ---------------------------------------------------------------------------
// Invoices + Payments listings
// ---------------------------------------------------------------------------

export type InvoicesListQuery = {
  view?: "mtd" | "lifetime" | "custom";
  status?: "active" | "recovery" | "completed" | "all";
  fleet?: ReportFleet;
  start?: string;
  end?: string;
  q?: string;
  limit?: number;
  offset?: number;
};

export type InvoiceStream = "rider_daily" | "rider_larger" | "b2b_dealer";

export type InvoiceListRow = {
  invoice_id: string;
  customer_id: string;
  customer_name: string;
  invoice_date: string | null;
  due_date: string | null;
  status: string;
  total_ghs: number;
  balance_ghs: number;
  last_payment_date: string | null;
  stream: InvoiceStream;
};

export type InvoiceStreamSummary = {
  stream: InvoiceStream;
  label: string;
  count: number;
  total_ghs: number;
};

export type InvoiceAgingBucket = {
  label: string;
  rider_count: number;
  open_invoice_count: number;
  ghs: number;
  pct_of_ghs: number;
};

export type InvoicesListResponse = {
  as_of: string;
  window: { period: string; start: string; end: string; label: string };
  filters: { view: string; status: string; fleet: ReportFleet };
  summary: {
    total_invoices: number;
    open_count: number;
    total_invoiced_ghs: number;
    total_outstanding_ghs: number;
    by_stream: InvoiceStreamSummary[];
  };
  aging: {
    as_of: string;
    total_outstanding_ghs: number;
    buckets: InvoiceAgingBucket[];
  };
  limit: number;
  offset: number;
  rows: InvoiceListRow[];
};

export type PaymentChannel =
  | "all" | "mtn" | "telecel" | "hero" | "bank" | "cash" | "bolt_deduction" | "unknown";

export type PaymentMatchStatus = "all" | "matched" | "unmatched";

export type PaymentView = "mtd" | "lifetime" | "custom";

export type PaymentsListQuery = {
  view?: PaymentView;
  channel?: PaymentChannel;
  match_status?: PaymentMatchStatus;
  start?: string;
  end?: string;
  q?: string;
  limit?: number;
  offset?: number;
};

export type PaymentListRow = {
  source: "receipt" | "bolt";
  channel: string;
  method: string;
  date: string | null;
  amount_ghs: number;
  sender_name: string;
  sender_phone: string;
  reference: string;
  narration: string;
  source_file: string;
  line_no?: number;
  txn_id: string;
  matched: boolean;
  rider_id: string;
  rider_name: string;
  applied_to_invoice: string;
  days_late: number | null;
  timeliness: string;
  stream: string;
};

export type PaymentMethodSummary = {
  method: string;
  count: number;
  value_ghs: number;
};

export type PaymentTimelinessBucket = {
  bucket: string;
  count: number;
  pct_count: number;
  value_ghs: number;
  pct_value: number;
};

export type PaymentsListResponse = {
  as_of: string;
  window: { period: string; start: string; end: string; label: string };
  filters: { view: string; channel: string; match_status: string };
  summary: {
    total_payments: number;
    total_value_ghs: number;
    unique_paying_riders: number;
    matched_count: number;
    matched_value_ghs: number;
    unmatched_count: number;
    unmatched_value_ghs: number;
    by_method: PaymentMethodSummary[];
    timeliness: PaymentTimelinessBucket[];
  };
  row_total: number;
  limit: number;
  offset: number;
  rows: PaymentListRow[];
  _error?: string;
};

export type OutliersResponse = {
  as_of: string;
  counts: Record<string, number>;
  total: number;
  items: {
    category: string;
    severity: string;
    title: string;
    detail: string;
    customer_id: string;
    customer_name: string;
    invoice_id: string;
    invoice_number: string;
    invoice_date: string;
    amount_ghs: number;
    days_old: number;
  }[];
  _note?: string;
};
