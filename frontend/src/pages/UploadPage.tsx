import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Link } from "react-router-dom";
import {
  Upload,
  FileUp,
  CheckCircle,
  XCircle,
  Loader2,
  ArrowRight,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { uploadAPI, examAPI } from "@/services/api";
import toast from "react-hot-toast";
import { clsx } from "clsx";

interface UploadResult {
  filename: string;
  uploadedScriptId?: string;
  status: string;
  reason?: string;
}

interface ExamOption {
  id: string;
  title: string;
  subject: string;
  totalMarks: number;
}

export function UploadPage() {
  const [exams, setExams] = useState<ExamOption[]>([]);
  const [examId, setExamId] = useState("");
  const [studentName, setStudentName] = useState("");
  const [studentRoll, setStudentRoll] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[]>([]);

  useEffect(() => {
    examAPI.list().then(({ data }) => setExams(data.items)).catch(() => {});
  }, []);

  const onDrop = useCallback((accepted: File[]) => {
    setFiles((prev) => [...prev, ...accepted]);
    setResults([]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "image/jpeg": [".jpg", ".jpeg"],
      "image/png": [".png"],
    },
    maxSize: 50 * 1024 * 1024,
  });

  async function handleUpload() {
    if (!examId) {
      toast.error("Please select an exam first");
      return;
    }
    if (files.length === 0) {
      toast.error("Please select files to upload");
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append("examId", examId);
    formData.append("studentName", studentName);
    formData.append("studentRollNo", studentRoll);
    files.forEach((f) => formData.append("files", f));

    try {
      const { data } = await uploadAPI.upload(formData);
      setResults(data.results);
      const accepted = data.results.filter((r) => r.status === "ACCEPTED").length;
      toast.success(`${accepted}/${data.totalFiles} files uploaded successfully`);
      setFiles([]);
    } catch {
      toast.error("Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function resetAll() {
    setResults([]);
    setFiles([]);
    setStudentName("");
    setStudentRoll("");
  }

  const acceptedCount = results.filter((r) => r.status === "ACCEPTED").length;

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h2 className="page-title flex items-center gap-2">
          <Upload className="w-6 h-6 text-accent-green" />
          Upload Scripts
        </h2>
        <p className="text-text-secondary text-base mt-1.5">
          Upload student answer scripts for OCR processing and AI evaluation
        </p>
      </div>

      {results.length > 0 ? (
        <GlassCard>
          <div className="text-center mb-6">
            <div className="w-16 h-16 rounded-full bg-emerald-50 border border-emerald-200 flex items-center justify-center mx-auto mb-4">
              <CheckCircle className="w-8 h-8 text-accent-green" />
            </div>
            <h3 className="text-lg font-display font-bold text-text-primary">
              Upload Complete
            </h3>
            <p className="text-text-secondary text-sm mt-1">
              {acceptedCount} of {results.length} files accepted and queued for processing
            </p>
          </div>

          <div className="space-y-2 mb-6">
            {results.map((r, i) => (
              <div
                key={i}
                className={clsx(
                  "flex items-center gap-3 p-3 rounded-lg border",
                  r.status === "ACCEPTED"
                    ? "bg-emerald-50 border-emerald-200"
                    : "bg-red-50 border-red-200"
                )}
              >
                {r.status === "ACCEPTED" ? (
                  <CheckCircle className="w-4.5 h-4.5 text-accent-green flex-shrink-0" />
                ) : (
                  <XCircle className="w-4.5 h-4.5 text-accent-red flex-shrink-0" />
                )}
                <span className="flex-1 text-sm text-text-primary truncate">{r.filename}</span>
                <StatusBadge status={r.status} />
              </div>
            ))}
          </div>

          <div className="flex gap-3">
            <button onClick={resetAll} className="btn-secondary flex-1">
              Upload More
            </button>
            <Link to="/scripts" className="btn-primary flex-1 flex items-center justify-center gap-2">
              View Scripts
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </GlassCard>
      ) : (
        <GlassCard>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Exam *
              </label>
              <select
                value={examId}
                onChange={(e) => setExamId(e.target.value)}
                className="input-field"
              >
                <option value="">Select an exam...</option>
                {exams.map((ex) => (
                  <option key={ex.id} value={ex.id}>
                    {ex.title} — {ex.subject} ({ex.totalMarks} marks)
                  </option>
                ))}
              </select>
              {exams.length === 0 && (
                <p className="text-xs text-accent-gold mt-1.5">
                  No exams found — <Link to="/exams" className="underline hover:text-accent-gold/80">create one first</Link>
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Student Name
              </label>
              <input
                type="text"
                value={studentName}
                onChange={(e) => setStudentName(e.target.value)}
                className="input-field"
                placeholder="e.g. Amar Singh"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Roll Number
              </label>
              <input
                type="text"
                value={studentRoll}
                onChange={(e) => setStudentRoll(e.target.value)}
                className="input-field"
                placeholder="e.g. 2024CS001"
              />
            </div>
          </div>

          <div
            {...getRootProps()}
            className={clsx(
              "border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-all duration-300",
              isDragActive
                ? "border-accent-blue bg-blue-50"
                : "border-border hover:border-accent-blue/40 hover:bg-blue-50/30"
            )}
          >
            <input {...getInputProps()} />
            <FileUp
              className={clsx(
                "w-10 h-10 mx-auto mb-3",
                isDragActive ? "text-accent-blue" : "text-text-muted"
              )}
            />
            <p className="text-text-secondary font-medium">
              {isDragActive
                ? "Drop files here..."
                : "Drag & drop answer scripts, or click to browse"}
            </p>
            <p className="text-text-muted text-xs mt-1.5">
              Supports PDF, JPEG, PNG — up to 50 MB per file
            </p>
          </div>

          {files.length > 0 && (
            <div className="mt-4 space-y-2">
              {files.map((f, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 p-3 bg-surface border border-border rounded-lg"
                >
                  <Upload className="w-4 h-4 text-accent-green flex-shrink-0" />
                  <span className="flex-1 text-sm text-text-primary truncate">{f.name}</span>
                  <span className="text-xs text-text-muted font-mono">
                    {(f.size / 1024 / 1024).toFixed(1)} MB
                  </span>
                  <button
                    onClick={() => setFiles(files.filter((_, j) => j !== i))}
                    className="text-text-muted hover:text-accent-red transition-colors"
                  >
                    <XCircle className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            onClick={handleUpload}
            disabled={uploading || files.length === 0 || !examId}
            className="btn-primary w-full mt-6"
          >
            {uploading ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Uploading & Processing...
              </span>
            ) : (
              `Upload ${files.length} file${files.length !== 1 ? "s" : ""}`
            )}
          </button>
        </GlassCard>
      )}
    </div>
  );
}
