import { clsx } from "clsx";
import type { ReactNode } from "react";

interface KPICardProps {
  label: string;
  value: string | number;
  icon: ReactNode;
  trend?: string;
  accentColor?: string;
}

const BG_MAP: Record<string, string> = {
  "text-accent-cyan": "bg-cyan-50",
  "text-accent-blue": "bg-blue-50",
  "text-accent-green": "bg-emerald-50",
  "text-accent-gold": "bg-amber-50",
  "text-accent-red": "bg-red-50",
  "text-accent-purple": "bg-violet-50",
  "text-accent-orange": "bg-orange-50",
};

export function KPICard({
  label,
  value,
  icon,
  trend,
  accentColor = "text-accent-cyan",
}: KPICardProps) {
  const bgColor = BG_MAP[accentColor] ?? "bg-blue-50";

  return (
    <div className="glass-card p-5 flex items-start gap-4">
      <div
        className={clsx(
          "w-12 h-12 rounded-full flex items-center justify-center",
          bgColor
        )}
      >
        <span className={clsx(accentColor, "w-6 h-6")}>{icon}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-text-secondary text-[15px] font-medium">{label}</p>
        <p className="text-2xl sm:text-3xl font-display font-bold mt-1 text-text-primary">
          {value}
        </p>
        {trend && (
          <p className="text-text-muted text-xs mt-1">{trend}</p>
        )}
      </div>
    </div>
  );
}
