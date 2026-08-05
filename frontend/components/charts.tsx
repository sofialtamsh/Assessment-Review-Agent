"use client";

// Small dependency-free SVG charts with a restrained, accessible palette.

export function Donut({
  data,
  size = 148,
  thickness = 20,
}: {
  data: { label: string; value: number; color: string }[];
  size?: number;
  thickness?: number;
}) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circ = 2 * Math.PI * r;
  let offset = 0;

  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#eee" strokeWidth={thickness} />
        {data.map((d, i) => {
          const len = (d.value / total) * circ;
          const el = (
            <circle
              key={i}
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={d.color}
              strokeWidth={thickness}
              strokeDasharray={`${len} ${circ - len}`}
              strokeDashoffset={-offset}
              transform={`rotate(-90 ${cx} ${cy})`}
              strokeLinecap="butt"
            />
          );
          offset += len;
          return el;
        })}
        <text x={cx} y={cy - 2} textAnchor="middle" className="fill-ink" fontSize="20" fontWeight={700}>
          {total}
        </text>
        <text x={cx} y={cy + 15} textAnchor="middle" fill="#9aa" fontSize="10">
          questions
        </text>
      </svg>
      <ul className="space-y-1.5 text-sm">
        {data.map((d, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: d.color }} />
            <span className="text-black/60">{d.label}</span>
            <span className="ml-auto font-semibold tabular-nums">{d.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BarChart({
  data,
  color = "#6366f1",
  height = 150,
}: {
  data: { label: string; value: number }[];
  color?: string;
  height?: number;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  // reserve space for the value label (top) + the fixed-height text label (bottom)
  // so the tallest bar's number never overflows above the chart into the heading.
  const barSpace = height - 60;
  return (
    <div className="flex items-end gap-3" style={{ height }}>
      {data.map((d, i) => (
        <div key={i} className="flex flex-1 flex-col items-center justify-end gap-1.5">
          <span className="text-xs font-semibold tabular-nums">{d.value}</span>
          <div
            className="w-full rounded-t-md transition-all"
            style={{
              height: `${(d.value / max) * barSpace}px`,
              background: color,
              minHeight: d.value > 0 ? 4 : 0,
            }}
          />
          {/* fixed-height label region so multi-line labels don't push their bar up */}
          <span className="flex h-8 items-start justify-center text-center text-[11px] leading-tight text-black/50">
            {d.label}
          </span>
        </div>
      ))}
    </div>
  );
}
