import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  ArrowLeft,
  Loader2,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Copy,
  Check,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { OCRConfidenceMeter } from "@/components/dashboard/OCRConfidenceMeter";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ocrAPI } from "@/services/api";
import type { OCRPage } from "@/types";
import toast from "react-hot-toast";
import { clsx } from "clsx";

export function OCRReviewPage() {
  const { scriptId } = useParams<{ scriptId: string }>();
  const navigate = useNavigate();
  const [pages, setPages] = useState<OCRPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(0);
  const [signedUrl, setSignedUrl] = useState("");
  const [reSegmenting, setReSegmenting] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [imgError, setImgError] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!scriptId) return;
    setLoading(true);
    Promise.all([
      ocrAPI.getPages(scriptId),
      ocrAPI.getSignedUrl(scriptId),
    ])
      .then(([pagesRes, urlRes]) => {
        setPages(pagesRes.data.pages);
        setSignedUrl(urlRes.data.signedUrl);
      })
      .catch(() => toast.error("Failed to load OCR data"))
      .finally(() => setLoading(false));
  }, [scriptId]);

  useEffect(() => {
    setImgError(false);
  }, [currentPage]);

  async function handleReSegment() {
    if (!scriptId) return;
    setReSegmenting(true);
    try {
      await ocrAPI.reSegment(scriptId);
      toast.success("Re-segmentation triggered — check scripts page for updates");
    } catch {
      toast.error("Failed to trigger re-segmentation");
    } finally {
      setReSegmenting(false);
    }
  }

  function handleCopy() {
    const text = pages[currentPage]?.extractedText ?? "";
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Loader2 className="w-10 h-10 animate-spin text-accent-blue mb-4" />
        <p className="text-text-secondary text-sm">Loading OCR results...</p>
      </div>
    );
  }

  const page = pages[currentPage];
  const extractedText = page?.extractedText ?? "";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-text-muted hover:text-text-primary transition-colors mb-2">
            <ArrowLeft className="w-4 h-4" />
            Back to scripts
          </button>
          <h2 className="page-title">OCR Review</h2>
          <p className="text-text-secondary text-base mt-1">
            Review extracted text from the original document
          </p>
        </div>
        <button
          onClick={handleReSegment}
          disabled={reSegmenting}
          className="btn-secondary flex items-center gap-2 text-sm"
        >
          <RefreshCw className={clsx("w-4 h-4", reSegmenting && "animate-spin")} />
          Re-Segment
        </button>
      </div>

      {page && (
        <div className="flex items-center gap-5 bg-card border border-border rounded-xl shadow-card px-5 py-3">
          <OCRConfidenceMeter confidence={page.confidenceScore} size={48} />
          <div className="h-8 w-px bg-border" />
          <div>
            <p className="text-[10px] text-text-muted uppercase tracking-wider">Provider</p>
            <p className="text-sm font-mono text-accent-blue font-medium">{page.provider}</p>
          </div>
          <div className="h-8 w-px bg-border" />
          <div>
            <p className="text-[10px] text-text-muted uppercase tracking-wider">Processing</p>
            <p className="text-sm font-mono text-text-primary">{page.processingMs}ms</p>
          </div>
          <div className="h-8 w-px bg-border" />
          <div className="flex gap-1.5">
            {page.qualityFlags.map((f) => (
              <StatusBadge key={f} status={f} />
            ))}
            {page.qualityFlags.length === 0 && (
              <span className="badge-success">Good Quality</span>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" style={{ minHeight: "70vh" }}>
        <GlassCard className="flex flex-col !p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-display font-semibold text-sm text-text-primary">Original Document</h3>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))}
                className="btn-secondary !px-1.5 !py-1"
                title="Zoom out"
              >
                <ZoomOut className="w-3.5 h-3.5" />
              </button>
              <span className="text-xs text-text-muted font-mono w-10 text-center">
                {(zoom * 100).toFixed(0)}%
              </span>
              <button
                onClick={() => setZoom((z) => Math.min(3, z + 0.25))}
                className="btn-secondary !px-1.5 !py-1"
                title="Zoom in"
              >
                <ZoomIn className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setZoom(1)}
                className="btn-secondary !px-1.5 !py-1"
                title="Reset zoom"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
              <div className="w-px h-5 bg-border mx-1" />
              <button
                onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
                disabled={currentPage === 0}
                className="btn-secondary !px-1.5 !py-1"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="text-xs text-text-secondary font-mono">
                {currentPage + 1}/{pages.length}
              </span>
              <button
                onClick={() => setCurrentPage((p) => Math.min(pages.length - 1, p + 1))}
                disabled={currentPage === pages.length - 1}
                className="btn-secondary !px-1.5 !py-1"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          <div className="flex-1 bg-surface rounded-lg overflow-auto flex items-center justify-center">
            {signedUrl && !imgError ? (
              <img
                src={signedUrl}
                alt={`Page ${currentPage + 1}`}
                className="max-w-full object-contain rounded transition-transform duration-200"
                style={{ transform: `scale(${zoom})`, transformOrigin: "center" }}
                onError={() => setImgError(true)}
              />
            ) : (
              <div className="text-center text-text-muted py-12">
                <p className="text-sm">
                  {imgError ? "Failed to load image preview" : "No preview available"}
                </p>
                <p className="text-xs mt-1 text-text-muted">
                  The extracted text is shown on the right
                </p>
              </div>
            )}
          </div>
        </GlassCard>

        <GlassCard className="flex flex-col !p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-display font-semibold text-sm text-text-primary">Extracted Text</h3>
            <div className="flex items-center gap-3">
              <span className="text-xs text-text-muted font-mono">
                {extractedText.length} chars
              </span>
              <button
                onClick={handleCopy}
                className="btn-secondary !px-2 !py-1 flex items-center gap-1.5 text-xs"
                title="Copy text"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-accent-green" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
          <div className="flex-1 bg-surface border border-border rounded-lg p-4 overflow-auto">
            <pre className="text-sm font-mono text-text-primary whitespace-pre-wrap leading-relaxed">
              {extractedText || <span className="text-text-muted italic">No text extracted for this page.</span>}
            </pre>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
