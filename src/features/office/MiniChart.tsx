// src/features/office/MiniChart.tsx
//
// M6d: 结构化预览的迷你 SVG 柱状图。数据来自后端已提取的原生图表
// （PPT _extract_charts / Excel _extract_sheet_charts），不引入图表库。
// 负数向下画、零值为基线；数值非有限时按 0 处理（后端只输出合法数值，
// 这里是对历史缓存的防御）。

const VIEW_W = 120;
const VIEW_H = 40;
const GROUP_FILL = 0.75;
const SERIES_OPACITY = [1, 0.6, 0.35];

export interface MiniChartSeries {
  name: string | null;
  values: unknown[];
}

interface MiniChartProps {
  categories: (string | null)[];
  series: MiniChartSeries[];
}

function toFinite(value: unknown): number {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** True when at least one series carries renderable points. */
// eslint-disable-next-line react-refresh/only-export-components
export function hasChartPoints(series: MiniChartSeries[]): boolean {
  return series.some((s) => s.values.length > 0);
}

export function MiniChart({ categories, series }: MiniChartProps) {
  const points = Math.max(0, categories.length, ...series.map((s) => s.values.length));
  if (points === 0 || series.length === 0) return null;

  const numeric = series.map((s) => s.values.map(toFinite));
  const all = numeric.flat();
  const maxVal = Math.max(0, ...all);
  const minVal = Math.min(0, ...all);
  const span = maxVal - minVal;
  if (span === 0) return null;

  const yFor = (v: number) => VIEW_H - ((v - minVal) / span) * VIEW_H;
  const zeroY = yFor(0);
  const groupWidth = VIEW_W / points;
  const barWidth = Math.max(0.6, (groupWidth * GROUP_FILL) / series.length);
  const legend = series
    .map((s) => s.name)
    .filter((name): name is string => Boolean(name))
    .join(', ');

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="none"
      className="w-full h-10 text-primary"
      role="img"
      aria-label={legend || 'chart'}
      data-testid="office-mini-chart"
    >
      <line
        x1={0}
        x2={VIEW_W}
        y1={zeroY}
        y2={zeroY}
        className="stroke-border"
        strokeWidth={0.4}
        vectorEffect="non-scaling-stroke"
      />
      {numeric.map((values, si) =>
        values.slice(0, points).map((value, pi) => {
          if (value === 0) return null;
          const y = yFor(value);
          return (
            <rect
              key={`${si}-${pi}`}
              x={pi * groupWidth + (groupWidth - barWidth * series.length) / 2 + si * barWidth}
              y={Math.min(y, zeroY)}
              width={barWidth}
              height={Math.max(0.4, Math.abs(y - zeroY))}
              fill="currentColor"
              opacity={SERIES_OPACITY[si % SERIES_OPACITY.length]}
            >
              <title>
                {`${categories[pi] ?? pi + 1}: ${value}${
                  series[si].name ? ` (${series[si].name})` : ''
                }`}
              </title>
            </rect>
          );
        }),
      )}
    </svg>
  );
}
