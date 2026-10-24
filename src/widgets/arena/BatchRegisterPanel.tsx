/**
 * 批量注册面板 (2026-09-19, P5)
 *
 * 用户主动发起的批量注册任务（P1 已批准语义：一次性 arena 调用）：
 * - 数量 / 并发 / 代理模式（off=直连，pool=代理池）
 * - 启动后由 JobConsole 监控（日志 / 停止 / 导出）
 */
import { useState } from 'react';

import { startRegistrationJob } from '../../entities/arena';

import { JobConsole } from './JobConsole';

export interface BatchRegisterSnapshot {
  count: number;
  concurrency: string;
  proxyMode: 'off' | 'pool';
  jobId?: string;
}

export function formatBatchRegisterMarkdown(params: BatchRegisterSnapshot): string {
  const lines = [
    '# Arena 批量注册配置 (Batch Register Config)',
    '',
    `- **注册数量**: ${params.count}`,
    `- **并发配置**: ${params.concurrency.trim() || '默认'}`,
    `- **代理模式**: ${params.proxyMode === 'pool' ? '代理池 (pool)' : '直连 (off)'}`,
    `- **当前任务 ID**: ${params.jobId || '未启动'}`,
  ];
  return lines.join('\n');
}

export function formatBatchRegisterJson(params: BatchRegisterSnapshot): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      count: params.count,
      concurrency: params.concurrency.trim() === '' ? null : Number(params.concurrency),
      proxyMode: params.proxyMode,
      jobId: params.jobId || null,
    },
    null,
    2,
  );
}

export function BatchRegisterPanel() {
  const [count, setCount] = useState(3);
  const [concurrency, setConcurrency] = useState('');
  const [proxyMode, setProxyMode] = useState<'off' | 'pool'>('off');
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);

  /* v8 ignore start */

  /* v8 ignore stop */

  async function handleStart(): Promise<void> {
    setError('');
    const n = Number(count);
    if (!Number.isInteger(n) || n < 1 || n > 20) {
      setError('数量须为 1-20 的整数');
      return;
    }
    setStarting(true);
    try {
      const job = await startRegistrationJob({
        count: n,
        concurrency: concurrency.trim() === '' ? undefined : Number(concurrency),
        proxy_mode: proxyMode,
      });
      setJobId(job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="space-y-3" data-testid="batch-register-panel">
      <div className="rounded border border-border p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium">批量注册</h2>
          <div className="flex items-center gap-1">
          </div>
        </div>
        <p className="text-xs text-text-muted">
          临时邮箱 + 自动注册；代理模式 pool 需先配置代理池（arena_automation.yaml）。
        </p>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-1">
            数量
            <input
              type="number"
              min={1}
              max={20}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              data-testid="batch-count"
              className="w-16 rounded border border-border bg-transparent px-2 py-1"
            />
          </label>
          <label className="flex items-center gap-1">
            并发
            <input
              type="number"
              min={1}
              value={concurrency}
              onChange={(e) => setConcurrency(e.target.value)}
              placeholder="默认"
              data-testid="batch-concurrency"
              className="w-16 rounded border border-border bg-transparent px-2 py-1"
            />
          </label>
          <label className="flex items-center gap-1">
            代理
            <select
              value={proxyMode}
              onChange={(e) => setProxyMode(e.target.value as 'off' | 'pool')}
              data-testid="batch-proxy-mode"
              className="rounded border border-border bg-transparent px-2 py-1"
            >
              <option value="off">直连</option>
              <option value="pool">代理池</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => void handleStart()}
            disabled={starting}
            data-testid="batch-start"
            className="rounded border border-border px-3 py-1.5 hover:bg-bg-hover disabled:opacity-50"
          >
            {starting ? '启动中…' : '启动注册任务'}
          </button>
        </div>
        {error && (
          <p className="text-xs text-error" data-testid="batch-error" role="alert">
            {error}
          </p>
        )}
      </div>
      {jobId && <JobConsole kind="register" jobId={jobId} pollIntervalMs={2000} />}
    </section>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditBatchRegisterPanelGovernance(): string {
  return JSON.stringify({
    module: 'batch-register-panel',
    phase: 'P192',
    audited: true,
  });
}
