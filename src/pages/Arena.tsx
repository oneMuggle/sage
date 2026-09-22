/**
 * Arena 控制台 (2026-09-19, P5)
 *
 * 路由: /arena?tab=accounts|register|draw
 *
 * 三页签：
 * - 账号池：AccountTable + 注册向导（单账号）+ 模型观测（P1-P3 既有能力）
 * - 批量注册：BatchRegisterPanel（批量任务 + JobConsole 监控/导出）
 * - 抽卡：DrawPanel（抽卡任务 + 记录表）+ TokenWindowCard（token 窗口状态）
 *
 * 后端功能由 arena_automation.yaml enabled 开关控制；未启用时账号池
 * 显示启用指引（与旧 /arena-accounts 页一致），任务页签可独立报错。
 */
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  deleteAccount,
  enableAccount,
  isolateAccount,
  listAccounts,
  type ArenaAccount,
} from '../entities/arena';
import { BackendRequestError } from '../shared/api/backendRequest';
import { AccountTable, BatchRegisterPanel, DrawPanel, ObservationFeed, RegisterAssist, TokenWindowCard } from '../widgets/arena';

type TabKey = 'accounts' | 'register' | 'draw';

const TABS: ReadonlyArray<{ key: TabKey; label: string }> = [
  { key: 'accounts', label: '账号池' },
  { key: 'register', label: '批量注册' },
  { key: 'draw', label: '抽卡' },
];

export default function Arena() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const tab: TabKey = tabParam === 'register' || tabParam === 'draw' ? tabParam : 'accounts';

  const [accounts, setAccounts] = useState<ArenaAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setAccounts(await listAccounts());
    } catch (err) {
      if (err instanceof BackendRequestError && err.status === 403) {
        setError('Arena 自动化未启用：在 backend/config/arena_automation.yaml 中设置 enabled: true 后重启后端。');
        setAccounts([]);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function runAction(id: string, action: () => Promise<unknown>, okMessage: string): Promise<void> {
    setBusyId(id);
    setError('');
    try {
      await action();
      setStatus(okMessage);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  const disabled = error.includes('未启用');

  return (
    <div className="p-4 space-y-3 max-w-6xl mx-auto" data-testid="arena-page">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-medium">Arena 控制台</h1>
          <p className="text-xs text-text-muted">
            账号池 · 批量注册 · 抽卡（密码加密存储；任务日志 after_seq 断点续传）
          </p>
        </div>
        <button
          type="button"
          onClick={() => void reload()}
          disabled={loading}
          data-testid="arena-reload"
          className="text-xs rounded border border-border px-3 py-1.5 hover:bg-bg-hover disabled:opacity-50"
        >
          刷新
        </button>
      </header>

      <nav className="flex gap-1 border-b border-border" data-testid="arena-tabs">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setSearchParams(item.key === 'accounts' ? {} : { tab: item.key }, { replace: true })}
            data-testid={`arena-tab-${item.key}`}
            className={`px-3 py-1.5 text-xs border-b-2 -mb-px ${
              tab === item.key
                ? 'border-primary text-primary'
                : 'border-transparent text-text-muted hover:text-text'
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === 'accounts' && (
        <div className="space-y-3" data-testid="arena-tab-accounts-panel">
          {error && (
            <p
              className={`rounded p-2 text-xs ${disabled ? 'bg-bg-muted text-text-muted' : 'bg-error/10 text-error'}`}
              data-testid="arena-error"
              role={disabled ? 'note' : 'alert'}
            >
              {error}
            </p>
          )}
          {status && (
            <p className="rounded bg-success/10 text-success p-2 text-xs" data-testid="arena-status" role="status">
              {status}
            </p>
          )}
          {disabled ? null : (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              <div className="lg:col-span-2">
                <AccountTable
                  accounts={accounts}
                  loading={loading}
                  busyId={busyId}
                  onIsolate={(account) =>
                    void runAction(account.id, () => isolateAccount(account.id), `已隔离 ${account.email}`)
                  }
                  onEnable={(account) =>
                    void runAction(account.id, () => enableAccount(account.id), `已启用 ${account.email}`)
                  }
                  onDelete={(account) => {
                    if (window.confirm(`确认删除账号 ${account.email}？（软删除，密码不可恢复）`)) {
                      void runAction(account.id, () => deleteAccount(account.id), `已删除 ${account.email}`);
                    }
                  }}
                />
              </div>
              <div className="space-y-3">
                <RegisterAssist onCompleted={() => void reload()} onError={setError} onStatus={setStatus} />
                <ObservationFeed onError={setError} onStatus={setStatus} />
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'register' && (
        <div data-testid="arena-tab-register-panel">
          <BatchRegisterPanel />
        </div>
      )}

      {tab === 'draw' && (
        <div className="space-y-3" data-testid="arena-tab-draw-panel">
          <TokenWindowCard />
          <DrawPanel />
        </div>
      )}
    </div>
  );
}
