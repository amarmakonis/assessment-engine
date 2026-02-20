export type UploadStatus =
  | "UPLOADED"
  | "PROCESSING"
  | "OCR_COMPLETE"
  | "SEGMENTED"
  | "EVALUATING"
  | "EVALUATED"
  | "FAILED"
  | "FLAGGED";

export type ScriptStatus = "PENDING" | "EVALUATING" | "COMPLETE" | "FLAGGED";

export type EvaluationStatus = "PENDING" | "COMPLETE" | "OVERRIDDEN" | "FAILED";

export type ReviewRecommendation =
  | "AUTO_APPROVED"
  | "NEEDS_REVIEW"
  | "MUST_REVIEW";

export type UserRole =
  | "SUPER_ADMIN"
  | "INSTITUTION_ADMIN"
  | "EXAMINER"
  | "REVIEWER"
  | "STUDENT";

export interface StudentMeta {
  name: string;
  rollNo: string;
  email?: string;
}

export interface UploadedScript {
  id: string;
  scriptId: string | null;
  examId: string;
  uploadBatchId: string;
  studentMeta: StudentMeta;
  originalFilename: string;
  mimeType: string;
  fileSizeBytes: number;
  pageCount: number | null;
  uploadStatus: UploadStatus;
  failureReason: string | null;
  createdAt: string;
}

export interface OCRPage {
  id: string;
  uploadedScriptId: string;
  pageNumber: number;
  extractedText: string;
  confidenceScore: number;
  qualityFlags: string[];
  provider: string;
  processingMs: number;
}

export interface CriterionScore {
  criterionId: string;
  marksAwarded: number;
  maxMarks: number;
  justificationQuote: string;
  justificationReason: string;
  confidenceScore: number;
}

export interface ConsistencyAudit {
  overallAssessment: "CONSISTENT" | "MINOR_ISSUES" | "SIGNIFICANT_ISSUES";
  adjustments: {
    criterionId: string;
    originalScore: number;
    recommendedScore: number;
    reason: string;
  }[];
  finalScores: { criterionId: string; finalScore: number }[];
  totalScore: number;
  auditNotes: string;
}

export interface StudentFeedback {
  summary: string;
  strengths: string[];
  improvements: {
    criterionId: string;
    gap: string;
    suggestion: string;
  }[];
  studyRecommendations: string[];
  encouragementNote: string;
}

export interface ExplainabilityResult {
  chainOfReasoning: string;
  uncertaintyAreas: string[];
  reviewRecommendation: ReviewRecommendation;
  reviewReason: string;
  agentAgreementScore: number;
}

export interface EvaluationResult {
  id: string;
  runId: string;
  scriptId: string;
  questionId: string;
  evaluationVersion: string;
  groundedRubric: {
    totalMarks: number;
    criteria: {
      criterionId: string;
      description: string;
      maxMarks: number;
      requiredEvidencePoints: string[];
      isAmbiguous: boolean;
    }[];
    groundingConfidence: number;
  };
  criterionScores: CriterionScore[];
  consistencyAudit: ConsistencyAudit;
  feedback: StudentFeedback;
  explainability: ExplainabilityResult;
  totalScore: number;
  maxPossibleScore: number;
  percentageScore: number;
  reviewRecommendation: ReviewRecommendation;
  reviewerOverride: {
    reviewerId: string;
    overrideScore: number;
    note: string;
    at: string;
  } | null;
  status: EvaluationStatus;
  latencyMs: number;
  tokensUsed: { prompt: number; completion: number; total: number };
  createdAt: string;
}

export interface ScriptEvaluation {
  scriptId: string;
  studentMeta: StudentMeta;
  status: ScriptStatus;
  totalScore: number;
  maxPossibleScore: number;
  percentageScore: number;
  questionCount: number;
  evaluatedCount: number;
  evaluations: EvaluationResult[];
}

export interface DashboardKPIs {
  totalUploadsToday: number;
  totalScripts: number;
  averageScore: number;
  reviewQueueSize: number;
  failedScripts: number;
  processingNow: number;
}

export interface User {
  id: string;
  email: string;
  fullName: string;
  role: UserRole;
  institutionId: string;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  user: User;
}

export interface ActivityItem {
  type: "evaluation" | "upload";
  id: string;
  scriptId?: string;
  questionId?: string;
  filename?: string;
  status: string;
  totalScore?: number;
  maxScore?: number;
  createdAt: string;
}
