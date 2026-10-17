/**
 * 创建自主目标弹窗
 *
 * 表单字段：名称、描述、闲时窗口、执行预算。
 * 提交后通过 goalStore.create() 创建目标并关闭弹窗。
 */
import { useState } from 'react';

import { useGoalStore } from '../../entities/autonomous-goals/goalStore';
import type { CreateGoalInput } from '../../entities/autonomous-goals/types';
import { Button } from '../../shared/ui/Button';
import { Input } from '../../shared/ui/Input';
import { Modal } from '../../shared/ui/Modal';

interface CreateGoalModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function CreateGoalModal({ isOpen, onClose }: CreateGoalModalProps) {
  const create = useGoalStore((s) => s.create);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [offPeakStart, setOffPeakStart] = useState('22:00');
  const [offPeakEnd, setOffPeakEnd] = useState('06:00');
  const [maxRounds, setMaxRounds] = useState(10);
  const [maxHours, setMaxHours] = useState(8);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetForm = () => {
    setName('');
    setDescription('');
    setOffPeakStart('22:00');
    setOffPeakEnd('06:00');
    setMaxRounds(10);
    setMaxHours(8);
    setError(null);
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
