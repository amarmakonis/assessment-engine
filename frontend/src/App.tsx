import { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { Toaster } from "react-hot-toast";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Sidebar, SidebarToggle } from "@/components/ui/Sidebar";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { LoginPage } from "@/pages/LoginPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { UploadPage } from "@/pages/UploadPage";
import { ScriptsPage } from "@/pages/ScriptsPage";
import { OCRReviewPage } from "@/pages/OCRReviewPage";
import { EvaluationPage } from "@/pages/EvaluationPage";
import { EvaluationsListPage } from "@/pages/EvaluationsListPage";
import { ReviewQueuePage } from "@/pages/ReviewQueuePage";
import { ExamPage } from "@/pages/ExamPage";

function ProtectedLayout() {
  const { isAuthenticated, isLoading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-page">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="flex min-h-screen bg-page">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0 ml-0 lg:ml-64">
        <SidebarToggle onClick={() => setSidebarOpen(true)} />
        <main className="flex-1 p-4 sm:p-6 lg:p-8 pt-16 lg:pt-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: "#FFFFFF",
              color: "#0F172A",
              border: "1px solid #E2E8F0",
              boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
            },
          }}
        />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/exams" element={<ExamPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/scripts" element={<ScriptsPage />} />
            <Route path="/scripts/:scriptId/ocr" element={<OCRReviewPage />} />
            <Route
              path="/scripts/:scriptId/evaluation"
              element={<EvaluationPage />}
            />
            <Route path="/evaluations" element={<EvaluationsListPage />} />
            <Route path="/review" element={<ReviewQueuePage />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
