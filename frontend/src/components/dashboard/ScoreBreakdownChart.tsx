import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { CriterionScore } from "@/types";

interface ScoreBreakdownChartProps {
  scores: CriterionScore[];
}

export function ScoreBreakdownChart({ scores }: ScoreBreakdownChartProps) {
  const data = scores.map((s) => ({
    criterion: s.criterionId,
    score: s.marksAwarded,
    max: s.maxMarks,
    percentage: s.maxMarks > 0 ? (s.marksAwarded / s.maxMarks) * 100 : 0,
  }));

  return (
    <div className="w-full h-64">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
          <PolarGrid stroke="#E2E8F0" />
          <PolarAngleAxis
            dataKey="criterion"
            tick={{ fill: "#64748B", fontSize: 11 }}
          />
          <PolarRadiusAxis
            domain={[0, 100]}
            tick={{ fill: "#94A3B8", fontSize: 10 }}
          />
          <Radar
            name="Score %"
            dataKey="percentage"
            stroke="#3B82F6"
            fill="#3B82F6"
            fillOpacity={0.2}
            strokeWidth={2}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#FFFFFF",
              border: "1px solid #E2E8F0",
              borderRadius: "8px",
              color: "#0F172A",
              fontSize: "12px",
              boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
            }}
            formatter={(value: number) => [`${value.toFixed(1)}%`, "Score"]}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
