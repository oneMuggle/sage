import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  specialistApi,
  type SpecialistVersionDiff,
  type SpecialistVersionMeta,
} from '../../shared/api/specialistApi';
import type { AgentProfile } from '../../shared/api/types/domainEntityTypes';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';

interface VersionHistoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 当前查看的专家；null 时不请求。 */
  agent: AgentProfile | null;
  /** 回滚成功后回调（父组件用来刷新列表）。 */
  onRolledBack?: (profile: AgentProfile) => void;
}

const REASON_LABELS: Record<SpecialistVersionMeta['reason'], string> = {
  create: '创建',
  update: '更新',
  rollback: '回滚',
};

/** diff 字段的中文标签（与后端 DIFF_FIELD_WHITELIST 对齐，未知字段回退原字段名）。 */
const FIELD_LABELS: Record<string, string> = {
  name: '名称',
  role: '角色',
  system_prompt: '人设提示词',
  description: '描述',
  permission_mode: '权限模式',
  source: '来源',
  max_iterations: '最大迭代数',
  enabled: '启用',
  version: '版本号',
  tools: '工具',
  memory_access: '记忆访问',
  skills: '技能',
  knowledge_bindings: '知识绑定',
  memory_policy: '记忆策略',
  persona_ui: '外观配置',
  model_config: '模型配置',
};

function formatTimestamp(ms: number): string {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '（空）';
  if (typeof value === 'string') return value === '' ? '（空字符串）' : value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * 版本历史对话框（M4-T3）。
 *
 * 列表展示专家快照（版本号 / 类型 / 时间）；「对比」调用后端字段级 diff，
 * 与当前最新版本比较；「回滚」两段式确认后调用 rollback 端点，
 * 成功后回调父组件刷新。
 */
export function VersionHistoryDialog({
  open,
  onOpenChange,
  agent,
  onRolledBack,
}: VersionHistoryDialogProps) {
  const [versions, setVersions] = useState<SpecialistVersionMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [diffFor, setDiffFor] = useState<number | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [diffs, setDiffs] = useState<SpecialistVersionDiff[] | null>(null);
  const [pendingRollback, setPendingRollback] = useState<number | null>(null);
  const [rollingBack, setRollingBack] = useState(false);

  const agentId = agent?.id ?? null;

  const loadVersions = useCallback(async (id: string) => {
    setLoading(true);
    setLoadingError(null);
    try {
      const list = await specialistApi.listVersions(id);
      setVersions(list);
    } catch (err) {
      setLoadingError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open || !agentId) return;
    setVersions([]);
    setDiffs(null);
    setDiffFor(null);
    setDiffError(null);
    setPendingRollback(null);
    void loadVersions(agentId);
  }, [open, agentId, loadVersions]);

  const handleDiff = useCallback(
    async (meta: SpecialistVersionMeta) => {
      if (!agentId) return;
      const latest = versions[0]?.version;
      if (latest === undefined || latest === meta.version) return;
      if (diffFor === meta.version) {
        // 再次点击收起
        setDiffFor(null);
        setDiffs(null);
        setDiffError(null);
        return;
      }
      setDiffFor(meta.version);
      setDiffs(null);
      setDiffError(null);
      setDiffLoading(true);
      try {
        const changes = await specialistApi.diffVersions(
          agentId,
          meta.version,
          latest,
        );
        setDiffs(changes);
      } catch (err) {
        setDiffError(err instanceof Error ? err.message : String(err));
      } finally {
        setDiffLoading(false);
      }
    },
    [agentId, versions, diffFor],
  );

  const handleRollback = useCallback(
    async (version: number) => {
      if (!agentId) return;
      setRollingBack(true);
      try {
        const profile = await specialistApi.rollbackAgent(agentId, version);
        toast.success(`已回滚到第 ${version} 版`);
        setPendingRollback(null);
        onRolledBack?.(profile);
        await loadVersions(agentId);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        toast.error(`回滚失败：${message}`);
      } finally {
        setRollingBack(false);
      }
    },
    [agentId, onRolledBack, loadVersions],
  );

  const latestVersion = versions[0]?.version;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>版本历史{agent ? ` · ${agent.name}` : ''}</DialogTitle>
          <DialogDescription>
            查看人设变更快照；可将专家回滚到任意历史版本（回滚会生成一个新版本）。
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4">
          {loading ? (
            <div className="rounded-lg border border-border bg-bg-subtle/40 p-6 text-center text-sm text-muted">
              加载版本…
            </div>
          ) : loadingError ? (
            <div className="rounded-lg border border-border border-error/30 bg-bg-subtle/40 p-6 text-center text-sm text-error">
              加载版本失败：{loadingError}
            </div>
          ) : versions.length === 0 ? (
            <div className="rounded-lg border border-border bg-bg-subtle/40 p-6 text-center text-sm text-muted">
              暂无版本快照。修改人设后会自动记录历史版本。
            </div>
          ) : (
            <ul className="flex max-h-[55vh] flex-col gap-2 overflow-y-auto pr-1">
              {versions.map((meta) => {
                const isLatest = meta.version === latestVersion;
                const isOpen = diffFor === meta.version;
                const confirming = pendingRollback === meta.version;
                return (
                  <li
                    key={meta.version}
                    className="rounded-lg border border-border bg-surface-elevated/60 p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">v{meta.version}</span>
                      <span className="rounded-full bg-bg-subtle px-2 py-0.5 text-xs text-muted">
                        {REASON_LABELS[meta.reason] ?? meta.reason}
                      </span>
                      {isLatest && (
                        <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">
                          当前
                        </span>
                      )}
                      <span className="text-xs text-muted">
                        {formatTimestamp(meta.created_at)}
                      </span>
                      <div className="ml-auto flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={isLatest || latestVersion === undefined}
                          onClick={() => handleDiff(meta)}
                        >
                          {isOpen ? '收起对比' : '对比'}
                        </Button>
                        {!isLatest &&
                          (confirming ? (
                            <>
                              <Button
                                size="sm"
                                variant="danger"
                                disabled={rollingBack}
                                onClick={() => handleRollback(meta.version)}
                              >
                                {rollingBack ? '回滚中…' : '确认回滚'}
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                disabled={rollingBack}
                                onClick={() => setPendingRollback(null)}
                              >
                                取消
                              </Button>
                            </>
                          ) : (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => setPendingRollback(meta.version)}
                            >
                              回滚
                            </Button>
                          ))}
                      </div>
                    </div>

                    {isOpen && (
                      <div className="mt-3 border-t border-border pt-2 text-xs">
                        {diffLoading ? (
                          <div className="text-muted">对比中…</div>
                        ) : diffError ? (
                          <div className="text-error">对比失败：{diffError}</div>
                        ) : diffs && diffs.length === 0 ? (
                          <div className="text-muted">与当前版本无字段差异。</div>
                        ) : diffs ? (
                          <ul className="flex flex-col gap-2">
                            {diffs.map((d) => (
                              <li key={d.field}>
                                <div className="font-medium text-fg">
                                  {FIELD_LABELS[d.field] ?? d.field}
                                </div>
                                <div className="mt-1 grid grid-cols-2 gap-2">
                                  <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-all rounded bg-bg-subtle/60 p-2 text-muted">
                                    {formatValue(d.before)}
                                  </pre>
                                  <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-all rounded bg-bg-subtle/60 p-2 text-fg">
                                    {formatValue(d.after)}
                                  </pre>
                                </div>
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
