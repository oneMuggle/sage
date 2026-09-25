/**
 * 约束编辑器 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.4
 * 创建/编辑约束的 Dialog
 */

import { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../shared/ui/Dialog/Dialog';
import { Button } from '../../shared/ui/Button';
import { Input } from '../../shared/ui/Input';
import { Textarea } from '../../shared/ui/Textarea';
import { projectApi, type ProjectConstraint } from '../../shared/api';

export interface ConstraintEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  constraint: ProjectConstraint | null; // null = create mode
  onSave: () => void;
}

export function ConstraintEditor({
  open,
  onOpenChange,
  projectId,
  constraint,
  onSave,
}: ConstraintEditorProps) {
  const [category, setCategory] = useState('');
  const [content, setContent] = useState('');
  const [triggerPattern, setTriggerPattern] = useState('');
  const [priority, setPriority] = useState(5);
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 编辑模式时填充表单
  useEffect(() => {
    if (constraint) {
      setCategory(constraint.category);
      setContent(constraint.content);
      setTriggerPattern(constraint.triggerPattern || '');
      setPriority(constraint.priority);
      setEnabled(constraint.enabled);
    } else {
      // 创建模式重置表单
      setCategory('');
      setContent('');
      setTriggerPattern('');
      setPriority(5);
      setEnabled(true);
    }
    setError(null);
  }, [constraint, open]);

  const handleSave = async () => {
    if (!category.trim() || !content.trim()) {
      setError('类别和内容不能为空');
      return;
    }

    try {
      setSaving(true);
      setError(null);

      if (constraint) {
        // 更新
        await projectApi.updateConstraint(constraint.id, {
          category: category.trim(),
          content: content.trim(),
          triggerPattern: triggerPattern.trim() || undefined,
          priority,
          enabled,
        });
      } else {
        // 创建
        await projectApi.createConstraint(projectId, {
          category: category.trim(),
          content: content.trim(),
          triggerPattern: triggerPattern.trim() || undefined,
          priority,
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
          <DialogTitle>{constraint ? '编辑约束' : '新建约束'}</DialogTitle>
          <DialogDescription>
            约束用于规范项目工作流程，定义代码风格、文档格式、Git 提交规范等规则。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium">类别 *</label>
            <Input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="例如: code-style, git-commit, writing-format"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">内容 *</label>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="描述具体的约束规则..."
              rows={4}
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">触发条件</label>
            <Input
              value={triggerPattern}
              onChange={(e) => setTriggerPattern(e.target.value)}
              placeholder="glob 模式（如 src/**/*.ts）或 'always'"
            />
            <p className="text-xs text-muted-foreground">留空表示 always（始终生效）</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">优先级 (1-10)</label>
              <Input
                type="number"
                min={1}
                max={10}
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">状态</label>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="enabled"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  className="h-4 w-4"
                />
                <label htmlFor="enabled" className="text-sm">
                  {enabled ? '启用' : '禁用'}
                </label>
              </div>
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
