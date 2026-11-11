import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, type LabelProps } from "recharts";
import { formatDate } from "../lib/format";
import { useTokens } from "../lib/theme";

/**
 * Horizontal bars for magnitude (rubric dimensions, topic scores). Plain HTML so the mark specs hold exactly:
 * <= 24px thick, 4px rounded data-end square at the baseline, value at the tip, hover/focus tooltip.
 */
export function BarList({ items, max, format = (v) => String(v), caption }: {
  items: { label: string; value: number; detail?: string }[];
  max: number;
  format?: (v: number) => string;
  caption: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  return (
    <figure>
      <figcaption className="sr-only">{caption}</figcaption>
      <ul className="space-y-3">
        {items.map((it, i) => (
          <li
            key={it.label}
            tabIndex={0}
            onPointerEnter={() => setActive(i)}
            onPointerLeave={() => setActive(null)}
            onFocus={() => setActive(i)}
            onBlur={() => setActive(null)}
            className="group relative grid grid-cols-[minmax(6rem,9rem)_1fr] items-center gap-3 rounded-md py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label={`${it.label}: ${format(it.value)}${it.detail ? `, ${it.detail}` : ""}`}
          >
            <span className="truncate text-sm text-ink-2">{it.label}</span>
            <span className="flex items-center gap-2">
              <span
                className="h-4 rounded-r-[4px] bg-series-1 transition-opacity group-hover:opacity-80"
                style={{ width: `${Math.max(2, (it.value / max) * 100)}%`, maxWidth: "calc(100% - 3rem)" }}
              />
              <span className="text-sm font-medium tabular-nums text-ink">{format(it.value)}</span>
            </span>
            {active === i && it.detail && (
              <span role="tooltip" className="pointer-events-none absolute -top-8 left-36 z-10 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-xs text-page shadow">
                <strong>{format(it.value)}</strong> <span className="opacity-80">{it.detail}</span>
              </span>
            )}
          </li>
        ))}
      </ul>
    </figure>
  );
}

export interface TrendPoint {
  created_at: string;
  overall_score: number;
  role: string;
  interview_type: string;
}

/** Overall score over time: one series, so no legend; crosshair tooltip; end value labelled. */
export function ScoreTrend({ points }: { points: TrendPoint[] }) {
  const t = useTokens(["series-1", "surface", "line", "axis", "muted", "ink", "ink-2"] as const);
  const data = points.map((p, i) => ({ ...p, i, label: formatDate(p.created_at) }));
  const last = data.length - 1;

  return (
    <div className="h-64" role="img" aria-label={`Overall score across ${points.length} interviews, latest ${points[last]?.overall_score ?? "-"}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 16, right: 36, bottom: 4, left: -16 }}>
          <CartesianGrid vertical={false} stroke={t.line} />
          <XAxis dataKey="label" tick={{ fill: t.muted, fontSize: 12 }} tickLine={false} axisLine={{ stroke: t.axis }} interval="preserveStartEnd" minTickGap={24} />
          <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: t.muted, fontSize: 12 }} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ stroke: t.axis, strokeWidth: 1 }} content={({ active, payload }) => <TrendTooltip active={active} point={payload?.[0]?.payload} />} />
          <Line
            type="monotone"
            dataKey="overall_score"
            stroke={t["series-1"]}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            isAnimationActive={false}
            dot={{ r: 4, fill: t["series-1"], stroke: t.surface, strokeWidth: 2 }}
            activeDot={{ r: 6, fill: t["series-1"], stroke: t.surface, strokeWidth: 2 }}
            label={({ x, y, index, value }: LabelProps) =>
              index === last ? (
                <text x={Number(x) + 10} y={Number(y) + 4} fill={t.ink} fontSize={12} fontWeight={600}>{String(value)}</text>
              ) : (
                <g />
              )
            }
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function TrendTooltip({ active, point: p }: { active?: boolean; point?: TrendPoint }) {
  if (!active || !p) return null;
  return (
    <div className="rounded-lg bg-surface px-3 py-2 text-xs shadow-md ring-1 ring-ring">
      <p className="text-base font-semibold text-ink">{p.overall_score}<span className="text-xs font-normal text-muted">/100</span></p>
      <p className="text-ink-2">{p.role}</p>
      <p className="text-muted">{formatDate(p.created_at, true)}</p>
    </div>
  );
}
