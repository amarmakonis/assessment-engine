import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { PipelineTracker } from "@/components/dashboard/PipelineTracker";
import { uploadAPI } from "@/services/api";
import type { UploadedScript } from "@/types";
import { clsx } from "clsx";
import { formatDistanceToNow } from "date-fns";

const TERMINAL_STATUSES = new Set(["EVALUATED", "COMPLETE", "FAILED", "FLAGGED"]);

export function ScriptsPage() {
  const [scripts, setScripts] = useState<UploadedScript[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
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

  useEffect(() => {
    const hasProcessing = scripts.some((s) => !TERMINAL_STATUSES.has(s.uploadStatus));
    if (!hasProcessing) return;
    const interval = setInterval(() => loadData(true), 5000);
    return () => clearInterval(interval);
  }, [scripts, loadData]);

  function statusIcon(status: string) {
    switch (status) {
      case "EVALUATED":
      case "COMPLETE":
        return <BarChart3 className="w-4 h-4 text-accent-green" />;
      case "EVALUATING":
        return <Loader2 className="w-4 h-4 animate-spin text-accent-purple" />;
      case "FAILED":
        return <XCircle className="w-4 h-4 text-accent-red" />;
      case "FLAGGED":
        return <AlertCircle className="w-4 h-4 text-accent-gold" />;
      default:
        return <Clock className="w-4 h-4 text-accent-cyan animate-pulse" />;
    }
  }

  return (
    <div className="space-y-6">
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
        <div className="flex flex-col items-center justify-center py-20">
          <Loader2 className="w-10 h-10 animate-spin text-accent-blue mb-4" />
          <p className="text-text-muted text-sm">Loading scripts...</p>
        </div>
      ) : scripts.length === 0 ? (
        <GlassCard>
          <div className="text-center py-16">
            <FileText className="w-12 h-12 text-text-muted mx-auto mb-4 opacity-50" />
            <p className="text-text-secondary font-medium">No scripts uploaded yet</p>
            <p className="text-text-muted text-sm mt-1">
              Go to Upload Scripts to get started
            </p>
            <Link to="/upload" className="btn-primary inline-flex items-center gap-2 mt-4 text-sm">
              Upload Now
            </Link>
          </div>
        </GlassCard>
      ) : (
        <div className="space-y-3">
          {scripts.map((s) => (
            <GlassCard key={s.id} hover className="!p-0 overflow-hidden">
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
                  </div>

                  <div className="flex flex-col gap-1.5 flex-shrink-0">
                    {(s.uploadStatus === "EVALUATED" || s.uploadStatus === "COMPLETE" || s.uploadStatus === "FLAGGED") && s.scriptId && (
                      <Link
                        to={`/scripts/${s.scriptId}/evaluation`}
                        className="btn-primary text-xs !px-3 !py-1.5 flex items-center gap-1.5 whitespace-nowrap"
                      >
                        <BarChart3 className="w-3.5 h-3.5" />
                        Results
                      </Link>
                    )}
                    <Link
                      to={`/scripts/${s.id}/ocr`}
                      className="btn-secondary text-xs !px-3 !py-1.5 flex items-center gap-1.5 whitespace-nowrap"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      OCR Review
                    </Link>
                  </div>
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
    </div>
  );
}
