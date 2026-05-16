import { PageHeader } from "@/components/PageHeader";
import { SuspenseSection } from "./suspense-section";

export const dynamic = "force-dynamic";

export default function SuspensePage() {
  return (
    <div className="px-10 py-12 max-w-7xl">
      <PageHeader
        eyebrow="Reconciliation"
        title="Suspense"
        description="Payments received without a clear rider link. Match each to a rider and invoice manually, or book to the accounting suspense account if no match is found yet."
      />
      <SuspenseSection />
    </div>
  );
}
