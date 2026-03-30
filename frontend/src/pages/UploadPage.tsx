import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Link, useNavigate } from "react-router-dom";
import {
  Upload,
  FileUp,
  CheckCircle,
  XCircle,
  Loader2,
  ArrowRight,
  Type,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { uploadAPI, examAPI, batchAPI } from "@/services/api";
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

interface ExamQuestion {
  questionId: string;
  questionText: string;
  maxMarks: number;
}

type UploadMode = "file" | "typed";

export function UploadPage() {
  const navigate = useNavigate();
  const [exams, setExams] = useState<ExamOption[]>([]);
  const [examId, setExamId] = useState("");
  const [examQuestions, setExamQuestions] = useState<ExamQuestion[]>([]);
  const [studentName, setStudentName] = useState("");
  const [studentRoll, setStudentRoll] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [typedAnswers, setTypedAnswers] = useState<Record<string, string>>({});
  const [uploadMode, setUploadMode] = useState<UploadMode>("file");
  const [storeFileForTuning, setStoreFileForTuning] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[]>([]);

  useEffect(() => {
    examAPI.list().then(({ data }) => setExams(data.items)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!examId) {
      setExamQuestions([]);
      setTypedAnswers({});
      return;
    }
    examAPI
      .get(examId)
      .then(({ data }) => setExamQuestions(data.questions || []))
      .catch(() => setExamQuestions([]));
  }, [examId]);

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
      "application/zip": [".zip"],
      "application/x-zip-compressed": [".zip"],
    },
    maxSize: 50 * 1024 * 1024,
  });

  async function handleUpload() {
    if (!examId) {
      toast.error("Please select an exam first");
      return;
    }

    if (uploadMode === "file") {
      if (files.length === 0) {
        toast.error("Please select files to upload");
        return;
      }
      setUploading(true);
      
      try {
        const formData = new FormData();
        formData.append("examId", examId || "");
        formData.append("studentName", studentName);
        formData.append("studentRollNo", studentRoll);
        
        // If it's a single ZIP, use batch API
        const firstFile = files[0];
        if (files.length === 1 && firstFile && (firstFile.name.toLowerCase().endsWith(".zip") || firstFile.type === "application/zip" || firstFile.type === "application/x-zip-compressed")) {
          await batchAPI.uploadScripts(firstFile, examId || "");
          toast.success("ZIP uploaded! Processing in background...");
          setFiles([]);
          navigate("/scripts", { state: { fromUpload: true } });
          return;
        } else {
          // Send all files to the general upload endpoint which now also uses Celery
          const formData = new FormData();
          formData.append("examId", examId);
          if (studentName) formData.append("studentName", studentName);
          if (studentRoll) formData.append("studentRoll", studentRoll);
          files.forEach((f) => formData.append("files", f));
          const { data } = await uploadAPI.upload(formData);
          const results = data.results ?? [];
          const queued = results.filter((r) => r.status === "QUEUED");
          const skipped = results.filter((r) => r.status === "SKIPPED_DUPLICATE");

          if (skipped.length) {
            const first = skipped[0];
            const extra = skipped.length > 1 ? ` (${skipped.length} files)` : "";
            toast.error(
              (first?.reason ?? "Already uploaded for this exam.") + extra,
              { duration: 6000 }
            );
          }

          if (queued.length === 0) {
            setFiles([]);
            navigate("/scripts");
            return;
          }

          toast.success(
            skipped.length
              ? `${queued.length} file(s) queued. ${skipped.length} skipped (duplicate).`
              : `${queued.length} script(s) uploading! Open Scripts for progress.`
          );
          setFiles([]);
          navigate("/scripts", { state: { fromUpload: true } });
        }
      } catch (err: any) {
        toast.error(err.response?.data?.message || err.response?.data?.error?.message || "Upload failed");
      } finally {
        setUploading(false);
      }
    } else {
      const answers = examQuestions.map((q) => ({
        questionId: q.questionId,
        answerText: typedAnswers[q.questionId] || "",
      }));
      const hasAnyAnswer = answers.some((a) => a.answerText.trim());
      if (!hasAnyAnswer) {
        toast.error("Please type or paste at least one answer");
        return;
      }
      setUploading(true);
      try {
        const { data } = await uploadAPI.uploadTyped({
          examId,
          studentName,
          studentRollNo: studentRoll,
          answers,
        });
        setResults([
          {
            filename: "typed-answer.txt",
            uploadedScriptId: data.uploadedScriptId,
            status: "ACCEPTED",
          },
        ]);
        toast.success(`Typed answer submitted. Evaluating ${data.evaluatingCount} question(s)...`);
        setTypedAnswers({});
        navigate("/scripts", {
          state: { fromUpload: true, uploadedScriptIds: data.uploadedScriptId ? [data.uploadedScriptId] : [] },
        });
      } catch (e: unknown) {
        const err = e as { response?: { data?: { error?: { message?: string } } } };
        toast.error(err.response?.data?.error?.message || "Submit failed");
      } finally {
        setUploading(false);
      }
    }
  }

  function resetAll() {
    setResults([]);
    setFiles([]);
    setTypedAnswers({});
    setStudentName("");
    setStudentRoll("");
  }

  const acceptedCount = results.filter((r) => r.status === "ACCEPTED").length;
  const canSubmitTyped =
    uploadMode === "typed" &&
    examQuestions.length > 0 &&
    examQuestions.some((q) => (typedAnswers[q.questionId] || "").trim());

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h2 className="page-title flex items-center gap-2">
          <Upload className="w-6 h-6 text-accent-green" />
          Upload Answer Papers
        </h2>
        <p className="text-text-secondary text-base mt-1.5">
          Upload student answer papers (PDF or images) for the selected exam. Each question is matched to its answer automatically.
        </p>
        <div className="mt-3 p-3 rounded-lg bg-blue-50 border border-blue-200 text-sm text-text-secondary">
          <strong className="text-text-primary">Workflow:</strong> Create an exam from a <strong>question paper</strong> on the{" "}
          <Link to="/exams" className="text-accent-blue hover:underline">Exams</Link> page (e.g. question paper_HISTORY.pdf), then upload{" "}
          <strong>answer papers</strong> here (e.g. answer paper_History.pdf). The system will extract text, map answers to each question, and evaluate.
        </div>
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
                Exam (from question paper) *
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
                  No exams yet — <Link to="/exams" className="underline hover:text-accent-gold/80">create one from a question paper first</Link>
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

          {uploadMode === "file" && (
            <label className="flex items-center gap-2 mb-4 cursor-pointer">
              <input
                type="checkbox"
                checked={storeFileForTuning}
                onChange={(e) => setStoreFileForTuning(e.target.checked)}
                className="rounded border-border"
              />
              <span className="text-sm text-text-secondary">
                Store this script for tuning (enables re-run OCR and re-segment without re-uploading)
              </span>
            </label>
          )}

          <div className="flex gap-2 mb-6">
            <button
              type="button"
              onClick={() => setUploadMode("file")}
              className={clsx(
                "flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg font-medium transition-colors",
                uploadMode === "file"
                  ? "bg-accent-blue text-white"
                  : "bg-surface border border-border text-text-secondary hover:border-accent-blue/40"
              )}
            >
              <FileUp className="w-4 h-4" />
              Upload answer paper(s)
            </button>
            <button
              type="button"
              onClick={() => setUploadMode("typed")}
              className={clsx(
                "flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg font-medium transition-colors",
                uploadMode === "typed"
                  ? "bg-accent-blue text-white"
                  : "bg-surface border border-border text-text-secondary hover:border-accent-blue/40"
              )}
            >
              <Type className="w-4 h-4" />
              Type / paste answers
            </button>
          </div>

          {uploadMode === "typed" ? (
            <div className="space-y-4 mb-6">
              {examQuestions.length === 0 && examId ? (
                <p className="text-sm text-text-muted">Loading questions...</p>
              ) : examQuestions.length === 0 ? (
                <p className="text-sm text-accent-gold">
                  Select an exam to type or paste answers
                </p>
              ) : (
                examQuestions.map((q) => (
                  <div key={q.questionId}>
                    <label className="block text-sm font-medium text-text-secondary mb-1.5">
                      {q.questionId} — {q.questionText.slice(0, 60)}
                      {q.questionText.length > 60 ? "..." : ""} ({q.maxMarks} marks)
                    </label>
                    <textarea
                      value={typedAnswers[q.questionId] || ""}
                      onChange={(e) =>
                        setTypedAnswers((prev) => ({
                          ...prev,
                          [q.questionId]: e.target.value,
                        }))
                      }
                      className="input-field min-h-[120px] resize-y font-mono text-sm"
                      placeholder="Type or paste the student's answer here..."
                      rows={4}
                    />
                  </div>
                ))
              )}
            </div>
          ) : (
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
                : "Drag & drop answer paper(s) (e.g. answer paper_History.pdf), or click to browse"}
            </p>
            <p className="text-text-muted text-xs mt-1.5">
              PDF, JPEG, or PNG — up to 50 MB. One file per student; answers are matched to questions automatically.
            </p>
          </div>
          )}

          {uploadMode === "file" && files.length > 0 && (
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
            disabled={
              uploading ||
              !examId ||
              (uploadMode === "file" && files.length === 0) ||
              (uploadMode === "typed" && !canSubmitTyped)
            }
            className="btn-primary w-full mt-6"
          >
            {uploading ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                {uploadMode === "typed" ? "Submitting & Evaluating..." : "Uploading & Processing..."}
              </span>
            ) : uploadMode === "typed" ? (
              "Submit Typed Answer"
            ) : (
              `Upload ${files.length} file${files.length !== 1 ? "s" : ""}`
            )}
          </button>
        </GlassCard>
      )}
    </div>
  );
}
