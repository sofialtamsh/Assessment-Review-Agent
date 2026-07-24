import Dashboard from "@/components/Dashboard";

export const dynamic = "force-dynamic";

export default function DashboardPage({ params }: { params: { runId: string } }) {
  return <Dashboard runId={params.runId} />;
}
