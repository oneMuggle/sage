/**
 * TodoHeatmap — GitHub 风格的完成热力图（阶段 3）。
 *
 * 挂载时拉取最近 13 周（91 天）按日完成数；7 行（周日→周六）× N 列。
 * 颜色按当日完成数相对全区间最大值分 4 档；0 完成使用弱背景。
 */
import { Loader2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { todoClient } from '../../shared/api/todoClient';
import type { TodoHeatmapDay } from '../../shared/api/types';

const HEATMAP_DAYS = 91;

function levelFor(count: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0 || max <= 0) return 0;
  const ratio = count / max;
  if (ratio >= 0.75) return 4;
  if (ratio >= 0.5) return 3;
  if (ratio >= 0.25) return 2;
  return 1;
}

const LEVEL_CLASSES: Record<0 | 1 | 2 | 3 | 4, string> = {
  0: 'bg-bg-muted/60',
  1: 'bg-green-100 dark:bg-green-900/40',
  2: 'bg-green-300 dark:bg-green-700/60',
  3: 'bg-green-500 dark:bg-green-500/80',
  4: 'bg-green-700 dark:bg-green-400',
};

interface TodoHeatmapProps {
  /** 覆盖默认天数（测试用）。 */
  days?: number;
}

export function TodoHeatmap({ days = HEATMAP_DAYS }: TodoHeatmapProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<{ days: TodoHeatmapDay[]; total: number; max: number }>({
    days: [],
    total: 0,
    max: 0,
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    todoClient
      .heatmap(days)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  // 补齐到整周网格：首日前置空位（周日为行 0）。
  const cells = useMemo(() => {
    if (data.days.length === 0) return [];
    const firstDow = new Date(`${data.days[0].date}T00:00:00`).getDay();
    const padded: Array<TodoHeatmapDay | null> = Array.from({ length: firstDow }, () => null);
    padded.push(...data.days);
    while (padded.length % 7 !== 0) padded.push(null);
    const weeks: Array<Array<TodoHeatmapDay | null>> = [];
    for (let i = 0; i < padded.length; i += 7) {
      weeks.push(padded.slice(i, i + 7));
    }
    return weeks;
  }, [data.days]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-ui-xs text-text-muted py-2" role="status">
        <Loader2 className="w-3 h-3 animate-spin" />
        正在加载完成热力图…
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-ui-xs text-text-muted py-1" data-testid="todo-heatmap-error">
        热力图加载失败：{error}
      </p>
    );
  }

  return (
    <div data-testid="todo-heatmap" className="py-1">
      <div className="flex items-end justify-between mb-1">
        <span className="text-ui-xs text-text-muted">
          近 {HEATMAP_DAYS} 天完成 <span className="text-text font-medium">{data.total}</span> 条
        </span>
        <span className="flex items-center gap-1 text-ui-2xs text-text-muted">
          少
          {([0, 1, 2, 3, 4] as const).map((level) => (
            <span key={level} className={`w-2.5 h-2.5 rounded-sm ${LEVEL_CLASSES[level]}`} />
          ))}
          多
        </span>
      </div>
      <div className="flex gap-1 overflow-x-auto pb-1">
        {cells.map((week, weekIdx) => (
          <div key={weekIdx} className="flex flex-col gap-1">
            {week.map((day, dayIdx) =>
              day === null ? (
                <span key={dayIdx} className="w-2.5 h-2.5 rounded-sm" />
              ) : (
                <span
                  key={dayIdx}
                  title={`${day.date}：完成 ${day.count} 条`}
                  data-count={day.count}
                  className={`w-2.5 h-2.5 rounded-sm ${LEVEL_CLASSES[levelFor(day.count, data.max)]}`}
                />
              ),
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
