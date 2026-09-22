/**
 * token 窗口状态卡 (2026-09-19, P5)
 *
 * 轮询 /token-window/health + /token-window/state：
 * - health: ready / 累计出票数 / 出口 IP / UA / 错误
 * - state: needed / 拒绝计数 / 代理切换请求
 * 后端未启用（403）时显示配置指引而非报错。
 */
import { useEffect, useState } from 'react';

import { tokenWindowHealth, tokenWindowState } from '../../entities/arena';
import { BackendRequestError } from '../../shared/api/backendRequest';

interface TokenWindowCardProps {
  pollIntervalMs?: number;
}

export function TokenWindowCard({ pollIntervalMs = 5000 }: TokenWindowCardProps) {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof tokenWindowHealth>> | null>(null);
  const [state, setState] = useState<Awaited<ReturnType<typeof tokenWindowState>> | null>(null);
  const [error, setError] = useState('');
  const [disabled, setDisabled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const [h, s] = await Promise.all([tokenWindowHealth(), tokenWindowState()]);
        if (cancelled) return;
        setHealth(h);
        setState(s);
        setError('');
        setDisabled(false);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof BackendRequestError && err.status === 403) {
          setDisabled(true);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
      if (!cancelled) timer = setTimeout(() => void tick(), pollIntervalMs);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [pollIntervalMs]);

  return (
    <section className="rounded border border-border p-3 space-y-1" data-testid="token-window-card">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">token 窗口</h2>
        {health && (
          <span
            className={`text-xs rounded px-2 py-0.5 ${health.ready ? 'bg-success/10 text-success' : 'bg-bg-muted text-text-muted'}`}
            data-testid="tw-ready"
          >
            {health.ready ? '就绪' : '待票'}
          </span>
        )}
      </div>
      {disabled ? (
        <p className="text-xs text-text-muted" data-testid="tw-disabled">
          token 窗口未启用：在 backend/config/arena_automation.yaml 设置 token_window.enabled:
          true 后重启后端。
        </p>
      ) : (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
          <dt className="text-text-muted">累计出票</dt>
          <dd data-testid="tw-count">{health ? String(health.count) : '—'}</dd>
          <dt className="text-text-muted">出口 IP</dt>
          <dd data-testid="tw-exit-ip">{health?.exit_ip || '—'}</dd>
          <dt className="text-text-muted">UA</dt>
          <dd className="truncate" title={health?.ua ?? ''}>
            {health?.ua || '—'}
          </dd>
          {health?.error && (
            <>
              <dt className="text-text-muted">错误</dt>
              <dd className="text-error" data-testid="tw-error">
                {health.error}
              </dd>
            </>
          )}
          {state && (
            <>
              <dt className="text-text-muted">需要出票</dt>
              <dd data-testid="tw-needed">{state.needed ? '是' : '否'}</dd>
              <dt className="text-text-muted">拒绝计数</dt>
              <dd data-testid="tw-rejects">{String(state.reject_count)}</dd>
              {state.want_proxy && (
                <>
                  <dt className="text-text-muted">请求切换代理</dt>
                  <dd className="text-amber-500" data-testid="tw-want-proxy">
                    {state.proxy_url || '(系统代理)'}
                  </dd>
                </>
              )}
            </>
          )}
        </dl>
      )}
      {error && (
        <p className="text-xs text-error" data-testid="tw-poll-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
