import { useCallback, useEffect, useState } from 'react';

import {
  specialistApi,
  type SpecialistEvalReport,
  type SpecialistGoldenTask,
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

interface SpecialistEvalDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 当前评测的专家；null 时不请求。 */
  agent: AgentProfile | null;
}

/** 与后端 template_id_from_agent_id 同一规则（模板实例化命名）。 */
const TEMPLATE_INSTANCE_RE = /^specialist-[a-z][a-z0-9-]{1,30}-[0-9a-f]{6}$/;

const TEMPLATE_LABELS: Record<string, string> = {
  writing: '写作',
  research: '研究',
  coding: '编码',
  presentation: '演示',
  office: 'Office',
};

const CHECK_LABELS: Record<string, string> = {
  keywords_all: '关键词（全部）',
  keywords_any: '关键词（任一）',
  forbidden: '禁用词',
  refusal: '未拒答',
  regex: '正则匹配',
  max_chars: '字数上限',
};

function formatTimestamp(ms: number): string {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function formatRate(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

/**
 * 黄金任务集评测对话框（M4-T4，spec §11）。
 *
 * 打开时加载任务目录（任务数 / 覆盖模板）；「运行评测」调用后端
 * POST /specialists/{agent_id}/eval（同步跑完全部任务，可能耗时数分钟），
 * 结果展示总体通过率、按模板聚合与逐任务检查明细。
 */
export function SpecialistEvalDialog({ open, onOpenChange, agent }: SpecialistEvalDialogProps) {
  const [tasks, setTasks] = useState<SpecialistGoldenTask[]>([]);
  const [templateIds, setTemplateIds] = useState<string[]>([]);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [report, setReport] = useState<SpecialistEvalReport | null>(null);

  const agentId = agent?.id ?? null;
  const isTemplateInstance = agentId !== null && TEMPLATE_INSTANCE_RE.test(agentId);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingTasks(true);
    setLoadingError(null);
    setReport(null);
    setRunError(null);
    specialistApi
      .listGoldenTasks()
      .then((result) => {
        if (cancelled) return;
        setTasks(result.tasks);
        setTemplateIds(result.template_ids);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadingError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoadingTasks(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleRun = useCallback(async () => {
    if (!agentId) return;
    setRunning(true);
    setRunError(null);
    try {
      const result = await specialistApi.runEval(agentId);
      setReport(result.report);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, [agentId]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>评测{agent ? ` · ${agent.name}` : ''}</DialogTitle>
          <DialogDescription>
            用固定黄金任务集衡量该专家的输出质量：关键词、禁用词、拒答与格式检查全部为确定性评分。
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 flex flex-col gap-3">
          <div className="rounded-lg border border-border bg-bg-subtle/40 p-3 text-sm">
            {loadingTasks ? (
              <span className="text-muted">加载任务目录…</span>
            ) : loadingError ? (
              <span className="text-error">加载任务目录失败：{loadingError}</span>
            ) : (
              <span className="text-muted">
                共 {tasks.length} 个任务，覆盖{' '}
                {templateIds.map((id) => TEMPLATE_LABELS[id] ?? id).join(' / ') || '—'}
              </span>
            )}
          </div>

          {!isTemplateInstance && (
            <div className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
              仅通过内置模板创建的专家支持评测（专家 id 需形如
              specialist-&lt;模板&gt;-&lt;6位hex&gt;）。请从「从模板创建」开始使用评测。
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button size="sm" onClick={handleRun} disabled={running || !isTemplateInstance}>
              {running ? '评测中…（可能需要数分钟）' : '运行评测'}
            </Button>
            {runError && <span className="text-sm text-error">评测失败：{runError}</span>}
          </div>

          {report && (
            <div className="flex flex-col gap-3">
              <div className="rounded-lg border border-border bg-surface-elevated/60 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    通过 {report.passed}/{report.total_tasks}（{formatRate(report.pass_rate)}）
                  </span>
                  {report.errored > 0 && (
                    <span className="rounded-full bg-error/10 px-2 py-0.5 text-xs text-error">
                      错误 {report.errored}
                    </span>
                  )}
                  <span className="text-xs text-muted">
                    tokens {report.total_tokens} · {formatTimestamp(report.finished_at)}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted">
                  {Object.entries(report.by_template).map(([tpl, bucket]) => (
                    <span key={tpl} className="rounded-full bg-bg-subtle px-2 py-0.5">
                      {TEMPLATE_LABELS[tpl] ?? tpl} {bucket.passed}/{bucket.total}
                    </span>
                  ))}
                </div>
              </div>

              <ul className="flex max-h-[45vh] flex-col gap-2 overflow-y-auto pr-1">
                {report.task_results.map((result) => (
                  <li
                    key={result.task_id}
                    className="rounded-lg border border-border bg-surface-elevated/60 p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span
                        aria-hidden="true"
                        className={result.passed ? 'text-success' : 'text-error'}
                      >
                        {result.passed ? '✓' : '✗'}
                      </span>
                      <span className="font-medium">{result.topic || result.task_id}</span>
                      <span className="rounded-full bg-bg-subtle px-2 py-0.5 text-xs text-muted">
                        {TEMPLATE_LABELS[result.template_id] ?? result.template_id}
                      </span>
                    </div>
                    {result.error ? (
                      <p className="mt-1 text-xs text-error">{result.error}</p>
                    ) : (
                      !result.passed && (
                        <p className="mt-1 text-xs text-muted">
                          未通过：
                          {result.checks
                            .filter((c) => !c.passed)
                            .map((c) => CHECK_LABELS[c.check] ?? c.check)
                            .join('、') || '未知检查项'}
                        </p>
                      )
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
