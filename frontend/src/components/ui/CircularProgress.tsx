import React from 'react';
import { Loader2 } from 'lucide-react';
import { clsx } from 'clsx';

interface CircularProgressProps {
  progress?: number; // 0 to 100
  size?: 'sm' | 'md' | 'lg';
  label?: string;
}

export const CircularProgress: React.FC<CircularProgressProps> = ({ 
  progress, 
  size = 'md',
  label 
}) => {
  const radius = 30;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = progress !== undefined ? circumference - (progress / 100) * circumference : 0;

  const sizeClasses = {
    sm: 'w-10 h-10',
    md: 'w-16 h-16',
    lg: 'w-24 h-24'
  };

  return (
    <div className="flex flex-col items-center justify-center gap-3">
      <div className={clsx("relative", sizeClasses[size])}>
        {/* Track */}
        <svg className="w-full h-full transform -rotate-90">
          <circle
            cx="50%"
            cy="50%"
            r={radius}
            stroke="currentColor"
            strokeWidth="4"
            fill="transparent"
            className="text-slate-700"
          />
          {/* Progress */}
          {progress !== undefined ? (
            <circle
              cx="50%"
              cy="50%"
              r={radius}
              stroke="currentColor"
              strokeWidth="4"
              fill="transparent"
              strokeDasharray={circumference}
              style={{ strokeDashoffset, transition: 'stroke-dashoffset 0.5s ease' }}
              className="text-indigo-500"
            />
          ) : (
            <circle
              cx="50%"
              cy="50%"
              r={radius}
              stroke="currentColor"
              strokeWidth="4"
              fill="transparent"
              className="text-indigo-500 animate-[dash_2s_ease-in-out_infinite]"
              style={{ strokeDasharray: '1, 150', strokeLinecap: 'round' }}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
            {progress !== undefined ? (
                <span className="text-[10px] font-bold text-white">{Math.round(progress)}%</span>
            ) : (
                <Loader2 className="w-1/3 h-1/3 text-indigo-400 animate-spin" />
            )}
        </div>
      </div>
      {label && <p className="text-sm font-medium text-slate-300">{label}</p>}
    </div>
  );
};
