import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  FileText,
  Eye,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Loader2,
  AlertCircle,
  Clock,
  XCircle,
  Trash2,
  Square,
  Upload,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { PipelineTracker } from "@/components/dashboard/PipelineTracker";
import { uploadAPI, evaluationAPI } from "@/services/api";
import type { UploadedScript } from "@/types";
import { clsx } from "clsx";
import toast from "react-hot-toast";
import { formatDistanceToNow } from "date-fns";

const TERMINAL_STATUSES = new Set(["EVALUATED", "COMPLETE", "FAILED", "FLAGGED", "IN_REVIEW"]);

/** Human-readable stage for re-evaluation banner */
function getStageLabel(status: string): string {
  const map: Record<string, string> = {
    UPLOADED: "Uploaded",
    PROCESSING: "OCR",
    OCR_COMPLETE: "Segmenting",
    SEGMENTED: "Segmented",
    EVALUATING: "Evaluating",
    EVALUATED: "Complete",
    COMPLETE: "Complete",
    IN_REVIEW: "Complete — review recommended",
    FLAGGED: "Flagged",
    FAILED: "Failed",
  };
  return map[status] ?? status;
}

export function ScriptsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const reEvaluatedId = searchParams.get("re-evaluated");
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [scripts, setScripts] = useState<UploadedScript[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [stopScriptId, setStopScriptId] = useState<string | null>(null);
  const [deleteUploadId, setDeleteUploadId] = useState<string | null>(null);
  const perPage = 20;

  const loadData = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      else setRefreshing(true);
      try {
        const { data } = await uploadAPI.list({ page, perPage });
        setScripts(data.items);
        setTotal(data.total);
      } catch {
        /* handled */
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [page, perPage]
  );

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-refresh when any script is in progress (or when we're tracking a re-evaluation)
  useEffect(() => {
    const hasProcessing = scripts.some((s) => !TERMINAL_STATUSES.has(s.uploadStatus));
    const trackingReEval = !!reEvaluatedId;
    if (!hasProcessing && !trackingReEval) return;
    const inOcrOrSegmenting = scripts.some(
      (s) => s.uploadStatus === "PROCESSING" || s.uploadStatus === "OCR_COMPLETE"
    );
    const intervalMs = inOcrOrSegmenting ? 3000 : 5000;
    const interval = setInterval(() => loadData(true), intervalMs);
    return () => clearInterval(interval);
  }, [scripts, loadData, reEvaluatedId]);

  // Scroll re-evaluated script into view when it appears
  useEffect(() => {
    if (!reEvaluatedId || !scripts.some((s) => s.id === reEvaluatedId)) return;
    const el = cardRefs.current[reEvaluatedId];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [reEvaluatedId, scripts]);

  function statusIcon(status: string) {
    switch (status) {
      case "EVALUATED":
      case "COMPLETE":
        return <BarChart3 className="w-4 h-4 text-accent-green" />;
      case "IN_REVIEW":
        return <AlertCircle className="w-4 h-4 text-accent-gold" />;
      case "EVALUATING":
        return <Loader2 className="w-4 h-4 animate-spin text-accent-purple" />;
      case "FAILED":
        return <XCircle className="w-4 h-4 text-accent-red" />;
      case "FLAGGED":
        return <XCircle className="w-4 h-4 text-accent-red" />;
      default:
        return <Clock className="w-4 h-4 text-accent-cyan animate-pulse" />;
    }
  }

  return (
    <div className="space-y-6">
      {reEvaluatedId && (() => {
        const reEvalScript = scripts.find((s) => s.id === reEvaluatedId);
        const stageLabel = reEvalScript ? getStageLabel(reEvalScript.uploadStatus) : null;
        const isDone = reEvalScript && TERMINAL_STATUSES.has(reEvalScript.uploadStatus);
        const needsReview = reEvalScript?.uploadStatus === "IN_REVIEW";
        const isInProgress = reEvalScript && !TERMINAL_STATUSES.has(reEvalScript.uploadStatus);
        return (
        <div
          className={clsx(
            "flex items-start gap-3 p-4 rounded-xl border text-sm shadow-sm",
            isInProgress && "border-blue-200 bg-blue-50",
            isDone && !needsReview && "border-emerald-200 bg-emerald-50",
            needsReview && "border-amber-200 bg-amber-50"
          )}
          role="status"
        >
          <div className={clsx(
            "w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0",
            isInProgress && "bg-blue-100",
            isDone && !needsReview && "bg-emerald-100",
            needsReview && "bg-amber-100"
          )}>
            {isInProgress ? (
              <Loader2 className="w-5 h-5 text-accent-blue animate-spin" />
            ) : needsReview ? (
              <AlertCircle className="w-5 h-5 text-amber-600" />
            ) : (
              <BarChart3 className="w-5 h-5 text-accent-green" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-text-primary">
              {isInProgress
                ? "Re-evaluation in progress"
                : needsReview
                  ? "Re-evaluation finished — review recommended"
                  : "Re-evaluation complete"}
            </p>
            {stageLabel && (
              <p className={clsx(
                "font-medium mt-1",
                isInProgress ? "text-accent-blue" : needsReview ? "text-amber-700" : "text-accent-green"
              )}>
                Current stage: {stageLabel}
              </p>
            )}
            <p className="text-text-secondary mt-0.5">
              {isInProgress
                ? "Pipeline is running from segmentation → evaluation. This page auto-refreshes. When done, open Results below."
                : needsReview
                  ? "Some answers need human review. Open Results to see which questions."
                  : "Open Results below to view scores."}
            </p>
            <button
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                next.delete("re-evaluated");
                setSearchParams(next);
              }}
              className="mt-2 text-accent-blue hover:underline font-medium text-sm"
            >
              Dismiss
            </button>
          </div>
        </div>
        );
      })()}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="page-title flex items-center gap-2">
            <FileText className="w-6 h-6 text-accent-orange" />
            Scripts
          </h2>
          <p className="text-text-secondary text-base mt-1.5">
            Uploaded answer scripts and their processing pipeline
          </p>
        </div>
        <div className="flex items-center gap-3">
          {scripts.some((s) => !TERMINAL_STATUSES.has(s.uploadStatus)) && (
            <span className="flex items-center gap-1.5 text-xs text-accent-blue bg-blue-50 px-3 py-1.5 rounded-full border border-blue-200">
              <Loader2 className="w-3 h-3 animate-spin" />
              Auto-refreshing
            </span>
          )}
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

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : scripts.length === 0 ? (
        <GlassCard>
          <EmptyState
            icon={<FileText className="w-8 h-8 sm:w-10 sm:h-10 text-text-muted" />}
            title="No scripts uploaded yet"
            description="Upload answer booklets (PDF or images) or submit typed answers to get started."
            action={
              <Link to="/upload" className="btn-primary inline-flex items-center gap-2">
                <Upload className="w-4 h-4" />
                Upload Scripts
              </Link>
            }
          />
        </GlassCard>
      ) : (
        <div className="space-y-3">
          {scripts.map((s) => (
            <div
              key={s.id}
              ref={(el) => { cardRefs.current[s.id] = el; }}
              className={clsx(reEvaluatedId === s.id && "ring-2 ring-accent-blue ring-offset-2 rounded-xl")}
            >
            <GlassCard hover className="!p-0 overflow-hidden">
              <div className="p-4">
                <div className="flex items-start gap-4">
                  <div className="relative flex-shrink-0">
                    <div className="w-11 h-11 rounded-lg bg-orange-50 flex items-center justify-center">
                      <FileText className="w-5 h-5 text-accent-orange" />
                    </div>
                    <div className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-card border border-border flex items-center justify-center">
                      {statusIcon(s.uploadStatus)}
                    </div>
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <p className="font-medium text-sm text-text-primary truncate">{s.originalFilename}</p>
                      <StatusBadge status={s.uploadStatus} />
                    </div>
                    <div className="flex items-center gap-4 text-xs text-text-muted">
                      <span>{s.studentMeta?.name || "Unknown"}</span>
                      <span className="font-mono">{s.studentMeta?.rollNo || "-"}</span>
                      <span>{(s.fileSizeBytes / 1024 / 1024).toFixed(1)} MB</span>
                      {s.pageCount && <span>{s.pageCount} page{s.pageCount > 1 ? "s" : ""}</span>}
                      <span>
                        {s.createdAt ? formatDistanceToNow(new Date(s.createdAt), { addSuffix: true }) : ""}
                      </span>
                    </div>

                    <div className="mt-3">
                      <PipelineTracker currentStatus={s.uploadStatus} />
                    </div>

                    {s.failureReason && (
                      <div className="mt-2 flex items-center gap-2 text-xs text-accent-red bg-red-50 border border-red-200 rounded-lg px-3 py-1.5">
                        <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                        {s.failureReason}
                      </div>
                    )}
                    {s.uploadStatus === "IN_REVIEW" && (
                      <p className="mt-2 text-xs text-text-muted">
                        One or more answers are recommended for human review. Open Results to see which questions.
                      </p>
                    )}
                  </div>

                  <div className="flex flex-col gap-1.5 flex-shrink-0">
                    {(s.uploadStatus === "EVALUATED" || s.uploadStatus === "COMPLETE" || s.uploadStatus === "FLAGGED" || s.uploadStatus === "IN_REVIEW") && s.scriptId && (
                      <Link
                        to={`/scripts/${s.scriptId}/evaluation`}
                        className="btn-primary text-xs !px-3 !py-1.5 flex items-center gap-1.5 whitespace-nowrap"
                      >
                        <BarChart3 className="w-3.5 h-3.5" />
                        Results
                      </Link>
                    )}
                    {s.uploadStatus === "EVALUATING" && s.scriptId && (
                      <button
                        onClick={() => setStopScriptId(s.scriptId!)}
                        className="btn-secondary text-xs !px-3 !py-1.5 flex items-center gap-1.5 text-accent-red hover:bg-red-50"
                        title="Stop evaluation"
                      >
                        <Square className="w-3.5 h-3.5" />
                        Stop
                      </button>
                    )}
                    <Link
                      to={`/scripts/${s.id}/ocr`}
                      className="btn-secondary text-xs !px-3 !py-1.5 flex items-center gap-1.5 whitespace-nowrap"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      OCR Review
                    </Link>
                    <button
                      onClick={() => setDeleteUploadId(s.id)}
                      className="btn-secondary text-xs !px-3 !py-1.5 flex items-center gap-1.5 text-accent-red hover:bg-red-50"
                      title="Delete upload"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            </GlassCard>
            </div>
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
        isOpen={!!deleteUploadId}
        onClose={() => setDeleteUploadId(null)}
        onConfirm={async () => {
          if (!deleteUploadId) return;
          try {
            await uploadAPI.delete(deleteUploadId);
            toast.success("Upload deleted");
            setDeleteUploadId(null);
            loadData(true);
          } catch {
            toast.error("Failed to delete upload");
          }
        }}
        title="Delete upload"
        message="Delete this upload and all related scripts and evaluations? This cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
      />
    </div>
  );
}
