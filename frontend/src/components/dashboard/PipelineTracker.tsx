import { clsx } from "clsx";
import {
  Upload,
  ScanText,
  Scissors,
  Brain,
  CheckCircle,
  XCircle,
  AlertTriangle,
} from "lucide-react";

const STAGES = [
  { key: "UPLOADED", label: "Uploaded", icon: Upload },
  { key: "PROCESSING", label: "OCR", icon: ScanText },
  { key: "SEGMENTED", label: "Segmented", icon: Scissors },
  { key: "EVALUATING", label: "Evaluating", icon: Brain },
  { key: "COMPLETE", label: "Complete", icon: CheckCircle },
] as const;

const STAGE_ORDER: Record<string, number> = {
  UPLOADED: 0,
  PROCESSING: 1,
  OCR_COMPLETE: 2,
  SEGMENTED: 2,
  EVALUATING: 3,
  EVALUATED: 4,
  COMPLETE: 4,
  FLAGGED: -1,
  FAILED: -1,
};

interface PipelineTrackerProps {
  currentStatus: string;
  compact?: boolean;
}

export function PipelineTracker({ currentStatus, compact }: PipelineTrackerProps) {
  const currentIdx = STAGE_ORDER[currentStatus] ?? -1;
  const isFailed = currentStatus === "FAILED";
  const isFlagged = currentStatus === "FLAGGED";
  const isTerminalError = isFailed || isFlagged;

  if (compact) {
    return (
      <div className="flex items-center gap-1">
        {STAGES.map((stage, idx) => {
          const isCompleted = idx < currentIdx && !isTerminalError;
          const isActive = idx === currentIdx;
          return (
            <div
              key={stage.key}
              className={clsx(
                "h-1 flex-1 rounded-full transition-all duration-300",
                isCompleted && "bg-accent-green",
                isActive && "bg-accent-blue animate-pulse",
                !isCompleted && !isActive && "bg-border",
                isTerminalError && idx >= currentIdx && "bg-red-200"
              )}
            />
          );
        })}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5 w-full">
      {STAGES.map((stage, idx) => {
        const Icon = stage.icon;
        const isActive = idx === currentIdx;
        const isCompleted = idx < currentIdx && !isTerminalError;

        return (
          <div key={stage.key} className="flex items-center gap-1.5 flex-1">
            <div className="flex flex-col items-center gap-1">
              <div
                className={clsx(
                  "w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all duration-300",
                  isCompleted && "bg-emerald-50 border-accent-green text-accent-green",
                  isActive && !isTerminalError && "bg-blue-50 border-accent-blue text-accent-blue",
                  !isCompleted && !isActive && "bg-surface border-border text-text-muted",
                  isTerminalError && idx >= currentIdx && "bg-red-50 border-red-200 text-red-300"
                )}
              >
                <Icon className="w-4 h-4" />
              </div>
              <span
                className={clsx(
                  "text-[9px] font-medium whitespace-nowrap",
                  isActive ? "text-accent-blue" : isCompleted ? "text-accent-green" : "text-text-muted"
                )}
              >
                {stage.label}
              </span>
            </div>
            {idx < STAGES.length - 1 && (
              <div
                className={clsx(
                  "flex-1 h-0.5 rounded-full transition-all duration-300",
                  isCompleted ? "bg-accent-green/50" : "bg-border"
                )}
              />
            )}
          </div>
        );
      })}
      {isTerminalError && (
        <div className="flex flex-col items-center gap-1 ml-1">
          <div className={clsx(
            "w-8 h-8 rounded-full flex items-center justify-center border-2",
            isFailed ? "bg-red-50 border-accent-red text-accent-red" : "bg-amber-50 border-accent-gold text-accent-gold"
          )}>
            {isFailed ? <XCircle className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
          </div>
          <span className={clsx("text-[9px] font-medium", isFailed ? "text-accent-red" : "text-accent-gold")}>
            {isFailed ? "Failed" : "Flagged"}
          </span>
        </div>
      )}
    </div>
  );
}
