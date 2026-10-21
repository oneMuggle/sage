/**
 * HarnessDashboard — harness 组件 effectiveness 可视化（阶段 1）。
 *
 * 展示后端登记的 harness 组件清单及其实时效果指标：
 * 调用次数 / 成功率 / 平均延迟 / 满意度，并标记触发改进阈值的组件。
 *
 * 数据源：``GET /api/v1/harness/components``（见 ``backend/api/harness_routes.py``）。
 */

import React, { useCallback, useEffect, useState } from 'react';

import {
  HARNESS_TYPE_LABELS,
  type HarnessComponent,
  type HarnessComponentType,
} from '../../entities/harness/types';
import { harnessApi } from '../../shared/api/harnessApi';
import { Badge } from '../../shared/ui/Badge';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';
import { Progress } from '../../shared/ui/Progress';

/** 改进阈值 —— 与后端 ``HarnessComponent.needs_improvement`` 保持一致。 */
const SUCCESS_RATE_THRESHOLD = 0.8;
const LATENCY_THRESHOLD_MS = 1000;

type FilterValue = HarnessComponentType | 'all';

function formatPercent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function formatLatency(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

/** 组件卡片 —— 单个 harness 组件的指标展示。 */
function ComponentCard({ component }: { component: HarnessComponent }): React.JSX.Element {
  const { effectiveness } = component;
  const successRatePct = Math.round(effectiveness.success_rate * 100);
  const lowSuccess = effectiveness.success_rate < SUCCESS_RATE_THRESHOLD;
  const highLatency = effectiveness.avg_latency_ms > LATENCY_THRESHOLD_MS;

  return (
    <Card className="p-4" data-testid={`harness-component-${component.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium text-text">{component.name}</span>
            <Badge variant="outline">{HARNESS_TYPE_LABELS[component.type]}</Badge>
            {component.needs_improvement && (
              <Badge variant="destructive" data-testid="harness-needs-improvement">
                待改进
              </Badge>
            )}
          </div>
          <div className="mt-1 text-xs text-muted">
            {component.id} · v{component.version}
          </div>
        </div>
        <div className="shrink-0 text-right text-xs text-muted">
          <div>{effectiveness.usage_count} 次调用</div>
          {effectiveness.last_used_at && (
            <div>最后使用 {effectiveness.last_used_at.slice(0, 16).replace('T', ' ')}</div>
          )}
        </div>
      </div>

      <div className="mt-3 space-y-2">
        <div>
          <div className="flex justify-between text-xs">
            <span className={lowSuccess ? 'text-destructive' : 'text-muted'}>
              成功率 {formatPercent(effectiveness.success_rate)}
            </span>
          </div>
          <Progress value={successRatePct} />
        </div>
        <div className="flex justify-between text-xs">
          <span className={highLatency ? 'text-destructive' : 'text-muted'}>
            平均延迟 {formatLatency(effectiveness.avg_latency_ms)}
          </span>
          {effectiveness.user_satisfaction !== null && (
            <span className="text-muted">
              满意度 {formatPercent(effectiveness.user_satisfaction)}
            </span>
          )}
        </div>
      </div>
    </Card>
  );
}

export const HarnessDashboard: React.FC = () => {
  const [components, setComponents] = useState<HarnessComponent[]>([]);
  const [filter, setFilter] = useState<FilterValue>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const response = await harnessApi.listComponents();
      setComponents(response.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载 harness 组件失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visible =
    filter === 'all' ? components : components.filter((c) => c.type === filter);

  const presentTypes = Array.from(new Set(components.map((c) => c.type)));

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-muted">加载中…</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Harness 组件</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted">
            后端登记的 harness 组件及其调用效果。成功率低于 {formatPercent(SUCCESS_RATE_THRESHOLD)}
            、平均延迟超过 {LATENCY_THRESHOLD_MS}ms 或满意度偏低的组件会被标记为「待改进」。
          </p>
          {error && (
            <div className="mt-3 text-sm text-destructive" role="alert">
              {error}
              <button
                type="button"
                className="ml-2 underline"
                onClick={() => void load()}
              >
                重试
              </button>
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setFilter('all')}
              className={
                filter === 'all'
                  ? 'rounded-full bg-primary px-3 py-1 text-xs text-primary-foreground'
                  : 'rounded-full border border-border px-3 py-1 text-xs'
              }
            >
              全部 ({components.length})
            </button>
            {presentTypes.map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => setFilter(type)}
                className={
                  filter === type
                    ? 'rounded-full bg-primary px-3 py-1 text-xs text-primary-foreground'
                    : 'rounded-full border border-border px-3 py-1 text-xs'
                }
              >
                {HARNESS_TYPE_LABELS[type]} (
                {components.filter((c) => c.type === type).length})
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {visible.length === 0 ? (
        <div className="rounded-xl border border-border p-8 text-center text-sm text-muted">
          暂无 harness 组件。组件会在工具 / 技能首次被调用时自动登记。
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {visible.map((component) => (
            <ComponentCard key={component.id} component={component} />
          ))}
        </div>
      )}
    </div>
  );
};
