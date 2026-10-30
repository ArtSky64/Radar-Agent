import React from 'react';

interface SparklineProps {
  data?: number[];
  color?: string;
  width?: number;
  height?: number;
}

export const Sparkline: React.FC<SparklineProps> = ({
  data = [10, 15, 12, 18, 24, 22, 30],
  color = '#6366f1',
  width = 54,
  height = 18,
}) => {
  if (!data || data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((val, idx) => {
    const x = (idx / (data.length - 1)) * (width - 4) + 2;
    const y = height - 3 - ((val - min) / range) * (height - 6);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const pathD = `M ${points.join(' L ')}`;
  const areaD = `M ${points[0]} L ${points.join(' L ')} L ${width - 2},${height} L 2,${height} Z`;

  const gradientId = `sparkline-grad-${Math.random().toString(36).substring(2, 7)}`;

  return (
    <svg width={width} height={height} className="overflow-visible shrink-0">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill={`url(#${gradientId})`} />
      <path
        d={pathD}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Точка на последнем значении */}
      <circle
        cx={(width - 4) + 2}
        cy={height - 3 - ((data[data.length - 1] - min) / range) * (height - 6)}
        r="1.75"
        fill={color}
      />
    </svg>
  );
};
