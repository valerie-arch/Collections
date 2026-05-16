import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api";
import { ActivitiesClient } from "./activities-client";

export const dynamic = "force-dynamic";

export default async function ActivitiesPage({
  searchParams,
}: {
  searchParams?: { agency?: string; band?: string; q?: string };
}) {
  const agencyFilter = searchParams?.agency ?? "All";
  const recs = await api
    .listRecommendations({
      agency:
        agencyFilter === "All"
          ? undefined
          : agencyFilter === "Unassigned"
          ? "Unassigned"
          : agencyFilter,
      limit: 1000,
    })
    .catch(() => null);

  return (
    <div className="px-10 py-12 max-w-[88rem]">
      <PageHeader
        eyebrow="Collections officer"
        title="Activities"
        description="Every rider with outstanding balance, with the SOP §10-recommended next action. Click a row to see history and log a new action. Daily summary archived to Google Drive at 18:00 Africa/Accra."
      />
      <ActivitiesClient
        initialRecommendations={recs?.items ?? []}
        agencyFilter={agencyFilter}
        bandFilter={searchParams?.band ?? "All"}
        searchQuery={searchParams?.q ?? ""}
      />
    </div>
  );
}
