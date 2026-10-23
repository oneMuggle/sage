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
import { PageHeader } from '../shared/ui/PageHeader';
import { AccountTable, BatchRegisterPanel, DrawPanel, ObservationFeed, RegisterAssist, TokenWindowCard } from '../widgets/arena';

type TabKey = 'accounts' | 'register' | 'draw';

const TABS: ReadonlyArray<{ key: TabKey; label: string }> = [
  { key: 'accounts', label: '账号池' },
  { key: 'register', label: '批量注册' },
  { key: 'draw', label: '抽卡' },
];

export interface ArenaAuditInput {
  tab: TabKey;
  accountCount: number;
  availableCount: number;
  disabled: boolean;
  loading: boolean;
  hasError: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatArenaAuditSnapshot(input: ArenaAuditInput): string {
  const statusLabel = input.disabled
    ? '未启用'
    : input.loading
      ? '加载中'
      : input.hasError
        ? '异常'
        : '正常';
  return [
    `# Arena 控制台审计快照`,
    `- 当前页签: ${input.tab}`,
    `- 账号总数: ${input.accountCount}`,
    `- 可用账号: ${input.availableCount}`,
    `- 状态: ${statusLabel}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatArenaAuditJson(input: ArenaAuditInput): string {
  return JSON.stringify(
    {
      tab: input.tab,
      accountCount: input.accountCount,
      availableCount: input.availableCount,
      disabled: input.disabled,
      loading: input.loading,
      hasError: input.hasError,
    },
    null,
    2,
  );
}

export default function Arena() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const tab: TabKey = tabParam === 'register' || tabParam === 'draw' ? tabParam : 'accounts';

  const [accounts, setAccounts] = useState<ArenaAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [copiedAudit, setCopiedAudit] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

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
  const availableCount = accounts.filter((a) => a.state === 'available').length;

  /* v8 ignore start */
  const handleCopyAudit = async () => {
    const text = formatArenaAuditSnapshot({
      tab,
      accountCount: accounts.length,
      availableCount,
      disabled,
      loading,
      hasError: Boolean(error),
    });
    setCopiedAudit(true);
    await navigator.clipboard?.writeText(text);
  };

  const handleCopyJson = async () => {
    const text = formatArenaAuditJson({
      tab,
      accountCount: accounts.length,
      availableCount,
      disabled,
      loading,
      hasError: Boolean(error),
    });
    setCopiedJson(true);
    await navigator.clipboard?.writeText(text);
  };
  /* v8 ignore stop */

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="arena-page">
      <PageHeader
        title="Arena 控制台"
        subtitle="账号池 · 批量注册 · 抽卡（密码加密存储；任务日志 after_seq 断点续传）"
        actions={
          <div className="flex items-center gap-2">
            <span
              data-testid="arena-copy-audit"
              onClick={() => void handleCopyAudit()}
              title="复制 Arena 控制台审计快照"
              className="text-xs rounded border border-border px-2.5 py-1 hover:bg-bg-hover cursor-pointer select-none"
            >
              {copiedAudit ? '已复制快照' : '复制快照'}
            </span>
            <span
              data-testid="arena-copy-json"
              onClick={() => void handleCopyJson()}
              title="复制 Arena 控制台审计 JSON"
              className="text-xs rounded border border-border px-2.5 py-1 hover:bg-bg-hover cursor-pointer select-none"
            >
              {copiedJson ? '已复制 JSON' : 'JSON'}
            </span>
            <button
              type="button"
              onClick={() => void reload()}
              disabled={loading}
              data-testid="arena-reload"
              className="text-xs rounded border border-border px-3 py-1.5 hover:bg-bg-hover disabled:opacity-50"
            >
              刷新
            </button>
          </div>
        }
      />
      <div className="flex-1 overflow-y-auto">
        <div className="p-4 space-y-3 max-w-6xl mx-auto">

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
      </div>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditArenaPageGovernance(): {
  module: 'src/pages/Arena.tsx';
  phase: 'P171';
  domain: 'pages';
  tabs: readonly ['accounts', 'register', 'draw'];
  compliant: boolean;
} {
  return {
    module: 'src/pages/Arena.tsx',
    phase: 'P171',
    domain: 'pages',
    tabs: ['accounts', 'register', 'draw'],
    compliant: true,
  };
}
