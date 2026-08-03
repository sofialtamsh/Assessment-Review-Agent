import ActivityPanel from "@/components/ActivityPanel";
import CrossSetCheck from "@/components/CrossSetCheck";
import InsightsPanel from "@/components/InsightsPanel";
import UploadRun from "@/components/UploadRun";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <div className="space-y-8">
      <UploadRun />
      <CrossSetCheck />
      <InsightsPanel />
      <ActivityPanel />
    </div>
  );
}
