import ActivityPanel from "@/components/ActivityPanel";

export const dynamic = "force-dynamic";

export default function HistoryPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Review history</h1>
        <p className="mt-1 text-sm text-black/50">
          Every review — who ran it, on what, and the outcome. Open any to see its dashboard.
        </p>
      </div>
      <ActivityPanel limit={100} />
    </div>
  );
}
