import { clsx } from "clsx";

interface OCRConfidenceMeterProps {
  confidence: number;
  size?: number;
}

export function OCRConfidenceMeter({
  confidence,
  size = 120,
}: OCRConfidenceMeterProps) {
  const pct = Math.round(confidence * 100);
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (confidence * circumference);
  const center = size / 2;

  const color =
    pct >= 80
      ? "text-accent-green"
      : pct >= 65
        ? "text-accent-gold"
        : "text-accent-red";

  const strokeColor =
    pct >= 80
      ? "#10B981"
      : pct >= 65
        ? "#F59E0B"
        : "#EF4444";

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="#E2E8F0"
          strokeWidth="6"
        />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={clsx("font-display font-bold", color, size <= 60 ? "text-sm" : "text-xl")}>
          {pct}%
        </span>
      </div>
    </div>
  );
}
