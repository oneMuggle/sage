// src/widgets/skills/SkillAuditDrawer.tsx
//
// P2-2（可审计可回滚）：技能演化的审计台账 + 回滚入口。
//
// 背景：技能会被后台的 consolidation / draft 流程自动改动，而此前 UI 上
// 既看不到「谁在什么时候改了什么」，也没有任何退回上一版的能力 —— 用户只能
// 被动接受技能被改。后端两个端点早已存在（/skills/{name}/audit 与
// /skills/{name}/rollback），只是从来没被接出来。
//
// 两个**必须如实告知用户、不能假装**的后端限制：
// 1. 审计 list 接口不返回 before_content / after_content（后端 SELECT 就没取
//    这两列），所以这里只能做**元数据时间线**，展示不了 diff。
// 2. 回滚没有条目粒度 —— 后端取的是最近一条带快照的记录，所以只有
//    「回滚到上一版」这一个动作，做不到「点某条历史回到那一版」。
//
// 这两条都写在 UI 文案里，不做超出后端能力的承诺。

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { skillsApi } from '../../shared/api/skillsApi';
import type { SkillAuditEntry } from '../../shared/api/types';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';

const ACTION_LABELS: Record<SkillAuditEntry['action'], string> = {
  create: '创建',
  update: '更新',
  archive: '归档',
  restore: '恢复',
  rollback: '回滚',
  consolidation_note: '固化巡检记录',
};

const ACTOR_LABELS: Record<SkillAuditEntry['actor'], string> = {
  user: '你',
  system: '系统',
};

function formatTime(ms: number): string {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return '时间未知';
  return d.toLocaleString('zh-CN');
}

interface SkillAuditDrawerProps {
  skillName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 回滚成功后通知外层刷新技能列表（当前 SKILL.md 可能已被换回上一版） */
  onRolledBack?: () => void;
}

export function SkillAuditDrawer({
  skillName,
  open,
  onOpenChange,
  onRolledBack,
}: SkillAuditDrawerProps) {
  const [entries, setEntries] = useState<SkillAuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rollingBack, setRollingBack] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await skillsApi.getAudit(skillName);
      setEntries(res.entries);
    } catch (error) {
      // 不静默吞掉：审计读不到就明说，否则用户会以为「没变化过」。
      setLoadError(error instanceof Error ? error.message : '审计记录加载失败');
    } finally {
      setLoading(false);
    }
  }, [skillName]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const handleRollback = useCallback(async () => {
    // 不可逆写操作：先讲清后果再执行，且必须由用户显式确认。
    const confirmed = await confirmDialog({
      title: `回滚技能 ${skillName}？`,
      message: '将把该技能回滚到上一个有快照的版本。回滚不可撤销，当前版本会被覆盖。',
      confirmLabel: '回滚到上一版',
      danger: true,
    });
    if (!confirmed) return;
    setRollingBack(true);
    try {
      await skillsApi.rollback(skillName);
      toast.success(`已回滚 ${skillName} 到上一版本`);
      onRolledBack?.();
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '回滚失败');
    } finally {
      setRollingBack(false);
    }
  }, [skillName, onRolledBack, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>变更历史 · {skillName}</DialogTitle>
          <DialogDescription>
            记录该技能被创建、更新、归档与回滚的历史。回滚会退到**上一个**版本，不是选定的某一条。
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-80 overflow-y-auto py-1">
          {loading ? (
            <p className="text-sm text-text-secondary">加载中…</p>
          ) : loadError ? (
            <p role="alert" className="text-sm text-error">
              {loadError}
            </p>
          ) : entries.length === 0 ? (
            <p className="text-sm text-text-secondary">暂无变更记录</p>
          ) : (
            <ol className="space-y-2" data-testid="skill-audit-timeline">
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  data-testid="skill-audit-entry"
                  className="flex items-baseline gap-2 border-b border-border pb-2 text-sm last:border-b-0"
                >
                  <span className="shrink-0 text-text-secondary">
                    {formatTime(entry.created_at)}
                  </span>
                  <span className="shrink-0 font-medium text-text">
                    {ACTION_LABELS[entry.action] ?? entry.action}
                  </span>
                  <span className="shrink-0 text-xs text-text-tertiary">
                    {ACTOR_LABELS[entry.actor] ?? entry.actor}
                  </span>
                  {entry.source ? (
                    <span className="truncate text-xs text-text-tertiary">{entry.source}</span>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={handleRollback}
            disabled={rollingBack || loading || loadError !== null}
            data-testid="skill-audit-rollback"
            className="px-2 py-1 text-xs rounded border border-error text-error hover:bg-error/10 disabled:opacity-50"
          >
            {rollingBack ? '回滚中…' : '回滚到上一版'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default SkillAuditDrawer;
