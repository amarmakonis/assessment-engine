import { useCallback, useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { EmptyState } from "@/components/ui/EmptyState";
import { examAPI } from "@/services/api";
import {
  Plus,
  Trash2,
  BookOpen,
  ClipboardList,
  Loader2,
  ChevronDown,
  ChevronUp,
  Copy,
  Upload,
  FileText,
  PenTool,
  PlusCircle,
  Pencil,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import { clsx } from "clsx";

interface RubricInput {
  description: string;
  maxMarks: number;
}

interface QuestionInput {
  questionText: string;
  maxMarks: number;
  rubric: RubricInput[];
}

interface ExamItem {
  id: string;
  title: string;
  subject: string;
  totalMarks: number;
  questions: any[];
  createdAt: string;
}

type CreateMode = "upload" | "manual";

export function ExamPage() {
  const [exams, setExams] = useState<ExamItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [createMode, setCreateMode] = useState<CreateMode>("upload");
  const [expandedExam, setExpandedExam] = useState<string | null>(null);
  const [examToDelete, setExamToDelete] = useState<string | null>(null);
  const [addQuestionExamId, setAddQuestionExamId] = useState<string | null>(null);
  const [addQuestionLabel, setAddQuestionLabel] = useState("");
  const [addQuestionText, setAddQuestionText] = useState("");
  const [addQuestionMarks, setAddQuestionMarks] = useState(2);
  const [addQuestionRubric, setAddQuestionRubric] = useState<RubricInput[]>([{ description: "", maxMarks: 2 }]);
  const [savingAddQuestion, setSavingAddQuestion] = useState(false);
  const [editQuestionExamId, setEditQuestionExamId] = useState<string | null>(null);
  const [editQuestionId, setEditQuestionId] = useState<string | null>(null);
  const [editQuestionText, setEditQuestionText] = useState("");
  const [editQuestionMarks, setEditQuestionMarks] = useState(0);
  const [savingEditQuestion, setSavingEditQuestion] = useState(false);

  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("");
  const [questionFile, setQuestionFile] = useState<File | null>(null);
  const [rubricFile, setRubricFile] = useState<File | null>(null);
  /** When no rubric file is uploaded: true = generate detailed rubrics with AI (recommended); false = use generic rubrics only (faster). */
  const [generateRubrics, setGenerateRubrics] = useState(true);
  /** When set, we are polling for this exam job and show a Cancel button. */
  const [creatingJobId, setCreatingJobId] = useState<string | null>(null);
  const cancelPollingRef = useRef(false);
  const [questions, setQuestions] = useState<QuestionInput[]>([
    { questionText: "", maxMarks: 10, rubric: [{ description: "", maxMarks: 10 }] },
  ]);

  const loadExams = useCallback(async () => {
    try {
      const { data } = await examAPI.list();
      setExams(data.items);
    } catch {
      toast.error("Failed to load exams");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadExams();
  }, [loadExams]);

  function addQuestion() {
    setQuestions([...questions, { questionText: "", maxMarks: 10, rubric: [{ description: "", maxMarks: 10 }] }]);
  }

  function removeQuestion(idx: number) {
    if (questions.length <= 1) return;
    setQuestions(questions.filter((_, i) => i !== idx));
  }

  function updateQuestion(idx: number, field: keyof QuestionInput, value: any) {
    const updated = [...questions];
    (updated[idx] as any)[field] = value;
    setQuestions(updated);
  }

  function addRubric(qIdx: number) {
    const updated = [...questions];
    const q = updated[qIdx];
    if (!q) return;
    q.rubric.push({ description: "", maxMarks: 5 });
    setQuestions(updated);
  }

  function removeRubric(qIdx: number, rIdx: number) {
    const updated = [...questions];
    const q = updated[qIdx];
    if (!q || q.rubric.length <= 1) return;
    q.rubric = q.rubric.filter((_, i) => i !== rIdx);
    setQuestions(updated);
  }

  function updateRubric(qIdx: number, rIdx: number, field: keyof RubricInput, value: any) {
    const updated = [...questions];
    const q = updated[qIdx];
    if (!q) return;
    (q.rubric[rIdx] as any)[field] = value;
    setQuestions(updated);
  }

  function openAddQuestionModal(examId: string) {
    setAddQuestionExamId(examId);
    setAddQuestionLabel("");
    setAddQuestionText("");
    setAddQuestionMarks(2);
    setAddQuestionRubric([{ description: "", maxMarks: 2 }]);
  }

  async function saveAddQuestion() {
    if (!addQuestionExamId || !addQuestionText.trim()) {
      toast.error("Please enter question text.");
      return;
    }
    setSavingAddQuestion(true);
    try {
      const rubric = addQuestionRubric.filter((r) => r.description.trim());
      await examAPI.addQuestion(addQuestionExamId, {
        questionLabel: addQuestionLabel.trim() || undefined,
        questionText: addQuestionText.trim(),
        maxMarks: addQuestionMarks,
        rubric: rubric.length > 0 ? rubric : undefined,
      });
      toast.success("Question added. Re-segment or re-evaluate scripts to use it.");
      setAddQuestionExamId(null);
      loadExams();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "response" in e && typeof (e as { response?: { data?: { error?: { message?: string } } } }).response?.data?.error?.message === "string"
        ? (e as { response: { data: { error: { message: string } } } }).response.data.error.message
        : "Failed to add question";
      toast.error(msg);
    } finally {
      setSavingAddQuestion(false);
    }
  }

  function openEditQuestionModal(exam: ExamItem, q: { questionId: string; questionText: string; maxMarks: number }) {
    setEditQuestionExamId(exam.id);
    setEditQuestionId(q.questionId);
    setEditQuestionText(q.questionText || "");
    setEditQuestionMarks(q.maxMarks ?? 0);
  }

  async function saveEditQuestion() {
    if (!editQuestionExamId || !editQuestionId) return;
    setSavingEditQuestion(true);
    try {
      await examAPI.updateQuestion(editQuestionExamId, editQuestionId, {
        questionText: editQuestionText.trim() || undefined,
        maxMarks: editQuestionMarks,
      });
      toast.success("Question updated.");
      setEditQuestionExamId(null);
      setEditQuestionId(null);
      loadExams();
    } catch {
      toast.error("Failed to update question");
    } finally {
      setSavingEditQuestion(false);
    }
  }

  async function handleUploadCreate() {
    if (!questionFile) {
      toast.error("Please upload a question paper");
      return;
    }

    setCreating(true);
    try {
      const formData = new FormData();
      formData.append("questionPaper", questionFile);
      if (rubricFile) formData.append("rubricDocument", rubricFile);
      if (title.trim()) formData.append("title", title.trim());
      if (subject.trim()) formData.append("subject", subject.trim());
      formData.append("generateRubrics", generateRubrics ? "true" : "false");

      const res = await examAPI.upload(formData);
      const { data, status } = res;

      if (status === 202 && "jobId" in data && data.jobId) {
        const jobId = data.jobId;
        cancelPollingRef.current = false;
        setCreatingJobId(jobId);
        toast.loading("Creating exam… This may take 1–2 minutes.", { id: "exam-create" });
        const poll = async (): Promise<void> => {
          if (cancelPollingRef.current) return;
          const { data: job } = await examAPI.getJobStatus(jobId);
          if (cancelPollingRef.current) return;
          if (job.status === "COMPLETE") {
            setCreatingJobId(null);
            setCreating(false);
            toast.success(`Exam created! ${job.examId ? "You can use it for uploads now." : ""}`, { id: "exam-create" });
            resetForm();
            loadExams();
            return;
          }
          if (job.status === "FAILED") {
            setCreatingJobId(null);
            setCreating(false);
            toast.error(job.error || "Exam creation failed", { id: "exam-create" });
            return;
          }
          if (job.status === "CANCELLED") {
            setCreatingJobId(null);
            setCreating(false);
            toast("Exam creation was cancelled", { id: "exam-create" });
            return;
          }
          setTimeout(poll, 2500);
        };
        await poll();
      } else {
        toast.success(`Exam created! ${(data as { totalMarks?: number }).totalMarks ?? 0} total marks extracted.`, { id: "exam-create" });
        if ((data as { marksMismatchWarning?: string }).marksMismatchWarning) {
          toast((data as { marksMismatchWarning: string }).marksMismatchWarning, { duration: 8000, icon: "⚠️" });
        }
        resetForm();
        loadExams();
      }
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "response" in err && typeof (err as { response?: { data?: { error?: { message?: string } } } }).response?.data?.error?.message === "string"
        ? (err as { response: { data: { error: { message: string } } } }).response.data.error.message
        : "Failed to extract exam from documents";
      toast.error(msg, { id: "exam-create" });
    } finally {
      setCreating(false);
    }
  }

  async function handleManualCreate() {
    if (!title.trim() || !subject.trim()) {
      toast.error("Title and subject are required");
      return;
    }
    for (let i = 0; i < questions.length; i++) {
      const q = questions[i];
      if (!q?.questionText.trim()) {
        toast.error(`Question ${i + 1} text is empty`);
        return;
      }
    }

    setCreating(true);
    try {
      const { data } = await examAPI.create({ title, subject, questions });
      toast.success(`Exam created! Total marks: ${data.totalMarks}`);
      resetForm();
      loadExams();
    } catch {
      toast.error("Failed to create exam");
    } finally {
      setCreating(false);
    }
  }

  async function cancelExamCreation() {
    if (!creatingJobId) return;
    try {
      await examAPI.cancelJob(creatingJobId);
      cancelPollingRef.current = true;
      setCreatingJobId(null);
      setCreating(false);
      toast("Exam creation cancelled", { id: "exam-create" });
    } catch {
      toast.error("Could not cancel", { id: "exam-create" });
    }
  }

  function resetForm() {
    setTitle("");
    setSubject("");
    setQuestionFile(null);
    setRubricFile(null);
    setGenerateRubrics(true);
    setCreatingJobId(null);
    setQuestions([{ questionText: "", maxMarks: 10, rubric: [{ description: "", maxMarks: 10 }] }]);
    setShowForm(false);
  }

  function copyExamId(id: string) {
    navigator.clipboard.writeText(id);
    toast.success("Exam ID copied!");
  }

  const totalMarks = questions.reduce((s, q) => s + q.maxMarks, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="page-title">Exams</h2>
          <p className="text-text-secondary text-base mt-1.5">
            Create exams by uploading question papers or entering manually
          </p>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" />
          {showForm ? "Cancel" : "New Exam"}
        </button>
      </div>

      {showForm && (
        <GlassCard>
          <div className="flex gap-2 mb-6">
            <button
              onClick={() => setCreateMode("upload")}
              className={clsx(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
                createMode === "upload"
                  ? "bg-accent-blue text-white"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface border border-border"
              )}
            >
              <Upload className="w-4 h-4" />
              Upload Documents
            </button>
            <button
              onClick={() => setCreateMode("manual")}
              className={clsx(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
                createMode === "manual"
                  ? "bg-accent-blue text-white"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface border border-border"
              )}
            >
              <PenTool className="w-4 h-4" />
              Enter Manually
            </button>
          </div>

          {createMode === "upload" ? (
            <div className="space-y-4">
              <p className="text-sm text-text-secondary">
                Upload your question paper and optionally a rubric/marking scheme.
                OpenAI will extract all questions, marks, and grading criteria automatically.
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">
                    Title (optional — auto-detected)
                  </label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="input-field"
                    placeholder="CS101 Midterm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">
                    Subject (optional — auto-detected)
                  </label>
                  <input
                    type="text"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    className="input-field"
                    placeholder="Computer Science"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">
                    Question Paper *
                  </label>
                  <p className="text-xs text-text-muted mb-2">
                    e.g. question paper_HISTORY.pdf — used to create the exam; students&apos; answer papers are uploaded separately.
                  </p>
                  <label className={clsx(
                    "flex flex-col items-center justify-center gap-2 p-6 border-2 border-dashed rounded-xl cursor-pointer transition-all",
                    questionFile
                      ? "border-accent-green bg-emerald-50"
                      : "border-border hover:border-accent-blue/50 hover:bg-blue-50/30"
                  )}>
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.docx,.jpg,.jpeg,.png"
                      onChange={(e) => setQuestionFile(e.target.files?.[0] || null)}
                    />
                    <FileText className={clsx("w-8 h-8", questionFile ? "text-accent-green" : "text-text-muted")} />
                    {questionFile ? (
                      <span className="text-sm text-accent-green font-medium">{questionFile.name}</span>
                    ) : (
                      <span className="text-sm text-text-muted">PDF, DOCX, JPEG, or PNG</span>
                    )}
                  </label>
                </div>

                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">
                    Rubric / Marking Scheme (optional)
                  </label>
                  <label className={clsx(
                    "flex flex-col items-center justify-center gap-2 p-6 border-2 border-dashed rounded-xl cursor-pointer transition-all",
                    rubricFile
                      ? "border-accent-green bg-emerald-50"
                      : "border-border hover:border-accent-blue/50 hover:bg-blue-50/30"
                  )}>
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.docx,.jpg,.jpeg,.png"
                      onChange={(e) => setRubricFile(e.target.files?.[0] || null)}
                    />
                    <ClipboardList className={clsx("w-8 h-8", rubricFile ? "text-accent-green" : "text-text-muted")} />
                    {rubricFile ? (
                      <span className="text-sm text-accent-green font-medium">{rubricFile.name}</span>
                    ) : (
                      <span className="text-sm text-text-muted">PDF, DOCX, JPEG, or PNG</span>
                    )}
                  </label>
                  <p className="text-xs text-text-muted mt-1">
                    If not provided, choose below whether to generate detailed rubrics with AI or use generic rubrics.
                  </p>
                </div>
              </div>

              {!rubricFile && (
                <div className="rounded-xl border border-border bg-blue-50/50 dark:bg-slate-800/30 p-4">
                  <p className="text-sm font-medium text-text-primary mb-3">No rubric file uploaded. How should rubrics be set?</p>
                  <div className="space-y-2">
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="radio"
                        name="generateRubrics"
                        checked={generateRubrics}
                        onChange={() => setGenerateRubrics(true)}
                        className="mt-1"
                      />
                      <span className="text-sm text-text-primary">
                        <strong>Generate detailed rubrics with AI</strong> (recommended) — better evaluation quality. May take 1–2 minutes.
                      </span>
                    </label>
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="radio"
                        name="generateRubrics"
                        checked={!generateRubrics}
                        onChange={() => setGenerateRubrics(false)}
                        className="mt-1"
                      />
                      <span className="text-sm text-text-primary">
                        <strong>Use generic rubrics only</strong> (faster) — one criterion per question; exam created in ~30–60 seconds.
                      </span>
                    </label>
                  </div>
                </div>
              )}

              {creatingJobId ? (
                <div className="flex items-center justify-between gap-4 p-4 rounded-xl bg-blue-50 dark:bg-slate-800/40 border border-border">
                  <span className="text-sm text-text-primary flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Creating exam… This may take 1–2 minutes.
                  </span>
                  <button
                    type="button"
                    onClick={cancelExamCreation}
                    className="btn-secondary text-sm py-1.5 px-3"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={handleUploadCreate}
                  disabled={creating || !questionFile}
                  className="btn-primary w-full"
                >
                  {creating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
                      Extracting with AI... (1–3 min, please wait)
                    </>
                  ) : (
                    "Extract & Create Exam"
                  )}
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">Exam Title *</label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="input-field"
                    placeholder="CS101 Midterm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">Subject *</label>
                  <input
                    type="text"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    className="input-field"
                    placeholder="Computer Science"
                  />
                </div>
              </div>

              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium text-sm text-text-secondary">
                    Questions ({questions.length}) — Total: {totalMarks} marks
                  </h4>
                  <button onClick={addQuestion} className="text-accent-blue hover:underline text-sm flex items-center gap-1">
                    <Plus className="w-3 h-3" /> Add Question
                  </button>
                </div>

                {questions.map((q, qIdx) => (
                  <div key={qIdx} className="bg-surface rounded-xl p-4 space-y-3 border border-border">
                    <div className="flex items-start gap-3">
                      <span className="text-accent-blue font-mono text-sm mt-2 flex-shrink-0 font-bold">
                        Q{qIdx + 1}
                      </span>
                      <div className="flex-1 space-y-3">
                        <div className="flex gap-3">
                          <textarea
                            value={q.questionText}
                            onChange={(e) => updateQuestion(qIdx, "questionText", e.target.value)}
                            className="input-field flex-1 min-h-[60px] resize-y"
                            placeholder="Enter question text..."
                            rows={2}
                          />
                          <div className="w-24 flex-shrink-0">
                            <label className="block text-xs text-text-muted mb-1">Marks</label>
                            <input
                              type="number"
                              value={q.maxMarks}
                              onChange={(e) => updateQuestion(qIdx, "maxMarks", Number(e.target.value))}
                              className="input-field text-center"
                              min={0.5}
                              step={0.5}
                            />
                          </div>
                        </div>
                        <div className="pl-2 border-l-2 border-border space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs text-text-muted">Rubric Criteria</span>
                            <button onClick={() => addRubric(qIdx)} className="text-accent-blue text-xs hover:underline">
                              + Add Criterion
                            </button>
                          </div>
                          {q.rubric.map((r, rIdx) => (
                            <div key={rIdx} className="flex gap-2 items-center">
                              <input
                                type="text"
                                value={r.description}
                                onChange={(e) => updateRubric(qIdx, rIdx, "description", e.target.value)}
                                className="input-field flex-1 text-sm"
                                placeholder={`Criterion ${rIdx + 1} description...`}
                              />
                              <input
                                type="number"
                                value={r.maxMarks}
                                onChange={(e) => updateRubric(qIdx, rIdx, "maxMarks", Number(e.target.value))}
                                className="input-field w-20 text-center text-sm"
                                min={0.5}
                                step={0.5}
                              />
                              <button
                                onClick={() => removeRubric(qIdx, rIdx)}
                                className="text-text-muted hover:text-accent-red p-1"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                      <button
                        onClick={() => removeQuestion(qIdx)}
                        className="text-text-muted hover:text-accent-red mt-2"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <button onClick={handleManualCreate} disabled={creating} className="btn-primary w-full">
                {creating ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
                    Creating...
                  </>
                ) : (
                  `Create Exam (${totalMarks} marks)`
                )}
              </button>
            </div>
          )}
        </GlassCard>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-accent-blue" />
        </div>
      ) : exams.length === 0 ? (
        <GlassCard>
          <EmptyState
            icon={<BookOpen className="w-8 h-8 sm:w-10 sm:h-10 text-text-muted" />}
            title="No exams yet"
            description="Create an exam with questions and rubrics to start grading answer scripts."
            action={
              <button onClick={() => setShowForm(true)} className="btn-primary inline-flex items-center gap-2">
                <Plus className="w-4 h-4" />
                New Exam
              </button>
            }
          />
        </GlassCard>
      ) : (
        <div className="space-y-3">
          {exams.map((exam) => (
            <GlassCard key={exam.id}>
              <div
                className="flex items-center justify-between cursor-pointer"
                onClick={() => setExpandedExam(expandedExam === exam.id ? null : exam.id)}
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center">
                    <ClipboardList className="w-5 h-5 text-accent-blue" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-text-primary">{exam.title}</h3>
                    <p className="text-text-secondary text-sm">
                      {exam.subject} — {exam.questions.length} questions — {exam.totalMarks} marks
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={(e) => { e.stopPropagation(); copyExamId(exam.id); }}
                    className="text-text-muted hover:text-accent-blue p-1"
                    title="Copy Exam ID"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setExamToDelete(exam.id);
                    }}
                    className="text-text-muted hover:text-accent-red p-1"
                    title="Delete exam"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                  {expandedExam === exam.id ? (
                    <ChevronUp className="w-5 h-5 text-text-muted" />
                  ) : (
                    <ChevronDown className="w-5 h-5 text-text-muted" />
                  )}
                </div>
              </div>

              {expandedExam === exam.id && (
                <div className="mt-4 pt-4 border-t border-border space-y-3">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2 text-xs text-text-muted">
                      <span>Exam ID:</span>
                      <code className="bg-surface px-2 py-0.5 rounded font-mono border border-border">{exam.id}</code>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); openAddQuestionModal(exam.id); }}
                      className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 hover:bg-violet-200 dark:hover:bg-violet-800/50 text-sm font-medium transition-colors"
                    >
                      <PlusCircle className="w-4 h-4" />
                      Add missing question
                    </button>
                  </div>
                  {exam.questions.map((q: any, i: number) => (
                    <div key={q.questionId ?? i} className="bg-surface border border-border rounded-lg p-3">
                      <div className="flex justify-between items-start gap-2">
                        <p className="text-sm text-text-primary flex-1 min-w-0">
                          <span className="text-accent-blue font-mono mr-2 font-bold">
                            Q{(q.questionId || String(i + 1)).replace(/^q/i, "")}
                          </span>
                          {q.questionText}
                        </p>
                        <span className="text-xs text-text-muted flex-shrink-0">{q.maxMarks} marks</span>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); openEditQuestionModal(exam, q); }}
                          className="p-1.5 rounded text-text-muted hover:text-accent-blue hover:bg-blue-50 dark:hover:bg-blue-900/20"
                          title="Edit question / marks"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      {q.rubric?.length > 0 && (
                        <div className="mt-2 pl-6 space-y-1">
                          {q.rubric.map((r: any, j: number) => (
                            <p key={j} className="text-xs text-text-secondary">
                              • {r.description} ({r.maxMarks} marks)
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </GlassCard>
          ))}
        </div>
      )}

      {/* Add missing question modal */}
      {addQuestionExamId && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => !savingAddQuestion && setAddQuestionExamId(null)}
            aria-hidden="true"
          />
          <div
            className="relative w-full max-w-lg rounded-2xl bg-card border border-border shadow-card-hover overflow-hidden animate-in"
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-q-title"
          >
            <div className="bg-gradient-to-br from-violet-500/10 to-amber-500/10 border-b border-border px-6 py-4">
              <div className="flex items-center justify-between gap-4">
                <h3 id="add-q-title" className="text-lg font-semibold text-text-primary flex items-center gap-2">
                  <PlusCircle className="w-5 h-5 text-accent-purple" />
                  Add missing question
                </h3>
                <button
                  type="button"
                  onClick={() => !savingAddQuestion && setAddQuestionExamId(null)}
                  className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface"
                  aria-label="Close"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <p className="text-sm text-text-secondary mt-1">
                Add a question that was not detected (e.g. 34.2). It will be included in segmentation and evaluation.
              </p>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label htmlFor="add-q-label" className="block text-sm font-medium text-text-primary mb-1">Question number / label (optional)</label>
                <input
                  id="add-q-label"
                  type="text"
                  value={addQuestionLabel}
                  onChange={(e) => setAddQuestionLabel(e.target.value)}
                  placeholder="e.g. 34.2"
                  className="input-field w-full"
                />
              </div>
              <div>
                <label htmlFor="add-q-text" className="block text-sm font-medium text-text-primary mb-1">Question text *</label>
                <textarea
                  id="add-q-text"
                  value={addQuestionText}
                  onChange={(e) => setAddQuestionText(e.target.value)}
                  placeholder="Full question text as in the paper..."
                  className="input-field w-full min-h-[80px] resize-y"
                  rows={3}
                />
              </div>
              <div>
                <label htmlFor="add-q-marks" className="block text-sm font-medium text-text-primary mb-1">Marks</label>
                <input
                  id="add-q-marks"
                  type="number"
                  min={0.5}
                  step={0.5}
                  value={addQuestionMarks}
                  onChange={(e) => setAddQuestionMarks(parseFloat(e.target.value) || 0)}
                  className="input-field w-24"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 px-6 pb-6">
              <button type="button" onClick={() => !savingAddQuestion && setAddQuestionExamId(null)} className="btn-secondary">Cancel</button>
              <button
                type="button"
                onClick={saveAddQuestion}
                disabled={savingAddQuestion || !addQuestionText.trim()}
                className="btn-primary flex items-center gap-2"
              >
                {savingAddQuestion ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</> : <><PlusCircle className="w-4 h-4" /> Add question</>}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit question / marks modal */}
      {editQuestionExamId && editQuestionId && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => !savingEditQuestion && (setEditQuestionExamId(null), setEditQuestionId(null))} aria-hidden="true" />
          <div className="relative w-full max-w-lg rounded-2xl bg-card border border-border shadow-card-hover overflow-hidden animate-in" role="dialog" aria-modal="true">
            <div className="border-b border-border px-6 py-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-text-primary flex items-center gap-2">
                <Pencil className="w-5 h-5 text-accent-blue" />
                Edit question — Q{(editQuestionId || "").replace(/^q/i, "")}
              </h3>
              <button type="button" onClick={() => !savingEditQuestion && (setEditQuestionExamId(null), setEditQuestionId(null))} className="p-1.5 rounded-lg text-text-muted hover:bg-surface" aria-label="Close">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-text-primary mb-1">Question text</label>
                <textarea value={editQuestionText} onChange={(e) => setEditQuestionText(e.target.value)} className="input-field w-full min-h-[60px] resize-y" rows={2} />
              </div>
              <div>
                <label className="block text-sm font-medium text-text-primary mb-1">Marks</label>
                <input type="number" min={0.5} step={0.5} value={editQuestionMarks} onChange={(e) => setEditQuestionMarks(parseFloat(e.target.value) || 0)} className="input-field w-24" />
              </div>
            </div>
            <div className="flex justify-end gap-3 px-6 pb-6">
              <button type="button" onClick={() => !savingEditQuestion && (setEditQuestionExamId(null), setEditQuestionId(null))} className="btn-secondary">Cancel</button>
              <button type="button" onClick={saveEditQuestion} disabled={savingEditQuestion} className="btn-primary flex items-center gap-2">
                {savingEditQuestion ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</> : <>Save</>}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        isOpen={!!examToDelete}
        onClose={() => setExamToDelete(null)}
        onConfirm={async () => {
          if (!examToDelete) return;
          try {
            await examAPI.delete(examToDelete);
            toast.success("Exam deleted");
            setExamToDelete(null);
            loadExams();
          } catch {
            toast.error("Failed to delete exam");
          }
        }}
        title="Delete exam"
        message="Delete this exam? Questions and rubrics will be removed. This cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
      />
    </div>
  );
}
