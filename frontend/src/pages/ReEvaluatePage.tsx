import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Loader2, FileText, ArrowRight } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { uploadAPI, ocrAPI } from "@/services/api";
import toast from "react-hot-toast";

interface ScriptOption {
  id: string;
  label: string;
}

export function ReEvaluatePage() {
  const navigate = useNavigate();
  const [scripts, setScripts] = useState<ScriptOption[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const { data } = await uploadAPI.list({ page: 1, perPage: 200 });
        const allowed = new Set([
          "OCR_COMPLETE",
          "SEGMENTED",
          "EVALUATING",
          "EVALUATED",
          "COMPLETE",
          "IN_REVIEW",
          "FLAGGED",
        ]);
        const eligible = data.items.filter((s) => allowed.has(s.uploadStatus));
        setScripts(
          eligible.map((s) => ({
            id: s.id,
            label: `${s.studentMeta?.name || "—"} · ${s.studentMeta?.rollNo || "—"} · ${s.originalFilename || "script"} (${s.uploadStatus})`,
          }))
        );
        const first = eligible[0];
        if (first && !selectedId) setSelectedId(first.id);
      } catch {
        toast.error("Failed to load scripts");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  async function handleReEvaluate() {
    if (!selectedId) {
      toast.error("Please select a script");
      return;
    }
    setSubmitting(true);
    try {
      await ocrAPI.reSegment(selectedId);
      toast.success("Re-evaluation started. Redirecting to Scripts to track progress.");
      navigate(`/scripts?re-evaluated=${selectedId}`);
    } catch {
      toast.error("Failed to start re-evaluation");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <div>
        <h2 className="page-title flex items-center gap-2">
          <RefreshCw className="w-6 h-6 text-accent-blue" />
          Re-evaluate Script
        </h2>
        <p className="text-text-secondary text-base mt-1.5">
          Re-run segmentation and full evaluation using existing OCR. No need to re-upload the answer paper.
        </p>
      </div>

      <GlassCard>
        <h3 className="font-display font-semibold text-text-primary flex items-center gap-2 mb-1">
          <FileText className="w-4 h-4 text-accent-orange" />
          Select a script
        </h3>
        <p className="text-sm text-text-secondary mb-4">
          Choose a script that already has OCR results. The pipeline will start from segmentation, then run evaluation. You can track progress on the Scripts page.
        </p>

        {loading ? (
          <div className="flex items-center gap-2 text-text-muted py-4">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading scripts…
          </div>
        ) : (
          <>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              className="input-field w-full mb-4"
            >
              <option value="">Select a script…</option>
              {scripts.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
            {scripts.length === 0 && (
              <p className="text-sm text-text-muted mb-4">
                No scripts with OCR results. Upload and process an answer paper first.
              </p>
            )}
            <div className="flex flex-col sm:flex-row gap-3">
              <button
                onClick={handleReEvaluate}
                disabled={submitting || !selectedId || scripts.length === 0}
                className="btn-primary flex items-center justify-center gap-2"
              >
                {submitting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
                Start re-evaluation
              </button>
              <button
                onClick={() => navigate("/scripts")}
                className="btn-secondary flex items-center justify-center gap-2"
              >
                View Scripts
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </>
        )}
      </GlassCard>

      <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-4 text-sm text-text-secondary">
        <p className="font-medium text-text-primary mb-1">What happens next</p>
        <p>
          After you click &quot;Start re-evaluation&quot;, you&apos;ll be taken to the Scripts page. The page will auto-refresh so you can see the pipeline move from <strong>Segmenting</strong> → <strong>Segmented</strong> → <strong>Evaluating</strong> → <strong>Complete</strong>.
        </p>
      </div>
    </div>
  );
}
