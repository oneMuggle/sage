/**
 * 创建自主目标弹窗
 *
 * 表单字段：名称、描述、触发模式（立即/条件）、执行条件配置、闲时窗口、执行预算。
 * 提交后通过 goalStore.create() 创建目标并关闭弹窗。
 */
import { useState } from 'react';

import { useGoalStore } from '../../entities/autonomous-goals/goalStore';
import type {
  ConditionType,
  CreateGoalInput,
  ExecutionCondition,
  TriggerMode,
} from '../../entities/autonomous-goals/types';
import { Button } from '../../shared/ui/Button';
import { Input } from '../../shared/ui/Input';
import { Modal } from '../../shared/ui/Modal';

interface CreateGoalModalProps {
  isOpen: boolean;
  onClose: () => void;
}

// 条件类型选项
const CONDITION_OPTIONS: { value: ConditionType; label: string; description: string }[] = [
  { value: 'idle', label: '空闲', description: '用户空闲 N 分钟后执行' },
  { value: 'time_window', label: '时间段', description: '在指定时间段内执行' },
  { value: 'no_active', label: '无活动任务', description: '无其他运行中目标时执行' },
  { value: 'manual', label: '手动触发', description: '不自动触发，需用户手动启动' },
];

function defaultCondition(type: ConditionType): ExecutionCondition {
  switch (type) {
    case 'idle':
      return { type, params: { min_idle_minutes: 15 } };
    case 'time_window':
      return { type, params: { start: '22:00', end: '06:00' } };
    case 'no_active':
      return { type, params: {} };
    case 'manual':
      return { type, params: {} };
    default:
      return { type, params: {} };
  }
}

export function CreateGoalModal({ isOpen, onClose }: CreateGoalModalProps) {
  const create = useGoalStore((s) => s.create);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [triggerMode, setTriggerMode] = useState<TriggerMode>('immediate');
  const [conditions, setConditions] = useState<ExecutionCondition[]>([]);
  const [offPeakStart, setOffPeakStart] = useState('22:00');
  const [offPeakEnd, setOffPeakEnd] = useState('06:00');
  const [maxRounds, setMaxRounds] = useState(10);
  const [maxHours, setMaxHours] = useState(8);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetForm = () => {
    setName('');
    setDescription('');
    setTriggerMode('immediate');
    setConditions([]);
    setOffPeakStart('22:00');
    setOffPeakEnd('06:00');
    setMaxRounds(10);
    setMaxHours(8);
    setError(null);
  };

  const addCondition = (type: ConditionType) => {
    setConditions((prev) => [...prev, defaultCondition(type)]);
  };

  const removeCondition = (index: number) => {
    setConditions((prev) => prev.filter((_, i) => i !== index));
  };

  const updateConditionParams = (index: number, key: string, value: unknown) => {
    setConditions((prev) =>
      prev.map((c, i) =>
        i === index ? { ...c, params: { ...c.params, [key]: value } } : c,
      ),
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !description.trim()) return;

    setSubmitting(true);
    setError(null);
    try {
      const input: CreateGoalInput = {
        name: name.trim(),
        description: description.trim(),
        time_window: {
          off_peak_start: offPeakStart,
          off_peak_end: offPeakEnd,
        },
        budget: {
          max_rounds: maxRounds,
          max_hours: maxHours,
        },
        trigger_mode: triggerMode,
        execution_conditions: triggerMode === 'conditional' ? conditions : [],
      };
      await create(input);
      resetForm();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => {
        resetForm();
        onClose();
      }}
      title="创建自主目标"
      footer={
        <div className="flex justify-end gap-2 px-6 py-4">
          <Button
            variant="ghost"
            onClick={() => {
              resetForm();
              onClose();
            }}
          >
            取消
          </Button>
          <Button
            variant="primary"
            disabled={submitting || !name.trim() || !description.trim()}
            onClick={() => void handleSubmit}
          >
            {submitting ? '创建中...' : '创建'}
          </Button>
        </div>
      }
    >
      <form onSubmit={(e) => void handleSubmit(e)} className="px-6 py-4 space-y-4">
        {error && (
          <div
            className="px-3 py-2 bg-destructive/10 text-destructive text-sm rounded"
            role="alert"
          >
            {error}
          </div>
        )}

        <div className="space-y-1.5">
          <label className="text-sm font-medium text-text">目标名称</label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：重构认证模块"
            className="w-full"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium text-text">目标描述</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="详细描述要完成的目标..."
            rows={3}
            className="w-full border border-border rounded-md px-3 py-2 text-sm bg-surface focus:outline-none focus:border-primary resize-none"
          />
        </div>

        {/* 触发模式选择 */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-text">触发模式</label>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="triggerMode"
                value="immediate"
                checked={triggerMode === 'immediate'}
                onChange={() => setTriggerMode('immediate')}
                className="text-primary"
              />
              <span className="text-sm text-text">立即执行</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="triggerMode"
                value="conditional"
                checked={triggerMode === 'conditional'}
                onChange={() => setTriggerMode('conditional')}
                className="text-primary"
              />
              <span className="text-sm text-text">闲时执行</span>
            </label>
          </div>
          <p className="text-xs text-text-muted">
            {triggerMode === 'immediate'
              ? '立即开始执行，受闲时时间窗口约束'
              : '等待条件满足后自动执行（空闲、资源充足等）'}
          </p>
        </div>

        {/* 条件配置面板（仅 CONDITIONAL 模式显示） */}
        {triggerMode === 'conditional' && (
          <div className="space-y-3 p-3 bg-surface-secondary rounded-lg border border-border">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-text">执行条件</label>
              <select
                className="text-xs border border-border rounded px-2 py-1 bg-surface"
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) {
                    addCondition(e.target.value as ConditionType);
                    e.target.value = '';
                  }
                }}
              >
                <option value="" disabled>
                  + 添加条件
                </option>
                {CONDITION_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {conditions.length === 0 && (
              <p className="text-xs text-text-muted">
                未添加条件，将使用默认条件（空闲 15 分钟 + 闲时时间窗口）
              </p>
            )}

            {conditions.map((cond, idx) => (
              <div
                key={idx}
                className="flex items-center gap-2 p-2 bg-surface rounded border border-border"
              >
                <span className="text-xs font-medium text-text min-w-[60px]">
                  {CONDITION_OPTIONS.find((o) => o.value === cond.type)?.label ?? cond.type}
                </span>

                {cond.type === 'idle' && (
                  <div className="flex items-center gap-1">
                    <Input
                      type="number"
                      min={1}
                      max={120}
                      value={(cond.params.min_idle_minutes as number) ?? 15}
                      onChange={(e) =>
                        updateConditionParams(idx, 'min_idle_minutes', Number(e.target.value))
                      }
                      className="w-16 text-xs"
                    />
                    <span className="text-xs text-text-muted">分钟</span>
                  </div>
                )}

                {cond.type === 'time_window' && (
                  <div className="flex items-center gap-1">
                    <Input
                      type="time"
                      value={(cond.params.start as string) ?? '22:00'}
                      onChange={(e) => updateConditionParams(idx, 'start', e.target.value)}
                      className="w-24 text-xs"
                    />
                    <span className="text-xs text-text-muted">至</span>
                    <Input
                      type="time"
                      value={(cond.params.end as string) ?? '06:00'}
                      onChange={(e) => updateConditionParams(idx, 'end', e.target.value)}
                      className="w-24 text-xs"
                    />
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => removeCondition(idx)}
                  className="ml-auto text-xs text-destructive hover:text-destructive/80"
                >
                  移除
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-text">闲时开始</label>
            <Input
              type="time"
              value={offPeakStart}
              onChange={(e) => setOffPeakStart(e.target.value)}
              className="w-full"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-text">闲时结束</label>
            <Input
              type="time"
              value={offPeakEnd}
              onChange={(e) => setOffPeakEnd(e.target.value)}
              className="w-full"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-text">最大轮次</label>
            <Input
              type="number"
              min={1}
              max={1000}
              value={maxRounds}
              onChange={(e) => setMaxRounds(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-text">最大时长（小时）</label>
            <Input
              type="number"
              min={0.1}
              max={24}
              step={0.5}
              value={maxHours}
              onChange={(e) => setMaxHours(Number(e.target.value))}
              className="w-full"
            />
          </div>
        </div>
      </form>
    </Modal>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function formatCreateGoalModalSummary(
  isOpen: boolean,
  maxHours = 4,
  maxTokens = 500_000,
): string {
  const safeHours = Math.max(0, Number(maxHours) || 0);
  const safeTokens = Math.max(0, Math.trunc(maxTokens));
  return `open=${Boolean(isOpen)} · maxHours=${safeHours} · maxTokens=${safeTokens}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatCreateGoalModalJson(
  isOpen: boolean,
  maxHours = 4,
  maxTokens = 500_000,
): string {
  return JSON.stringify({
    isOpen: Boolean(isOpen),
    maxHours: Math.max(0, Number(maxHours) || 0),
    maxTokens: Math.max(0, Math.trunc(maxTokens)),
  });
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditCreateGoalModalGovernance(
  state: {
    isOpen?: boolean;
    maxTurns?: number;
  } = {},
): {
  module: 'src/features/autonomous-goals/CreateGoalModal.tsx';
  phase: 'P158';
  isOpen: boolean;
  maxTurns: number;
  healthy: boolean;
} {
  const isOpen = state.isOpen === true;
  const maxTurns =
    typeof state.maxTurns === 'number' && Number.isFinite(state.maxTurns)
      ? Math.max(0, Math.trunc(state.maxTurns))
      : 10;
  return {
    module: 'src/features/autonomous-goals/CreateGoalModal.tsx',
    phase: 'P158',
    isOpen,
    maxTurns,
    healthy: maxTurns >= 1 && maxTurns <= 100,
  };
}
