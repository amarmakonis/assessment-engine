import { clsx } from "clsx";

const STATUS_STYLES: Record<string, string> = {
  UPLOADED: "badge-info",
  PROCESSING: "badge-warning",
  OCR_COMPLETE: "badge-info",
  SEGMENTED: "badge-success",
  EVALUATING: "badge-warning",
  EVALUATED: "badge-success",
  COMPLETE: "badge-success",
  OVERRIDDEN: "badge-warning",
  FAILED: "badge-error",
  FLAGGED: "badge-error",
  PENDING: "bg-text-muted/20 text-text-muted",
  AUTO_APPROVED: "badge-success",
  NEEDS_REVIEW: "badge-warning",
  MUST_REVIEW: "badge-error",
  CONSISTENT: "badge-success",
  MINOR_ISSUES: "badge-warning",
  SIGNIFICANT_ISSUES: "badge-error",
};

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const style = STATUS_STYLES[status] ?? "badge-info";
  return (
    <span className={clsx("badge", style, className)}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
