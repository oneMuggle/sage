/**
 * ArenaAccounts 页面 (2026-09-19)
 *
 * 路由: /arena-accounts
 *
 * 布局:
 * - 顶部工具栏: 刷新 + 错误/状态提示
 * - 左（主列）: AccountTable 账号池列表（隔离/启用/删除行内动作）
 * - 右（侧列）: RegisterAssist 注册向导 + ObservationFeed 模型观测
 *
 * 后端功能由 arena_automation.yaml enabled 开关控制；未启用时所有请求 403，
 * 页面显示启用指引而不是报错堆栈。
 */
import { useCallback, useEffect, useState } from 'react';

import {
  deleteAccount,
  enableAccount,
  isolateAccount,
  listAccounts,
  type ArenaAccount,
} from '../entities/arena';
import { BackendRequestError } from '../shared/api/backendRequest';
import { PageHeader } from '../shared/ui/PageHeader';
import { AccountTable, ObservationFeed, RegisterAssist } from '../widgets/arena';

export default function ArenaAccounts() {
  const [accounts, setAccounts] = useState<ArenaAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const list = await listAccounts();
      setAccounts(list);
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
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="arena-accounts-page">
      <PageHeader
        title="Arena 账号"
        subtitle="账号池管理（密码加密存储）· 单账号注册辅助 · 被动模型观测"
        actions={
          <button
            type="button"
            onClick={() => void reload()}
            disabled={loading}
            data-testid="arena-reload"
            className="text-xs rounded border border-border px-3 py-1.5 hover:bg-bg-hover disabled:opacity-50"
          >
            刷新
          </button>
        }
      />
      <div className="flex-1 overflow-y-auto">
        <div className="p-4 space-y-3 max-w-6xl mx-auto">

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
                // P1-8: 两步确认已下沉到 AccountTable（armed 态展示「确认删除?」），
                // 页面层不再弹 window.confirm。
                void runAction(account.id, () => deleteAccount(account.id), `已删除 ${account.email}`);
              }}
            />
          </div>
          <div className="space-y-3">
            <RegisterAssist
              onCompleted={() => void reload()}
              onError={setError}
              onStatus={setStatus}
            />
            <ObservationFeed onError={setError} onStatus={setStatus} />
          </div>
        </div>
      )}
        </div>
      </div>
    </div>
  );
}
