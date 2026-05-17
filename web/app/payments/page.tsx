import { PageHeader } from "@/components/PageHeader";
import { PaymentsClient } from "./payments-client";

export const dynamic = "force-dynamic";

export default function PaymentsPage({
  searchParams,
}: {
  searchParams?: { cutoff?: string };
}) {
  const cutoff = searchParams?.cutoff || "2026-05-14";
  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Reconciliation"
        title="Payments"
        description="Pull rider payments from Drive, match to riders, allocate against the oldest open Zoho invoice, and download a Zoho upload schedule. Anything that can't be matched gets pushed to Suspense."
      />
      <PaymentsClient defaultCutoff={cutoff} />
    </div>
  );
}
