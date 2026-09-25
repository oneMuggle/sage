/**
 * 里程碑编辑器 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.5
 * 创建/编辑里程碑的 Dialog
 */

import { useState, useEffect } from 'react';

import { projectApi, type ProjectMilestone } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../shared/ui/Dialog/Dialog';
import { Input } from '../../shared/ui/Input';
import { Textarea } from '../../shared/ui/Textarea';

export interface MilestoneEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  milestone: ProjectMilestone | null; // null = create mode
  onSave: () => void;
}

export function MilestoneEditor({
  open,
  onOpenChange,
  projectId,
  milestone,
  onSave,
}: MilestoneEditorProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [stage, setStage] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [status, setStatus] = useState('pending');
  const [sortOrder, setSortOrder] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 编辑模式时填充表单
  useEffect(() => {
    if (milestone) {
      setTitle(milestone.title);
      setDescription(milestone.description || '');
      setStage(milestone.stage || '');
      setDueDate(milestone.dueDate || '');
      setStatus(milestone.status);
      setSortOrder(milestone.sortOrder);
    } else {
      // 创建模式重置表单
      setTitle('');
      setDescription('');
      setStage('');
      setDueDate('');
      setStatus('pending');
      setSortOrder(0);
    }
    setError(null);
  }, [milestone, open]);

  const handleSave = async () => {
    if (!title.trim()) {
      setError('标题不能为空');
      return;
    }

    try {
      setSaving(true);
      setError(null);

      if (milestone) {
        // 更新
        await projectApi.updateMilestone(milestone.id, {
          title: title.trim(),
          description: description.trim() || undefined,
          stage: stage.trim() || undefined,
          dueDate: dueDate || undefined,
          status,
          sortOrder,
        });
      } else {
        // 创建
        await projectApi.createMilestone(projectId, {
          title: title.trim(),
          description: description.trim() || undefined,
          stage: stage.trim() || undefined,
          dueDate: dueDate || undefined,
          status,
          sortOrder,
        });
      }

      onSave();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{milestone ? '编辑里程碑' : '新建里程碑'}</DialogTitle>
          <DialogDescription>里程碑用于标记项目的重要节点和目标，跟踪项目进度。</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium">标题 *</label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如: 完成 MVP、发布 v1.0"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">描述</label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述里程碑的具体目标和交付物..."
              rows={3}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">阶段</label>
              <Input
                value={stage}
                onChange={(e) => setStage(e.target.value)}
                placeholder="例如: 开发阶段、测试阶段"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">截止日期</label>
              <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">状态</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="pending">待开始</option>
                <option value="in_progress">进行中</option>
                <option value="completed">已完成</option>
                <option value="blocked">阻塞</option>
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">排序顺序</label>
              <Input
                type="number"
                value={sortOrder}
                onChange={(e) => setSortOrder(Number(e.target.value))}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
