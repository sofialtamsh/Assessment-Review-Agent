import ActivityPanel from "@/components/ActivityPanel";
import UploadRun from "@/components/UploadRun";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <div className="space-y-8">
      <UploadRun />
      <ActivityPanel />
    </div>
  );
}
