import axios from "axios";
import type {
  AuthTokens,
  DashboardKPIs,
  EvaluationResult,
  OCRPage,
  ScriptEvaluation,
  UploadedScript,
  ActivityItem,
} from "@/types";

const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const refreshToken = localStorage.getItem("refresh_token");
      if (refreshToken) {
        try {
          const { data } = await axios.post("/api/v1/auth/refresh", null, {
            headers: { Authorization: `Bearer ${refreshToken}` },
          });
          localStorage.setItem("access_token", data.accessToken);
          original.headers.Authorization = `Bearer ${data.accessToken}`;
          return api(original);
        } catch {
          localStorage.removeItem("access_token");
          localStorage.removeItem("refresh_token");
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);

export const authAPI = {
  login: (email: string, password: string) =>
    api.post<AuthTokens>("/auth/login", { email, password }),
  register: (data: {
    email: string;
    password: string;
    fullName: string;
    institutionId: string;
    role?: string;
  }) => api.post("/auth/register", data),
  me: () => api.get<{ id: string; email: string; fullName: string; role: string }>("/auth/me"),
};

export const uploadAPI = {
  upload: (formData: FormData) =>
    api.post<{ batchId: string; totalFiles: number; results: { filename: string; uploadedScriptId?: string; status: string; reason?: string }[] }>(
      "/uploads/",
      formData,
      { headers: { "Content-Type": "multipart/form-data" } }
    ),
  list: (params: { examId?: string; page?: number; perPage?: number }) =>
    api.get<{ items: UploadedScript[]; total: number; page: number; perPage: number }>(
      "/uploads/",
      { params }
    ),
  get: (scriptId: string) => api.get<UploadedScript>(`/uploads/${scriptId}`),
};

export const ocrAPI = {
  getPages: (scriptId: string) =>
    api.get<{ scriptId: string; pageCount: number; pages: OCRPage[] }>(
      `/ocr/scripts/${scriptId}/pages`
    ),
  updatePage: (scriptId: string, pageNumber: number, extractedText: string) =>
    api.put(`/ocr/scripts/${scriptId}/pages/${pageNumber}`, { extractedText }),
  getSignedUrl: (scriptId: string) =>
    api.get<{ signedUrl: string; expiresIn: number }>(
      `/ocr/scripts/${scriptId}/signed-url`
    ),
  reSegment: (scriptId: string) =>
    api.post(`/ocr/scripts/${scriptId}/re-segment`),
};

export const evaluationAPI = {
  list: (params?: { page?: number; perPage?: number; status?: string }) =>
    api.get<{
      items: {
        scriptId: string;
        examId: string;
        studentMeta: { name: string; rollNo: string };
        status: string;
        totalScore: number;
        maxPossibleScore: number;
        percentageScore: number;
        questionCount: number;
        evaluatedCount: number;
        needsReview: boolean;
        createdAt: string;
      }[];
      total: number;
      page: number;
      perPage: number;
    }>("/evaluation/list", { params }),
  getScript: (scriptId: string) =>
    api.get<ScriptEvaluation>(`/evaluation/scripts/${scriptId}`),
  getResult: (resultId: string) =>
    api.get<EvaluationResult>(`/evaluation/results/${resultId}`),
  override: (resultId: string, overrideScore: number, note: string) =>
    api.post(`/evaluation/results/${resultId}/override`, { overrideScore, note }),
  reEvaluate: (scriptId: string) =>
    api.post(`/evaluation/scripts/${scriptId}/re-evaluate`),
};

export const examAPI = {
  create: (data: {
    title: string;
    subject: string;
    questions: { questionText: string; maxMarks: number; rubric: { description: string; maxMarks: number }[] }[];
  }) => api.post<{ examId: string; totalMarks: number }>("/exams/", data),
  upload: (formData: FormData) =>
    api.post<{ examId: string; totalMarks: number }>("/exams/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120000,
    }),
  list: (params?: { page?: number; perPage?: number }) =>
    api.get<{
      items: { id: string; title: string; subject: string; totalMarks: number; questions: any[]; createdAt: string }[];
      total: number;
    }>("/exams/", { params }),
  get: (examId: string) => api.get<any>(`/exams/${examId}`),
};

export const dashboardAPI = {
  kpis: () => api.get<DashboardKPIs>("/dashboard/kpis"),
  recentActivity: () =>
    api.get<{ activity: ActivityItem[] }>("/dashboard/recent-activity"),
  reviewQueue: () =>
    api.get<{
      items: {
        id: string;
        scriptId: string;
        questionId: string;
        totalScore: number;
        maxScore: number;
        reviewRecommendation: string;
        reviewReason: string;
        createdAt: string;
      }[];
      total: number;
    }>("/dashboard/review-queue"),
};

export default api;
