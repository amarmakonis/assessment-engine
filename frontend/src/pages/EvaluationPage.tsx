import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  ChevronUp,
  BookOpen,
  Award,
  MessageSquare,
  Shield,
  Edit3,
  ArrowLeft,
  RefreshCw,
  Loader2,
  Brain,
  AlertTriangle,
  Lightbulb,
  Target,
  TrendingUp,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ScoreBreakdownChart } from "@/components/dashboard/ScoreBreakdownChart";
import { evaluationAPI } from "@/services/api";
import type { ScriptEvaluation, EvaluationResult } from "@/types";
import toast from "react-hot-toast";
import { clsx } from "clsx";

export function EvaluationPage() {
  const { scriptId } = useParams<{ scriptId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<ScriptEvaluation | null>(null);
  const [loading, setLoading] = useState(true);
  const [reEvaluating, setReEvaluating] = useState(false);
  const [expandedQ, setExpandedQ] = useState<string | null>(null);
  const [overrideId, setOverrideId] = useState<string | null>(null);
  const [overrideScore, setOverrideScore] = useState("");
  const [overrideNote, setOverrideNote] = useState("");

  function loadData() {
    if (!scriptId) return;
    evaluationAPI
      .getScript(scriptId)
      .then(({ data: d }) => {
        setData(d);
        const first = d.evaluations[0];
        if (first) setExpandedQ(first.questionId);
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadData();
  }, [scriptId]);

  useEffect(() => {
    if (!data || data.status !== "EVALUATING") return;
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [data]);

  async function handleReEvaluate() {
    if (!scriptId) return;
    setReEvaluating(true);
    try {
      await evaluationAPI.reEvaluate(scriptId);
      toast.success("Re-evaluation triggered");
      loadData();
    } catch {
      toast.error("Failed to trigger re-evaluation");
    } finally {
      setReEvaluating(false);
    }
  }

  async function submitOverride(resultId: string) {
    try {
      await evaluationAPI.override(resultId, parseFloat(overrideScore), overrideNote);
      toast.success("Override applied");
      setOverrideId(null);
      loadData();
    } catch {
      toast.error("Failed to apply override");
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Loader2 className="w-10 h-10 animate-spin text-accent-purple mb-4" />
        <p className="text-text-secondary text-sm">Loading evaluation results...</p>
      </div>
    );
  }

  if (!data || data.evaluations.length === 0) {
    return (
      <div className="space-y-6">
        <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-text-muted hover:text-text-primary transition-colors">
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <GlassCard>
          <div className="text-center py-16">
            <Brain className="w-12 h-12 text-text-muted mx-auto mb-4 opacity-50" />
            <p className="text-text-secondary font-medium">No evaluation results yet</p>
            <p className="text-text-muted text-sm mt-1">
              {data?.status === "EVALUATING"
                ? "Evaluation is in progress... this page will auto-refresh."
                : "This script hasn't been evaluated yet."}
            </p>
            {data?.status === "EVALUATING" && (
              <Loader2 className="w-6 h-6 animate-spin text-accent-blue mx-auto mt-4" />
            )}
          </div>
        </GlassCard>
      </div>
    );
  }

  const pct = data.percentageScore;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-text-muted hover:text-text-primary transition-colors mb-3">
            <ArrowLeft className="w-4 h-4" />
            Back to list
          </button>
          <h2 className="page-title">Evaluation Results</h2>
          <div className="flex items-center gap-3 mt-1.5">
            <p className="text-text-secondary text-sm">
              {data.studentMeta.name} &middot; {data.studentMeta.rollNo}
            </p>
            <StatusBadge status={data.status} />
          </div>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={handleReEvaluate}
            disabled={reEvaluating}
            className="btn-secondary text-sm flex items-center gap-2"
          >
            <RefreshCw className={clsx("w-4 h-4", reEvaluating && "animate-spin")} />
            Re-evaluate
          </button>
          <div className="text-right">
            <p className={clsx(
              "text-4xl font-display font-bold",
              pct >= 75 ? "text-accent-green" : pct >= 50 ? "text-accent-gold" : "text-accent-red"
            )}>
              {pct}%
            </p>
            <p className="text-sm text-text-secondary font-mono">
              {data.totalScore}/{data.maxPossibleScore} marks
            </p>
          </div>
        </div>
      </div>

      <GlassCard className="!p-4">
        <div className="flex items-center justify-between text-sm text-text-secondary mb-2">
          <span>Overall Score</span>
          <span className="font-mono">{data.evaluatedCount}/{data.questionCount} questions graded</span>
        </div>
        <div className="w-full h-3 bg-surface rounded-full overflow-hidden">
          <div
            className={clsx(
              "h-full rounded-full transition-all duration-1000",
              pct >= 75 ? "bg-accent-green" : pct >= 50 ? "bg-accent-gold" : "bg-accent-red"
            )}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
      </GlassCard>

      <div className="space-y-3">
        {data.evaluations.map((ev) => (
          <QuestionAccordion
            key={ev.questionId}
            evaluation={ev}
            isExpanded={expandedQ === ev.questionId}
            onToggle={() => setExpandedQ(expandedQ === ev.questionId ? null : ev.questionId)}
            overrideId={overrideId}
            setOverrideId={setOverrideId}
            overrideScore={overrideScore}
            setOverrideScore={setOverrideScore}
            overrideNote={overrideNote}
            setOverrideNote={setOverrideNote}
            submitOverride={submitOverride}
          />
        ))}
      </div>
    </div>
  );
}

function QuestionAccordion({
  evaluation: ev,
  isExpanded,
  onToggle,
  overrideId,
  setOverrideId,
  overrideScore,
  setOverrideScore,
  overrideNote,
  setOverrideNote,
  submitOverride,
}: {
  evaluation: EvaluationResult;
  isExpanded: boolean;
  onToggle: () => void;
  overrideId: string | null;
  setOverrideId: (id: string | null) => void;
  overrideScore: string;
  setOverrideScore: (v: string) => void;
  overrideNote: string;
  setOverrideNote: (v: string) => void;
  submitOverride: (id: string) => void;
}) {
  const pct = ev.maxPossibleScore > 0 ? (ev.totalScore / ev.maxPossibleScore) * 100 : 0;

  function scoreLabel(ratio: number) {
    if (ratio >= 0.7) return { color: "text-accent-green", bg: "bg-accent-green", border: "border-emerald-200" };
    if (ratio >= 0.4) return { color: "text-accent-gold", bg: "bg-accent-gold", border: "border-amber-200" };
    return { color: "text-accent-red", bg: "bg-accent-red", border: "border-red-200" };
  }

  const qColors = scoreLabel(pct / 100);

  return (
    <GlassCard className="!p-0 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 p-4 hover:bg-surface transition-colors"
      >
        <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 bg-violet-50 border border-violet-200">
          <BookOpen className="w-5 h-5 text-accent-purple" />
        </div>
        <div className="flex-1 text-left">
          <p className="font-medium text-text-primary">Question {ev.questionId.replace("q", "")}</p>
          <div className="flex items-center gap-3 mt-0.5">
            <span className={clsx("font-mono text-sm font-bold", qColors.color)}>
              {ev.totalScore}/{ev.maxPossibleScore}
            </span>
            <span className="text-text-muted text-xs">({pct.toFixed(1)}%)</span>
            <StatusBadge status={ev.reviewRecommendation} />
            {ev.reviewerOverride && (
              <span className="text-xs text-accent-orange flex items-center gap-1">
                <Edit3 className="w-3 h-3" /> Overridden
              </span>
            )}
          </div>
        </div>
        <div className="w-20 h-2.5 bg-surface rounded-full overflow-hidden mr-2">
          <div className={clsx("h-full rounded-full", qColors.bg)} style={{ width: `${pct}%` }} />
        </div>
        {isExpanded ? <ChevronUp className="w-5 h-5 text-text-muted" /> : <ChevronDown className="w-5 h-5 text-text-muted" />}
      </button>

      {isExpanded && (
        <div className="border-t border-border p-5 space-y-6 animate-in">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <h4 className="flex items-center gap-2 text-sm font-semibold text-text-primary mb-3">
                <Award className="w-4 h-4 text-accent-gold" />
                Criterion Scores
              </h4>
              <div className="space-y-3">
                {ev.criterionScores.map((cs) => {
                  const ratio = cs.maxMarks > 0 ? cs.marksAwarded / cs.maxMarks : 0;
                  const s = scoreLabel(ratio);
                  const rubricCriterion = ev.groundedRubric?.criteria?.find(
                    (c) => c.criterionId === cs.criterionId
                  );
                  return (
                    <div key={cs.criterionId} className={clsx("bg-card-alt rounded-lg p-3 border", s.border)}>
                      <div className="flex justify-between items-start gap-3 mb-2">
                        <div className="flex-1 min-w-0">
                          <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider">
                            {cs.criterionId}
                          </span>
                          {rubricCriterion && (
                            <p className="text-sm font-medium text-text-primary mt-0.5 leading-snug">
                              {rubricCriterion.description}
                            </p>
                          )}
                        </div>
                        <span className={clsx("font-mono text-sm font-bold flex-shrink-0", s.color)}>
                          {cs.marksAwarded}/{cs.maxMarks}
                        </span>
                      </div>
                      <div className="w-full h-1.5 bg-surface rounded-full overflow-hidden mb-2">
                        <div className={clsx("h-full rounded-full transition-all duration-500", s.bg)} style={{ width: `${ratio * 100}%` }} />
                      </div>
                      {cs.justificationQuote && (
                        <p className="text-sm text-text-secondary italic leading-relaxed mb-1">
                          &ldquo;{cs.justificationQuote.substring(0, 250)}{cs.justificationQuote.length > 250 ? "..." : ""}&rdquo;
                        </p>
                      )}
                      {cs.justificationReason && (
                        <p className="text-sm text-text-primary leading-relaxed">{cs.justificationReason}</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
            <div>
              <h4 className="flex items-center gap-2 text-sm font-semibold text-text-primary mb-3">
                <Target className="w-4 h-4 text-accent-cyan" />
                Score Distribution
              </h4>
              <ScoreBreakdownChart scores={ev.criterionScores} />
            </div>
          </div>

          {ev.feedback && (
            <div>
              <h4 className="flex items-center gap-2 text-sm font-semibold text-text-primary mb-3">
                <MessageSquare className="w-4 h-4 text-accent-green" />
                Student Feedback
              </h4>
              <div className="bg-card-alt border border-border rounded-lg p-4 space-y-4">
                <p className="text-sm text-text-primary leading-relaxed">{ev.feedback.summary}</p>

                {ev.feedback.strengths?.length > 0 && (
                  <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3">
                    <p className="text-xs font-semibold text-accent-green mb-2 flex items-center gap-1.5">
                      <TrendingUp className="w-3.5 h-3.5" />
                      Strengths
                    </p>
                    <ul className="space-y-1">
                      {ev.feedback.strengths.map((s: string, i: number) => (
                        <li key={i} className="text-sm text-text-secondary flex items-start gap-2">
                          <span className="text-accent-green mt-1">•</span>
                          {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {ev.feedback.improvements?.length > 0 && (
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                    <p className="text-xs font-semibold text-accent-gold mb-2 flex items-center gap-1.5">
                      <Lightbulb className="w-3.5 h-3.5" />
                      Areas for Improvement
                    </p>
                    <div className="space-y-2">
                      {ev.feedback.improvements.map((imp: any) => (
                        <div key={imp.criterionId}>
                          <span className="font-mono text-xs text-accent-gold">{imp.criterionId}</span>
                          <p className="text-sm text-text-secondary mt-0.5">
                            <span className="text-text-primary">{imp.gap}</span>
                            {imp.suggestion && <span className="text-text-muted"> — {imp.suggestion}</span>}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {ev.feedback.encouragementNote && (
                  <p className="text-sm text-accent-blue italic border-l-2 border-accent-blue/30 pl-3">
                    {ev.feedback.encouragementNote}
                  </p>
                )}
              </div>
            </div>
          )}

          {ev.explainability && (
            <div>
              <h4 className="flex items-center gap-2 text-sm font-semibold text-text-primary mb-3">
                <Shield className="w-4 h-4 text-accent-purple" />
                AI Audit Trail
              </h4>
              <div className="bg-card-alt border border-border rounded-lg p-4 space-y-3">
                <p className="text-sm text-text-secondary leading-relaxed">
                  {ev.explainability.chainOfReasoning}
                </p>
                {ev.explainability.uncertaintyAreas?.length > 0 && (
                  <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3">
                    <AlertTriangle className="w-4 h-4 text-accent-gold flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-text-secondary">{ev.explainability.uncertaintyAreas.join("; ")}</p>
                  </div>
                )}
                <div className="flex items-center gap-6 pt-2 border-t border-border text-sm">
                  <span className="text-text-secondary">
                    Agent Agreement:{" "}
                    <span className="font-mono text-accent-blue font-bold">
                      {((ev.explainability.agentAgreementScore ?? 0) * 100).toFixed(0)}%
                    </span>
                  </span>
                  <StatusBadge status={ev.explainability.reviewRecommendation} />
                </div>
              </div>
            </div>
          )}

          {ev.tokensUsed && (
            <div className="flex items-center gap-6 text-xs text-text-muted font-mono bg-surface rounded-lg px-3 py-2">
              <span>Latency: <span className="text-text-secondary">{ev.latencyMs}ms</span></span>
              <span>Tokens: <span className="text-text-secondary">{ev.tokensUsed.total?.toLocaleString()}</span></span>
              <span>Prompt: <span className="text-text-secondary">{ev.tokensUsed.prompt?.toLocaleString()}</span></span>
              <span>Completion: <span className="text-text-secondary">{ev.tokensUsed.completion?.toLocaleString()}</span></span>
            </div>
          )}

          <div className="border-t border-border pt-4">
            {overrideId === ev.id ? (
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label className="text-xs font-medium text-text-secondary">Override Score (max {ev.maxPossibleScore})</label>
                  <input type="number" value={overrideScore} onChange={(e) => setOverrideScore(e.target.value)} className="input-field mt-1" min={0} max={ev.maxPossibleScore} step={0.5} />
                </div>
                <div className="flex-1">
                  <label className="text-xs font-medium text-text-secondary">Note</label>
                  <input type="text" value={overrideNote} onChange={(e) => setOverrideNote(e.target.value)} className="input-field mt-1" placeholder="Reason for override" />
                </div>
                <button onClick={() => submitOverride(ev.id)} className="btn-primary">Apply</button>
                <button onClick={() => setOverrideId(null)} className="btn-secondary">Cancel</button>
              </div>
            ) : (
              <button
                onClick={() => { setOverrideId(ev.id); setOverrideScore(String(ev.totalScore)); setOverrideNote(""); }}
                className="btn-secondary text-xs flex items-center gap-1.5"
              >
                <Edit3 className="w-3.5 h-3.5" />
                Override Score
              </button>
            )}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
