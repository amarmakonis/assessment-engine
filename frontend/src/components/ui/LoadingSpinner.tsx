import { clsx } from "clsx";

interface LoadingSpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZES = { sm: "w-4 h-4", md: "w-8 h-8", lg: "w-12 h-12" };

export function LoadingSpinner({ size = "md", className }: LoadingSpinnerProps) {
  return (
    <div
      className={clsx(
        "animate-spin rounded-full border-2 border-accent-blue/20 border-t-accent-blue",
        SIZES[size],
        className
      )}
    />
  );
}
