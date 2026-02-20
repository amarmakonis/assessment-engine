import { useCallback, useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
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

  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("");
  const [questionFile, setQuestionFile] = useState<File | null>(null);
  const [rubricFile, setRubricFile] = useState<File | null>(null);
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

      const { data } = await examAPI.upload(formData);
      toast.success(`Exam created! ${data.totalMarks} total marks extracted.`);
      resetForm();
      loadExams();
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message || "Failed to extract exam from documents";
      toast.error(msg);
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

  function resetForm() {
    setTitle("");
    setSubject("");
    setQuestionFile(null);
    setRubricFile(null);
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
                    If not provided, rubric criteria will be auto-generated.
                  </p>
                </div>
              </div>

              <button
                onClick={handleUploadCreate}
                disabled={creating || !questionFile}
                className="btn-primary w-full"
              >
                {creating ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
                    Extracting with AI... (this may take 30-60s)
                  </>
                ) : (
                  "Extract & Create Exam"
                )}
              </button>
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
          <div className="text-center py-12">
            <BookOpen className="w-12 h-12 text-text-muted mx-auto mb-4" />
            <p className="text-text-secondary">No exams yet. Create one to get started.</p>
          </div>
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
                  {expandedExam === exam.id ? (
                    <ChevronUp className="w-5 h-5 text-text-muted" />
                  ) : (
                    <ChevronDown className="w-5 h-5 text-text-muted" />
                  )}
                </div>
              </div>

              {expandedExam === exam.id && (
                <div className="mt-4 pt-4 border-t border-border space-y-3">
                  <div className="flex items-center gap-2 text-xs text-text-muted">
                    <span>Exam ID:</span>
                    <code className="bg-surface px-2 py-0.5 rounded font-mono border border-border">{exam.id}</code>
                  </div>
                  {exam.questions.map((q: any, i: number) => (
                    <div key={i} className="bg-surface border border-border rounded-lg p-3">
                      <div className="flex justify-between items-start">
                        <p className="text-sm text-text-primary">
                          <span className="text-accent-blue font-mono mr-2 font-bold">Q{i + 1}</span>
                          {q.questionText}
                        </p>
                        <span className="text-xs text-text-muted flex-shrink-0 ml-2">{q.maxMarks} marks</span>
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
    </div>
  );
}
