import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ClipboardCheck, Download, ExternalLink, Trash2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { dashboardAPI, evaluationAPI } from "@/services/api";
import toast from "react-hot-toast";
import { formatDistanceToNow } from "date-fns";

interface ReviewItem {
  id: string;
  scriptId: string;
  questionId: string;
  totalScore: number;
  maxScore: number;
  reviewRecommendation: string;
  reviewReason: string;
  createdAt: string;
}

export function ReviewQueuePage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteResultId, setDeleteResultId] = useState<string | null>(null);

  const loadData = useCallback(() => {
    dashboardAPI
      .reviewQueue()
      .then(({ data }) => setItems(data.items))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  function handleDeleteClick(id: string) {
    setDeleteResultId(id);
  }

  async function confirmDelete() {
    if (!deleteResultId) return;
    const id = deleteResultId;
    setDeleteResultId(null);
    try {
      await evaluationAPI.deleteResult(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
      toast.success("Evaluation deleted");
    } catch {
      toast.error("Failed to delete evaluation");
    }
  }

  async function handleExportCSV() {
    try {
      const { data } = await dashboardAPI.exportReviewQueue();
      const url = URL.createObjectURL(data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "review-queue.csv";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Export downloaded");
    } catch {
      toast.error("Failed to export");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="page-title flex items-center gap-2">
            <ClipboardCheck className="w-6 h-6 text-accent-gold" />
            Review Queue
          </h2>
          <p className="text-text-secondary text-base mt-1.5">
            Evaluations requiring human review — {items.length} pending
          </p>
        </div>
        {items.length > 0 && (
          <button
            onClick={handleExportCSV}
            className="btn-secondary flex items-center gap-2"
            title="Export as CSV"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </button>
        )}
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <GlassCard>
          <EmptyState
            icon={<ClipboardCheck className="w-8 h-8 sm:w-10 sm:h-10 text-text-muted" />}
            title="No evaluations pending review"
            description="All evaluations are either auto-approved or already reviewed."
          />
        </GlassCard>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <GlassCard key={item.id} hover className="!p-4">
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono text-sm text-text-primary">
                      Q: {item.questionId}
                    </span>
                    <StatusBadge status={item.reviewRecommendation} />
                  </div>
                  <p className="text-xs text-text-secondary">
                    {item.reviewReason}
                  </p>
                  <p className="text-xs text-text-muted mt-1">
                    {item.createdAt
                      ? formatDistanceToNow(new Date(item.createdAt), {
                          addSuffix: true,
                        })
                      : ""}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-lg font-bold text-accent-cyan">
                    {item.totalScore}/{item.maxScore}
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <Link
                    to={`/scripts/${item.scriptId}/evaluation`}
                    className="btn-primary text-xs !px-3 !py-1.5 flex items-center gap-1"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    Review
                  </Link>
                  <button
                    onClick={() => handleDeleteClick(item.id)}
                    className="btn-secondary text-xs !px-2.5 !py-1.5 text-accent-red hover:bg-red-50 hover:border-red-200"
                    title="Delete evaluation"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </GlassCard>
          ))}
        </div>
      )}

      <ConfirmModal
        isOpen={!!deleteResultId}
        onClose={() => setDeleteResultId(null)}
        onConfirm={confirmDelete}
        title="Delete evaluation"
        message="This evaluation will be permanently deleted. This cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
      />
    </div>
  );
}
