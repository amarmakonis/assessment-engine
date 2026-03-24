import { clsx } from "clsx";
import type { ReactNode } from "react";

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  hover?: boolean;
}

export function GlassCard({ children, className, hover }: GlassCardProps) {
  return (
    <div
      className={clsx(
        "glass-card p-6",
        hover && "hover:shadow-card-hover transition-all duration-250",
        className
      )}
    >
      {children}
    </div>
  );
}
