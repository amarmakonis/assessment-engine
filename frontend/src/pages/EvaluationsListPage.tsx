import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Brain,
  BarChart3,
  AlertTriangle,
  CheckCircle,
  Clock,
  ChevronLeft,
  ChevronRight,
  Download,
  Search,
  RefreshCw,
  Loader2,
  User,
  TrendingUp,
  Trash2,
  Square,
  Upload,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { evaluationAPI } from "@/services/api";
import toast from "react-hot-toast";
import { clsx } from "clsx";

interface EvalSummary {
  scriptId: string;
  examId: string;
  studentMeta: { name: string; rollNo: string };
  status: string;
  totalScore: number;
  maxPossibleScore: number;
  percentageScore: number;
  questionCount: number;
  evaluatedCount: number;
  needsReview: boolean;
  createdAt: string;
}

type FilterStatus = "" | "COMPLETE" | "EVALUATING" | "IN_REVIEW" | "FLAGGED";

export function EvaluationsListPage() {
  const [items, setItems] = useState<EvalSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [filterStatus, setFilterStatus] = useState<FilterStatus>("");
  const [searchTerm, setSearchTerm] = useState("");
  const [stopScriptId, setStopScriptId] = useState<string | null>(null);
  const [deleteScriptId, setDeleteScriptId] = useState<string | null>(null);
  const perPage = 20;

  const loadData = useCallback(
    async (showRefresh = false) => {
      if (showRefresh) setRefreshing(true);
      else setLoading(true);
      try {
        const params: Record<string, any> = { page, perPage };
        if (filterStatus) params.status = filterStatus;
        const { data } = await evaluationAPI.list(params);
        setItems(data.items);
        setTotal(data.total);
      } catch {
        /* handled */
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [page, perPage, filterStatus]
  );

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    const hasProcessing = items.some((i) => i.status === "EVALUATING");
    if (!hasProcessing) return;
    const interval = setInterval(() => loadData(true), 8000);
    return () => clearInterval(interval);
  }, [items, loadData]);

  const filtered = searchTerm
    ? items.filter(
        (i) =>
          i.studentMeta.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
          i.studentMeta.rollNo.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : items;

  const avgScore =
    filtered.length > 0
      ? filtered.reduce((s, i) => s + i.percentageScore, 0) / filtered.length
      : 0;
  const completedCount = filtered.filter((i) => i.status === "COMPLETE").length;
  const reviewCount = filtered.filter((i) => i.needsReview).length;

  function scoreColor(pct: number) {
    if (pct >= 75) return "text-accent-green";
    if (pct >= 50) return "text-accent-gold";
    if (pct >= 25) return "text-accent-orange";
    return "text-accent-red";
  }

  function scoreBg(pct: number) {
    if (pct >= 75) return "bg-accent-green";
    if (pct >= 50) return "bg-accent-gold";
    if (pct >= 25) return "bg-accent-orange";
    return "bg-accent-red";
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="page-title flex items-center gap-2">
            <Brain className="w-6 h-6 text-accent-purple" />
            Evaluations
          </h2>
          <p className="text-text-secondary text-base mt-1.5">
            AI-graded results for all uploaded answer scripts
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              try {
                const { data } = await evaluationAPI.exportCSV(
                  filterStatus ? { status: filterStatus } : undefined
                );
                const url = URL.createObjectURL(data as Blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "evaluations.csv";
                a.click();
                URL.revokeObjectURL(url);
                toast.success("Export downloaded");
              } catch {
                toast.error("Failed to export");
              }
            }}
            className="btn-secondary flex items-center gap-2"
            title="Export as CSV"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </button>
          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="btn-secondary flex items-center gap-2"
          >
            <RefreshCw className={clsx("w-4 h-4", refreshing && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <GlassCard className="!p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center">
              <BarChart3 className="w-5 h-5 text-accent-blue" />
            </div>
            <div>
              <p className="text-2xl sm:text-3xl font-display font-bold text-text-primary">{total}</p>
              <p className="text-xs text-text-muted">Total Scripts</p>
            </div>
          </div>
        </GlassCard>
        <GlassCard className="!p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-emerald-50 flex items-center justify-center">
              <TrendingUp className="w-5 h-5 text-accent-green" />
            </div>
            <div>
              <p className={clsx("text-2xl sm:text-3xl font-display font-bold", scoreColor(avgScore))}>
                {avgScore.toFixed(1)}%
              </p>
              <p className="text-xs text-text-muted">Avg Score</p>
            </div>
          </div>
        </GlassCard>
        <GlassCard className="!p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-cyan-50 flex items-center justify-center">
              <CheckCircle className="w-5 h-5 text-accent-cyan" />
            </div>
            <div>
              <p className="text-2xl sm:text-3xl font-display font-bold text-accent-cyan">{completedCount}</p>
              <p className="text-xs text-text-muted">Completed</p>
            </div>
          </div>
        </GlassCard>
        <GlassCard className="!p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-amber-50 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-accent-gold" />
            </div>
            <div>
              <p className="text-2xl sm:text-3xl font-display font-bold text-accent-gold">{reviewCount}</p>
              <p className="text-xs text-text-muted">Needs Review</p>
            </div>
          </div>
        </GlassCard>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            type="text"
            placeholder="Search by student name or roll..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="input-field !pl-9 !py-2 text-sm"
          />
        </div>
        <div className="flex gap-1.5">
          {([
            { val: "" as FilterStatus, label: "All" },
            { val: "COMPLETE" as FilterStatus, label: "Completed" },
            { val: "EVALUATING" as FilterStatus, label: "In Progress" },
            { val: "IN_REVIEW" as FilterStatus, label: "In Review" },
            { val: "FLAGGED" as FilterStatus, label: "Flagged" },
          ]).map((f) => (
            <button
              key={f.val}
              onClick={() => { setFilterStatus(f.val); setPage(1); }}
              className={clsx(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                filterStatus === f.val
                  ? "bg-accent-blue text-white"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface border border-border"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Results List */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <GlassCard>
          <EmptyState
            icon={<Brain className="w-8 h-8 sm:w-10 sm:h-10 text-text-muted" />}
            title="No evaluations found"
            description="Upload answer scripts and they'll be evaluated automatically."
            action={
              <Link to="/upload" className="btn-primary inline-flex items-center gap-2">
                <Upload className="w-4 h-4" />
                Upload Scripts
              </Link>
            }
          />
        </GlassCard>
      ) : (
        <div className="space-y-2 overflow-x-auto">
          <div className="grid grid-cols-12 gap-2 sm:gap-4 px-4 py-2 text-xs font-medium text-text-muted uppercase tracking-wider min-w-[640px]">
            <div className="col-span-3">Student</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-2 text-center">Questions</div>
            <div className="col-span-2 text-center">Score</div>
            <div className="col-span-1 text-center">%</div>
            <div className="col-span-2 text-right">Actions</div>
          </div>

          {filtered.map((item) => (
            <GlassCard key={item.scriptId} hover className="!p-0 overflow-hidden min-w-0">
              <div className="grid grid-cols-12 gap-2 sm:gap-4 items-center px-4 py-3 min-w-[640px]">
                <div className="col-span-3 flex items-center gap-3 min-w-0">
                  <div className="w-9 h-9 rounded-full bg-violet-50 flex items-center justify-center flex-shrink-0">
                    <User className="w-4 h-4 text-accent-purple" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-text-primary truncate">
                      {item.studentMeta.name || "Unknown"}
                    </p>
                    <p className="text-xs text-text-muted font-mono truncate">
                      {item.studentMeta.rollNo}
                    </p>
                  </div>
                </div>

                <div className="col-span-2 flex items-center gap-2">
                  <StatusBadge status={item.status} />
                  {item.needsReview && (
                    <AlertTriangle className="w-3.5 h-3.5 text-accent-gold" />
                  )}
                </div>

                <div className="col-span-2 text-center">
                  <span className="text-sm font-mono text-text-primary">
                    {item.evaluatedCount}/{item.questionCount}
                  </span>
                  {item.status === "EVALUATING" && (
                    <Loader2 className="w-3 h-3 animate-spin text-accent-blue inline ml-1.5" />
                  )}
                </div>

                <div className="col-span-2 text-center">
                  <span className={clsx("text-lg font-display font-bold", scoreColor(item.percentageScore))}>
                    {item.totalScore}
                  </span>
                  <span className="text-xs text-text-muted">/{item.maxPossibleScore}</span>
                </div>

                <div className="col-span-1">
                  <div className="text-center">
                    <span className={clsx("text-sm font-bold font-mono", scoreColor(item.percentageScore))}>
                      {item.percentageScore}%
                    </span>
                    <div className="w-full h-1.5 bg-surface rounded-full mt-1 overflow-hidden">
                      <div
                        className={clsx("h-full rounded-full transition-all duration-700", scoreBg(item.percentageScore))}
                        style={{ width: `${Math.min(item.percentageScore, 100)}%` }}
                      />
                    </div>
                  </div>
                </div>

                <div className="col-span-2 flex justify-end gap-2">
                  {item.status === "EVALUATING" ? (
                    <>
                      <span className="flex items-center gap-1.5 text-xs text-accent-blue">
                        <Clock className="w-3.5 h-3.5 animate-pulse" />
                        Processing...
                      </span>
                      <button
                        onClick={() => setStopScriptId(item.scriptId)}
                        className="btn-secondary text-xs !px-2.5 !py-1.5 text-accent-red hover:bg-red-50"
                        title="Stop evaluation"
                      >
                        <Square className="w-3.5 h-3.5" />
                      </button>
                    </>
                  ) : (
                    <Link
                      to={`/scripts/${item.scriptId}/evaluation`}
                      className="btn-primary text-xs !px-3 !py-1.5 flex items-center gap-1"
                    >
                      <BarChart3 className="w-3.5 h-3.5" />
                      View Details
                    </Link>
                  )}
                  <button
                    onClick={() => setDeleteScriptId(item.scriptId)}
                    className="btn-secondary text-xs !px-2.5 !py-1.5 text-accent-red hover:bg-red-50"
                    title="Delete script"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </GlassCard>
          ))}
        </div>
      )}

      {total > perPage && (
        <div className="flex items-center justify-center gap-4 pt-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="btn-secondary !px-3 !py-1.5"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm text-text-secondary font-mono">
            Page {page} of {Math.ceil(total / perPage)}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page * perPage >= total}
            className="btn-secondary !px-3 !py-1.5"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}

      <ConfirmModal
        isOpen={!!stopScriptId}
        onClose={() => setStopScriptId(null)}
        onConfirm={async () => {
          if (!stopScriptId) return;
          try {
            await evaluationAPI.stopEvaluation(stopScriptId);
            toast.success("Evaluation stopped");
            setStopScriptId(null);
            loadData(true);
          } catch {
            toast.error("Failed to stop evaluation");
          }
        }}
        title="Stop evaluation"
        message="Stop this evaluation? Remaining questions will not be scored."
        confirmLabel="Stop"
        cancelLabel="Cancel"
        variant="danger"
      />
      <ConfirmModal
        isOpen={!!deleteScriptId}
        onClose={() => setDeleteScriptId(null)}
        onConfirm={async () => {
          if (!deleteScriptId) return;
          try {
            await evaluationAPI.deleteScript(deleteScriptId);
            toast.success("Script deleted");
            setDeleteScriptId(null);
            loadData(true);
          } catch {
            toast.error("Failed to delete script");
          }
        }}
        title="Delete script"
        message="Delete this script and all its evaluations? This cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
      />
    </div>
  );
}
