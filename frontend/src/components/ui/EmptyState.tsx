import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, description, action, className = "" }: EmptyStateProps) {
  return (
    <div className={`text-center py-12 sm:py-16 px-4 ${className}`}>
      <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-2xl bg-surface border border-border flex items-center justify-center mx-auto mb-4 text-text-muted">
        {icon}
      </div>
      <h3 className="text-lg font-semibold text-text-primary mb-1">{title}</h3>
      {description && <p className="text-sm text-text-muted max-w-sm mx-auto mb-6">{description}</p>}
      {action && <div className="flex justify-center">{action}</div>}
    </div>
  );
}
