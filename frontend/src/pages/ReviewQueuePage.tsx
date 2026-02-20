import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ClipboardCheck, ExternalLink } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { dashboardAPI } from "@/services/api";
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

  useEffect(() => {
    dashboardAPI
      .reviewQueue()
      .then(({ data }) => setItems(data.items))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="page-title flex items-center gap-2">
          <ClipboardCheck className="w-6 h-6 text-accent-gold" />
          Review Queue
        </h2>
        <p className="text-text-secondary text-base mt-1.5">
          Evaluations requiring human review — {items.length} pending
        </p>
      </div>

      {items.length === 0 ? (
        <GlassCard>
          <p className="text-center text-text-muted py-12">
            No evaluations pending review
          </p>
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
                <Link
                  to={`/scripts/${item.scriptId}/evaluation`}
                  className="btn-primary text-xs !px-3 !py-1.5 flex items-center gap-1"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Review
                </Link>
              </div>
            </GlassCard>
          ))}
        </div>
      )}
    </div>
  );
}
