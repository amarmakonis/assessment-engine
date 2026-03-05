import { useCallback, useEffect, useState } from "react";
import {
  Upload,
  FileText,
  BarChart3,
  AlertTriangle,
  Loader2,
  Activity,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { KPICard } from "@/components/ui/KPICard";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { PageHeader } from "@/components/ui/PageHeader";
import { SkeletonKPI, SkeletonActivityRow } from "@/components/ui/Skeleton";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { dashboardAPI } from "@/services/api";
import toast from "react-hot-toast";
import type { DashboardKPIs, ActivityItem } from "@/types";
import { formatDistanceToNow } from "date-fns";

const POLL_INTERVAL_MS = 30_000; // refresh every 30 seconds

export function DashboardPage() {
  const [kpis, setKPIs] = useState<DashboardKPIs | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [dismissItem, setDismissItem] = useState<ActivityItem | null>(null);
  const [showClearAllModal, setShowClearAllModal] = useState(false);

  const fetchData = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    try {
      const [kpiRes, actRes] = await Promise.all([
        dashboardAPI.kpis(),
        dashboardAPI.recentActivity(),
      ]);
      setKPIs(kpiRes.data);
      setActivity(actRes.data.activity);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh so "Recent Activity" and KPIs stay up to date
  useEffect(() => {
    const id = setInterval(() => fetchData(true), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchData]);

  // Update "time ago" every minute so timestamps don't look stuck
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  async function handleDismissActivity(item: ActivityItem) {
    setDismissItem(item);
  }

  async function confirmDismissItem() {
    if (!dismissItem) return;
    const item = dismissItem;
    setDismissItem(null);
    try {
      await dashboardAPI.dismissActivity(item.type, item.id);
      toast.success("Removed from recent activity");
      setActivity((prev) => prev.filter((a) => !(a.type === item.type && a.id === item.id)));
      fetchData(true);
    } catch {
      toast.error("Failed to remove from list");
    }
  }

  function handleClearAllClick() {
    if (activity.length === 0) return;
    setShowClearAllModal(true);
  }

  async function confirmClearAll() {
    setShowClearAllModal(false);
    try {
      await dashboardAPI.clearActivity();
      toast.success("Recent activity cleared");
      setActivity([]);
      fetchData(true);
    } catch {
      toast.error("Failed to clear list");
      fetchData(true);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        subtitle="Real-time overview of your assessment pipeline"
        actions={
          <button
            onClick={() => fetchData(true)}
            disabled={refreshing}
            className="btn-secondary flex items-center gap-2"
            title="Refresh dashboard"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading ? (
          <>
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <SkeletonKPI key={i} />
            ))}
          </>
        ) : (
          <>
            <KPICard
              label="Uploads Today"
              value={kpis?.totalUploadsToday ?? 0}
              icon={<Upload className="w-6 h-6" />}
              accentColor="text-accent-cyan"
            />
            <KPICard
              label="Total Scripts"
              value={kpis?.totalScripts ?? 0}
              icon={<FileText className="w-6 h-6" />}
              accentColor="text-accent-blue"
            />
            <KPICard
              label="Average Score"
              value={`${kpis?.averageScore ?? 0}%`}
              icon={<BarChart3 className="w-6 h-6" />}
              accentColor="text-accent-green"
            />
            <KPICard
              label="Review Queue"
              value={kpis?.reviewQueueSize ?? 0}
              icon={<AlertTriangle className="w-6 h-6" />}
              accentColor="text-accent-gold"
            />
            <KPICard
              label="Failed Scripts"
              value={kpis?.failedScripts ?? 0}
              icon={<AlertTriangle className="w-6 h-6" />}
              accentColor="text-accent-red"
            />
            <KPICard
              label="Processing Now"
              value={kpis?.processingNow ?? 0}
              icon={<Loader2 className="w-6 h-6" />}
              accentColor="text-accent-purple"
            />
          </>
        )}
      </div>

      <GlassCard>
        <div className="flex items-center justify-between mb-4">
          <h3 className="section-title flex items-center gap-2">
            <Activity className="w-5 h-5 text-accent-blue" />
            Recent Activity
          </h3>
          {activity.length > 0 && (
            <button
              type="button"
              onClick={handleClearAllClick}
              className="text-sm text-text-muted hover:text-accent-red transition-colors flex items-center gap-1.5"
              title="Clear all from recent activity (data is kept)"
            >
              <Trash2 className="w-4 h-4" />
              Clear all
            </button>
          )}
        </div>
        <div className="space-y-1 max-h-96 overflow-y-auto">
          {loading ? (
            <>
              {[1, 2, 3, 4].map((i) => (
                <SkeletonActivityRow key={i} />
              ))}
            </>
          ) : (
          activity.map((item) => (
            <div
              key={`${item.type}-${item.id}`}
              className={`
                flex items-center gap-3 p-3 rounded-lg border-l-4 border-transparent
                transition-all duration-200 cursor-default
                hover:bg-blue-50/60 hover:border-l-accent-blue hover:shadow-sm
              `}
            >
              <div className="flex-1 min-w-0">
                <p className="text-[15px] font-medium text-text-primary truncate">
                  {item.type === "upload"
                    ? `Upload: ${item.filename}`
                    : `Evaluation: Q${item.questionId}`}
                </p>
                <p className="text-sm text-text-muted">
                  {item.createdAt
                    ? formatDistanceToNow(new Date(item.createdAt), {
                        addSuffix: true,
                      })
                    : ""}
                </p>
              </div>
              <StatusBadge status={item.status} />
              {item.totalScore !== undefined && item.maxScore !== undefined && (
                <span className="font-mono text-sm text-accent-blue font-semibold">
                  {item.totalScore}/{item.maxScore}
                </span>
              )}
              <button
                type="button"
                onClick={() => handleDismissActivity(item)}
                className="p-1.5 rounded text-text-muted hover:text-accent-red hover:bg-red-50 transition-colors"
                title="Remove from recent activity (data is kept)"
                aria-label="Remove from recent activity"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          )))}
          <ConfirmModal
            isOpen={showClearAllModal}
            onClose={() => setShowClearAllModal(false)}
            onConfirm={confirmClearAll}
            title="Clear recent activity"
            message={`Remove all ${activity.length} items from this list? Your data is kept; they will only be hidden from recent activity.`}
            confirmLabel="Clear all"
            cancelLabel="Cancel"
            variant="default"
          />
          <ConfirmModal
            isOpen={!!dismissItem}
            onClose={() => setDismissItem(null)}
            onConfirm={confirmDismissItem}
            title="Remove from recent activity"
            message="This will only hide the item from the list. Your upload and evaluation data will be kept."
            confirmLabel="Remove"
            cancelLabel="Cancel"
            variant="default"
          />
          {!loading && activity.length === 0 && (
            <p className="text-center text-text-muted py-8 text-[15px]">
              No recent activity
            </p>
          )}
        </div>
      </GlassCard>
    </div>
  );
}
