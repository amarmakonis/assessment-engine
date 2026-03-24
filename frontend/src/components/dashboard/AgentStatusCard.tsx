import { clsx } from "clsx";
import { CheckCircle, Loader2, AlertTriangle, Clock } from "lucide-react";

export type AgentStep = {
  name: string;
  status: "pending" | "running" | "complete" | "error";
  durationMs?: number;
};

interface AgentStatusCardProps {
  questionId: string;
  steps: AgentStep[];
}

const STATUS_ICON = {
  pending: Clock,
  running: Loader2,
  complete: CheckCircle,
  error: AlertTriangle,
};

export function AgentStatusCard({ questionId, steps }: AgentStatusCardProps) {
  return (
    <div className="glass-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-mono text-sm text-text-secondary">
          Q: {questionId}
        </h4>
      </div>
      <div className="space-y-2">
        {steps.map((step) => {
          const Icon = STATUS_ICON[step.status];
          return (
            <div
              key={step.name}
              className={clsx(
                "flex items-center gap-3 px-3 py-2 rounded-lg",
                step.status === "running" && "bg-accent-blue/10 border border-accent-blue/20",
                step.status === "complete" && "bg-accent-green/5",
                step.status === "error" && "bg-accent-red/10",
                step.status === "pending" && "opacity-50"
              )}
            >
              <Icon
                className={clsx(
                  "w-4 h-4",
                  step.status === "running" && "text-accent-blue animate-spin",
                  step.status === "complete" && "text-accent-green",
                  step.status === "error" && "text-accent-red",
                  step.status === "pending" && "text-text-muted"
                )}
              />
              <span className="text-sm flex-1">{step.name}</span>
              {step.durationMs !== undefined && (
                <span className="font-mono text-xs text-text-muted">
                  {(step.durationMs / 1000).toFixed(1)}s
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
