/**
 * 抽卡面板 (2026-09-19, P5)
 *
 * - 发起抽卡任务：范围（全部 / 勾选账号）· 轮数 · 保留 pattern ·
 *   未命中动作（归档=默认 / 保留 / 删除）· 命中改名 · 偏好推理模型
 * - JobConsole 监控（日志 / 停止；结束后刷新抽卡记录表）
 * - 抽卡记录：GET /draws 最近 N 条（模型 / run_id / 保留 / reasoning）
 */
import { useCallback, useEffect, useState } from 'react';

import { listAccounts, listDraws, startDrawJob, type ArenaAccount, type ArenaDrawRow } from '../../entities/arena';

import { JobConsole } from './JobConsole';

const MISS_ACTIONS = [
  { value: 'archive', label: '归档未命中（默认）' },
  { value: 'keep', label: '保留会话' },
  { value: 'delete', label: '删除会话' },
] as const;

export function DrawPanel() {
  const [accounts, setAccounts] = useState<ArenaAccount[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allAccounts, setAllAccounts] = useState(true);
  const [rounds, setRounds] = useState(1);
  const [keepPattern, setKeepPattern] = useState('');
  const [missAction, setMissAction] = useState<'archive' | 'keep' | 'delete'>('archive');
  const [renameHit, setRenameHit] = useState(false);
  const [wantReasoning, setWantReasoning] = useState(true);
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [draws, setDraws] = useState<ArenaDrawRow[]>([]);
  const [drawsLoading, setDrawsLoading] = useState(false);

  const refreshDraws = useCallback(async () => {
    setDrawsLoading(true);
    try {
      setDraws(await listDraws(20));
    } catch {
      // 抽卡记录加载失败不打断面板（任务监控仍可用）
    } finally {
      setDrawsLoading(false);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        setAccounts(await listAccounts());
      } catch {
        // 账号列表失败时仍允许「全部账号」模式启动
      }
    })();
    void refreshDraws();
  }, [refreshDraws]);

  async function handleStart(): Promise<void> {
    setError('');
    if (!allAccounts && selected.size === 0) {
      setError('请至少勾选一个账号，或切换为全部账号');
      return;
    }
    const n = Number(rounds);
    if (!Number.isInteger(n) || n < 1 || n > 50) {
      setError('轮数须为 1-50 的整数');
      return;
    }
    setStarting(true);
    try {
      const job = await startDrawJob({
        all_accounts: allAccounts,
        account_ids: allAccounts ? undefined : [...selected],
        rounds_per_account: n,
        keep_pattern: keepPattern.trim(),
        miss_action: missAction,
        rename_hit: renameHit,
        want_reasoning: wantReasoning,
      });
      setJobId(job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }

  function toggle(id: string): void {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section className="space-y-3" data-testid="draw-panel">
      <div className="rounded border border-border p-3 space-y-2">
        <h2 className="text-sm font-medium">抽卡</h2>
        <p className="text-xs text-text-muted">
          每轮 = 新会话 + 模型判定；未命中按所选动作处理。命中判定 = 模型名含 pattern（空
          pattern 视为未命中）。
        </p>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-1">
            轮数/账号
            <input
              type="number"
              min={1}
              max={50}
              value={rounds}
              onChange={(e) => setRounds(Number(e.target.value))}
              data-testid="draw-rounds"
              className="w-16 rounded border border-border bg-transparent px-2 py-1"
            />
          </label>
          <label className="flex items-center gap-1">
            保留 pattern
            <input
              type="text"
              value={keepPattern}
              onChange={(e) => setKeepPattern(e.target.value)}
              placeholder="如 astra"
              data-testid="draw-keep-pattern"
              className="w-28 rounded border border-border bg-transparent px-2 py-1"
            />
          </label>
          <label className="flex items-center gap-1">
            未命中
            <select
              value={missAction}
              onChange={(e) => setMissAction(e.target.value as 'archive' | 'keep' | 'delete')}
              data-testid="draw-miss-action"
              className="rounded border border-border bg-transparent px-2 py-1"
            >
              {MISS_ACTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1" data-testid="draw-rename-hit">
            <input type="checkbox" checked={renameHit} onChange={(e) => setRenameHit(e.target.checked)} />
            命中改名
          </label>
          <label className="flex items-center gap-1" data-testid="draw-want-reasoning">
            <input
              type="checkbox"
              checked={wantReasoning}
              onChange={(e) => setWantReasoning(e.target.checked)}
            />
            偏好推理模型
          </label>
        </div>
        <div className="space-y-1 text-xs">
          <label className="flex items-center gap-1" data-testid="draw-all-accounts">
            <input
              type="checkbox"
              checked={allAccounts}
              onChange={(e) => setAllAccounts(e.target.checked)}
            />
            全部可用账号
          </label>
          {!allAccounts && (
            <div className="max-h-32 overflow-y-auto rounded border border-border p-2 space-y-1" data-testid="draw-account-picker">
              {accounts.length === 0 ? (
                <span className="text-text-muted">（账号池为空或加载失败）</span>
              ) : (
                accounts.map((account) => (
                  <label key={account.id} className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={selected.has(account.id)}
                      onChange={() => toggle(account.id)}
                      data-testid={`draw-account-${account.id}`}
                    />
                    {account.email}
                  </label>
                ))
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => void handleStart()}
          disabled={starting}
          data-testid="draw-start"
          className="rounded border border-border px-3 py-1.5 hover:bg-bg-hover disabled:opacity-50"
        >
          {starting ? '启动中…' : '启动抽卡任务'}
        </button>
        {error && (
          <p className="text-xs text-error" data-testid="draw-error" role="alert">
            {error}
          </p>
        )}
      </div>

      {jobId && (
        <JobConsole kind="draw" jobId={jobId} pollIntervalMs={2000} onFinished={() => void refreshDraws()} />
      )}

      <div className="rounded border border-border p-3 space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium">抽卡记录（最近 20 条）</h2>
          <button
            type="button"
            onClick={() => void refreshDraws()}
            disabled={drawsLoading}
            data-testid="draws-refresh"
            className="text-xs rounded border border-border px-2 py-1 hover:bg-bg-hover disabled:opacity-50"
          >
            刷新
          </button>
        </div>
        {draws.length === 0 ? (
          <p className="text-xs text-text-muted" data-testid="draws-empty">
            暂无记录
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="draws-table">
              <thead className="text-text-muted">
                <tr>
                  <th className="text-left py-1">时间</th>
                  <th className="text-left py-1">账号</th>
                  <th className="text-left py-1">模型</th>
                  <th className="text-left py-1">保留</th>
                  <th className="text-left py-1">reasoning</th>
                  <th className="text-left py-1">run_id</th>
                </tr>
              </thead>
              <tbody>
                {draws.map((row, index) => (
                  <tr key={`${row.run_id}-${index}`} className="border-t border-border" data-testid={`draws-row-${index}`}>
                    <td className="py-1 pr-2">{(row.created_at ?? '').replace('T', ' ').slice(0, 19)}</td>
                    <td className="py-1 pr-2">{row.email}</td>
                    <td className="py-1 pr-2">{row.model || row.internal || '—'}</td>
                    <td className="py-1 pr-2">{row.kept ? '✓' : ''}</td>
                    <td className="py-1 pr-2">{String(row.reasoning ?? '') || '—'}</td>
                    <td className="py-1 pr-2 font-mono">{row.run_id ? row.run_id.slice(0, 12) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
