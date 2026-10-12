/**
 * AI 任务分解对话框 (M1, 2026-10-12)
 *
 * 用户在里程碑管理页点击「AI 任务分解」按钮打开此对话框。
 * 流程：
 * 1. 输入需求描述（必填）+ 补充上下文（可选）
 * 2. 点击「生成方案」→ 调用 LLM 预览
 * 3. 展示里程碑树预览（可嵌套）
 * 4. 用户确认后点击「采纳」→ 批量创建里程碑
 */

import { Sparkles, Loader2, ChevronRight, ChevronDown, CheckCircle2 } from 'lucide-react';
import { useState, useCallback } from 'react';

import { projectApi, type PreviewMilestoneNode } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../shared/ui/Dialog/Dialog';
import { Textarea } from '../../shared/ui/Textarea';

export interface TaskDecomposeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  /** 采纳后回调（外部重新拉取里程碑列表） */
  onApplied: () => void;
}

type Phase = 'input' | 'loading' | 'preview' | 'applying';

export function TaskDecomposeDialog({
  open,
  onOpenChange,
  projectId,
  onApplied,
}: TaskDecomposeDialogProps) {
  const [phase, setPhase] = useState<Phase>('input');
  const [requirement, setRequirement] = useState('');
  const [context, setContext] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [reasoning, setReasoning] = useState('');
  const [milestones, setMilestones] = useState<PreviewMilestoneNode[]>([]);
  const [totalCount, setTotalCount] = useState(0);

  const handlePreview = useCallback(async () => {
    if (!requirement.trim()) return;
    setError(null);
    setPhase('loading');
    try {
      const result = await projectApi.decomposePreview(projectId, {
        requirement: requirement.trim(),
        context: context.trim() || undefined,
      });
      setReasoning(result.reasoning);
      setMilestones(result.milestones);
      setTotalCount(result.totalCount);
      setPhase('preview');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 分解失败');
      setPhase('input');
    }
  }, [projectId, requirement, context]);

  const handleApply = useCallback(async () => {
    setError(null);
    setPhase('applying');
    try {
      await projectApi.decomposeApply(projectId, { milestones });
      onApplied();
      resetAndClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建里程碑失败');
      setPhase('preview');
    }
  }, [projectId, milestones, onApplied]);

  const resetAndClose = () => {
    setPhase('input');
    setRequirement('');
    setContext('');
    setError(null);
    setReasoning('');
    setMilestones([]);
    setTotalCount(0);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={resetAndClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            AI 智能任务分解
          </DialogTitle>
          <DialogDescription>描述你的需求，AI 将自动拆解为里程碑树</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              {error}
            </div>
          )}

          {/* 输入阶段 */}
          {(phase === 'input' || phase === 'loading') && (
            <>
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  需求描述 <span className="text-red-500">*</span>
                </label>
                <Textarea
                  placeholder="例如：实现用户认证系统，包括注册、登录、JWT token 管理..."
                  value={requirement}
                  onChange={(e) => setRequirement(e.target.value)}
                  rows={4}
                  disabled={phase === 'loading'}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">补充上下文（可选）</label>
                <Textarea
                  placeholder="例如：使用 NextAuth.js，数据库用 PostgreSQL..."
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                  rows={2}
                  disabled={phase === 'loading'}
                />
              </div>
            </>
          )}

          {/* 预览阶段 */}
          {phase === 'preview' && (
            <div className="space-y-3">
              {reasoning && (
                <div className="rounded-lg border bg-muted/50 p-3 text-sm text-muted-foreground">
                  <span className="font-medium text-foreground">分解思路：</span> {reasoning}
                </div>
              )}
              <div className="space-y-1">
                <div className="text-sm font-medium">将创建 {totalCount} 个里程碑：</div>
                <div className="rounded-lg border p-3 space-y-1">
                  {milestones.map((ms, idx) => (
                    <MilestoneTreeItem key={idx} node={ms} depth={0} />
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 应用中 */}
          {phase === 'applying' && (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在创建里程碑...
            </div>
          )}
        </div>

        <DialogFooter>
          {(phase === 'input' || phase === 'loading') && (
            <>
              <Button variant="secondary" onClick={resetAndClose}>
                取消
              </Button>
              <Button onClick={handlePreview} disabled={!requirement.trim() || phase === 'loading'}>
                {phase === 'loading' ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    分析中...
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    生成方案
                  </>
                )}
              </Button>
            </>
          )}
          {phase === 'preview' && (
            <>
              <Button variant="secondary" onClick={() => setPhase('input')}>
                重新输入
              </Button>
              <Button onClick={handleApply}>
                <CheckCircle2 className="mr-2 h-4 w-4" />
                采纳方案
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 递归渲染里程碑树节点 */
function MilestoneTreeItem({ node, depth }: { node: PreviewMilestoneNode; depth: number }) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;

  return (
    <div style={{ paddingLeft: depth * 20 }}>
      <div className="flex items-start gap-1.5 py-1">
        {hasChildren ? (
          <button
            type="button"
            className="mt-0.5 shrink-0 rounded p-0.5 hover:bg-muted"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </button>
        ) : (
          <span className="w-5 shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{node.title}</span>
            {node.estimatedDays != null && (
              <Badge variant="outline" className="text-xs">
                {node.estimatedDays}天
              </Badge>
            )}
            {node.stage && (
              <Badge variant="secondary" className="text-xs">
                {node.stage}
              </Badge>
            )}
          </div>
          {node.description && (
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{node.description}</p>
          )}
        </div>
      </div>
      {expanded && hasChildren && (
        <div>
          {node.children.map((child: PreviewMilestoneNode, idx: number) => (
            <MilestoneTreeItem key={idx} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
