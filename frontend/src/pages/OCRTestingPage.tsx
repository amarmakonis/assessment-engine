import React, { useState } from "react";
import { UploadCloud, Scan, CheckCircle } from "lucide-react";
import toast from "react-hot-toast";
import { ocrAPI } from "@/services/api";

export function OCRTestingPage() {
  const [answerFile, setAnswerFile] = useState<File | null>(null);
  const [questionFile, setQuestionFile] = useState<File | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);

  const handleFileChange = (
    e: React.ChangeEvent<HTMLInputElement>,
    type: "answer" | "question"
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.type !== "application/pdf" && !file.type.startsWith("image/")) {
      toast.error("Invalid file type. Please upload a PDF or Image.");
      return;
    }

    if (type === "answer") {
      setAnswerFile(file);
    } else {
      setQuestionFile(file);
    }
  };

  const handleTestOCR = async () => {
    if (!answerFile && !questionFile) {
      toast.error("Please upload at least one file (answer or question booklet).");
      return;
    }

    setIsProcessing(true);
    setAnswerText("");
    setQuestionText("");

    try {
      if (answerFile) {
        const answerFormData = new FormData();
        answerFormData.append("file", answerFile);
        const answerRes = await ocrAPI.testOCR(answerFormData);
        setAnswerText(answerRes.data.text);
      }

      if (questionFile) {
        const questionFormData = new FormData();
        questionFormData.append("file", questionFile);
        const questionRes = await ocrAPI.testOCR(questionFormData);
        setQuestionText(questionRes.data.text);
      }

      toast.success("OCR testing completed successfully.");
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: { message?: string }; message?: string } } };
      const msg =
        err.response?.data?.error?.message ??
        err.response?.data?.message ??
        "Failed to process OCR. Please try again.";
      toast.error(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold font-display text-gray-900 flex items-center gap-2">
          <Scan className="w-6 h-6 text-accent-blue" />
          OCR Testing Sandbox
        </h1>
        <p className="text-sm text-gray-500">
          Upload one or both: answer booklet and/or question booklet to verify
          how well the OCR works. This does not affect your production
          evaluations. Max 10 pages per file for testing.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
          <h2 className="text-lg font-bold text-gray-900 mb-4">
            Answer Booklet (Optional)
          </h2>
          <label
            className={`flex flex-col items-center justify-center h-40 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
              answerFile
                ? "border-accent-blue bg-accent-blue/5"
                : "border-gray-300 hover:border-gray-400 bg-gray-50/50"
            }`}
          >
            <div className="flex flex-col items-center justify-center pt-5 pb-6">
              {answerFile ? (
                <>
                  <CheckCircle className="w-10 h-10 text-accent-blue mb-3" />
                  <p className="mb-2 text-sm font-semibold text-gray-900">
                    {answerFile.name}
                  </p>
                </>
              ) : (
                <>
                  <UploadCloud className="w-10 h-10 text-gray-400 mb-3" />
                  <p className="mb-2 text-sm text-gray-500">
                    <span className="font-semibold text-accent-blue">
                      Click to upload
                    </span>
                  </p>
                  <p className="text-xs text-gray-500">
                    PDF, PNG, JPG (Max 10 pages)
                  </p>
                </>
              )}
            </div>
            <input
              type="file"
              className="hidden"
              accept="application/pdf,image/*"
              onChange={(e) => handleFileChange(e, "answer")}
            />
          </label>
        </div>

        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
          <h2 className="text-lg font-bold text-gray-900 mb-4">
            Question Booklet (Optional)
          </h2>
          <label
            className={`flex flex-col items-center justify-center h-40 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
              questionFile
                ? "border-accent-blue bg-accent-blue/5"
                : "border-gray-300 hover:border-gray-400 bg-gray-50/50"
            }`}
          >
            <div className="flex flex-col items-center justify-center pt-5 pb-6">
              {questionFile ? (
                <>
                  <CheckCircle className="w-10 h-10 text-accent-blue mb-3" />
                  <p className="mb-2 text-sm font-semibold text-gray-900">
                    {questionFile.name}
                  </p>
                </>
              ) : (
                <>
                  <UploadCloud className="w-10 h-10 text-gray-400 mb-3" />
                  <p className="mb-2 text-sm text-gray-500">
                    <span className="font-semibold text-accent-blue">
                      Click to upload
                    </span>
                  </p>
                  <p className="text-xs text-gray-500">
                    PDF, PNG, JPG (Max 10 pages)
                  </p>
                </>
              )}
            </div>
            <input
              type="file"
              className="hidden"
              accept="application/pdf,image/*"
              onChange={(e) => handleFileChange(e, "question")}
            />
          </label>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={handleTestOCR}
          disabled={(!answerFile && !questionFile) || isProcessing}
          className="flex items-center gap-2 px-6 py-2.5 bg-accent-blue text-white font-medium rounded-lg hover:bg-accent-blue-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isProcessing ? (
            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          ) : (
            <Scan className="w-5 h-5" />
          )}
          {isProcessing ? "Processing..." : "Run OCR Test"}
        </button>
      </div>

      {(answerText || questionText || isProcessing) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col min-h-[500px]">
            <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">Answer OCR Result</h3>
            </div>
            <div className="p-4 flex-1 bg-gray-50/30 overflow-y-auto font-mono text-sm whitespace-pre-wrap text-gray-700">
              {isProcessing && !answerText ? (
                <div className="flex items-center justify-center h-full text-gray-500">
                  <div className="w-6 h-6 border-2 border-gray-300 border-t-accent-blue rounded-full animate-spin mr-3" />
                  Extracting text from Answer Booklet...
                </div>
              ) : answerText ? (
                answerText
              ) : (
                <div className="text-gray-400 italic">No text extracted</div>
              )}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col min-h-[500px]">
            <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">
                Question OCR Result
              </h3>
            </div>
            <div className="p-4 flex-1 bg-gray-50/30 overflow-y-auto font-mono text-sm whitespace-pre-wrap text-gray-700">
              {isProcessing && questionFile && !questionText ? (
                <div className="flex items-center justify-center h-full text-gray-500">
                  <div className="w-6 h-6 border-2 border-gray-300 border-t-accent-blue rounded-full animate-spin mr-3" />
                  Extracting text from Question Booklet...
                </div>
              ) : questionText ? (
                questionText
              ) : (
                <div className="text-gray-400 italic">
                  {questionFile ? "No text extracted" : "No Question Booklet uploaded"}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
