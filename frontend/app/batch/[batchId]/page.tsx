import BatchDashboard from "@/components/BatchDashboard";

export const dynamic = "force-dynamic";

export default function BatchPage({ params }: { params: { batchId: string } }) {
  return <BatchDashboard batchId={params.batchId} />;
}
