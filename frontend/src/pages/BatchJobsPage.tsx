import { useCallback, useEffect, useState } from "react";
import {
  Layers,
  RefreshCw,
  CheckCircle,
  XCircle,
  Loader2,
  FileText,
  BookOpen,
  AlertCircle,
  Trash2,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { batchAPI } from "@/services/api";
import { clsx } from "clsx";
import toast from "react-hot-toast";

interface JobResult {
  filename: string;
  status: "SUCCESS" | "FAILED";
  entityId?: string;
  error?: string;
}

interface BatchJob {
  id: string;
  type: "EXAM_BATCH" | "SCRIPT_BATCH";
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  totalFiles: number;
  processedFiles: number;
  failedFiles: number;
  results: JobResult[];
  createdAt: string;
  updatedAt: string;
}

export function BatchJobsPage() {
  const [jobs, setJobs] = useState<BatchJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadJobs = useCallback(async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    else setLoading(true);
    try {
      const { data } = await batchAPI.listJobs();
      setJobs(data.items);
    } catch (err) {
      toast.error("Failed to load batch jobs");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const handleDelete = async (jobId: string) => {
    if (!window.confirm("Are you sure you want to delete this batch job record?")) return;

    try {
      await batchAPI.deleteJob(jobId);
      toast.success("Batch job deleted");
      setJobs(prev => prev.filter(j => j.id !== jobId));
    } catch (err) {
      toast.error("Failed to delete batch job");
    }
  };

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Poll if any job is still running
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === "PENDING" || j.status === "RUNNING");
    if (!hasActive) return;

    const interval = setInterval(() => loadJobs(true), 5000);
    return () => clearInterval(interval);
  }, [jobs, loadJobs]);

  function getProgress(job: BatchJob) {
    if (job.totalFiles === 0) return 0;
    return Math.round((job.processedFiles / job.totalFiles) * 100);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="page-title flex items-center gap-2">
            <Layers className="w-6 h-6 text-accent-blue" />
            Batch Jobs
          </h2>
          <p className="text-text-secondary text-base mt-1.5">
            Monitor background processing for ZIP uploads
          </p>
        </div>
        <button
          onClick={() => loadJobs(true)}
          disabled={refreshing}
          className="btn-secondary flex items-center gap-2"
        >
          <RefreshCw className={clsx("w-4 h-4", refreshing && "animate-spin")} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <GlassCard className="py-12 flex flex-col items-center justify-center text-center">
          <Layers className="w-12 h-12 text-text-muted mb-4 opacity-20" />
          <h3 className="text-lg font-display font-medium text-text-primary">No batch jobs found</h3>
          <p className="text-text-muted max-w-sm mt-2">
            Upload a ZIP folder in the Exams or Upload pages to start a batch process.
          </p>
        </GlassCard>
      ) : (
        <div className="space-y-4">
          {jobs.map((job) => (
            <GlassCard key={job.id} className="overflow-hidden border-l-4 border-l-accent-blue">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-start gap-4">
                  <div className={clsx(
                    "p-3 rounded-xl",
                    job.type === "EXAM_BATCH" ? "bg-blue-50 text-accent-blue" : "bg-purple-50 text-accent-cyan"
                  )}>
                    {job.type === "EXAM_BATCH" ? <BookOpen className="w-6 h-6" /> : <FileText className="w-6 h-6" />}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-display font-bold text-text-primary">
                        {job.type === "EXAM_BATCH" ? "Exam Batch Upload" : "Script Batch Upload"}
                      </h3>
                      <StatusBadge status={job.status} />
                    </div>
                    <p className="text-xs text-text-muted mt-1 font-mono">
                      ID: {job.id.split("-")[0]}... • {new Date(job.createdAt).toLocaleString()}
                    </p>
                  </div>
                </div>

                <div className="flex-1 max-w-md">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-text-secondary">
                      {job.processedFiles} / {job.totalFiles} Files Processed
                    </span>
                    <span className="text-sm font-bold text-accent-blue">
                      {getProgress(job)}%
                    </span>
                  </div>
                  <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={clsx(
                        "h-full transition-all duration-500 rounded-full",
                        job.status === "FAILED" ? "bg-accent-red" : "bg-accent-blue"
                      )}
                      style={{ width: `${getProgress(job)}%` }}
                    />
                  </div>
                </div>

                <div className="flex items-center gap-4 min-w-[140px] justify-end">
                   {job.failedFiles > 0 && (
                     <div className="flex items-center gap-1.5 text-accent-red text-sm font-medium">
                        <AlertCircle className="w-4 h-4" />
                        {job.failedFiles} Failed
                     </div>
                   )}
                   {job.status === "COMPLETED" && (
                      <div className="text-accent-green flex items-center gap-1.5 text-sm font-medium">
                        <CheckCircle className="w-4 h-4" />
                        Done
                      </div>
                   )}
                   {(job.status === "RUNNING" || job.status === "PENDING") && (
                      <div className="text-accent-blue flex items-center gap-1.5 text-sm font-medium">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        In Progress
                      </div>
                   )}
                   <button
                     onClick={() => handleDelete(job.id)}
                     className="p-2 text-text-muted hover:text-accent-red hover:bg-red-50 rounded-lg transition-colors"
                     title="Delete history"
                   >
                     <Trash2 className="w-4 h-4" />
                   </button>
                </div>
              </div>

              {/* Collapsible Results or simple summary */}
              {job.results && job.results.length > 0 && (
                <div className="mt-4 pt-4 border-t border-slate-100 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
                  {job.results.slice(0, 6).map((res, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs truncate p-2 rounded bg-slate-50 border border-slate-100">
                      {res.status === "SUCCESS" ? (
                        <CheckCircle className="w-3 h-3 text-accent-green flex-shrink-0" />
                      ) : (
                        <XCircle className="w-3 h-3 text-accent-red flex-shrink-0" />
                      )}
                      <span className="truncate text-text-secondary flex-1" title={res.filename}>
                        {res.filename}
                      </span>
                    </div>
                  ))}
                  {job.results.length > 6 && (
                    <div className="text-xs text-text-muted p-2 italic">
                      + {job.results.length - 6} more files...
                    </div>
                  )}
                </div>
              )}
            </GlassCard>
          ))}
        </div>
      )}
    </div>
  );
}
