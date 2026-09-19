/**
 * AccountTable — Arena 账号池列表 (2026-09-19)
 *
 * 纯展示 + 行内动作回调。状态徽标用「色点 + 文字」组合，不只靠颜色。
 */
import type { ArenaAccount } from '../../entities/arena';

interface AccountTableProps {
  accounts: ArenaAccount[];
  loading?: boolean;
  busyId?: string | null;
  onIsolate: (account: ArenaAccount) => void;
  onEnable: (account: ArenaAccount) => void;
  onDelete: (account: ArenaAccount) => void;
}

const STATE_META: Record<ArenaAccount['state'], { label: string; cls: string }> = {
  available: { label: '可用', cls: 'bg-success/15 text-success' },
  reserved: { label: '占用中', cls: 'bg-primary/15 text-primary' },
  degraded: { label: '降级', cls: 'bg-warning/15 text-warning' },
  disabled: { label: '已隔离', cls: 'bg-error/15 text-error' },
  destroyed: { label: '已删除', cls: 'bg-bg-muted text-text-muted' },
};

export function AccountTable({
  accounts,
  loading,
  busyId,
  onIsolate,
  onEnable,
  onDelete,
}: AccountTableProps) {
  if (loading) {
    return (
      <div className="p-3 text-xs text-text-muted" data-testid="account-table-loading" role="status">
        <span aria-hidden="true">⏳</span> 加载中…
      </div>
    );
  }
  if (accounts.length === 0) {
    return (
      <div className="p-3 text-xs text-text-muted" data-testid="account-table-empty" role="status">
        <span aria-hidden="true">📭</span> 账号池为空 —— 通过右侧「注册新账号」添加，或启用
        arena_automation 后由系统入池
      </div>
    );
  }
  return (
    <div className="border border-border rounded overflow-hidden" data-testid="account-table">
      <table className="w-full text-xs">
        <thead className="bg-bg-muted">
          <tr className="text-text-muted">
            <th className="font-normal text-left p-2">邮箱</th>
            <th className="font-normal text-left p-2">状态</th>
            <th className="font-normal text-left p-2">连续失败</th>
            <th className="font-normal text-left p-2">最近使用</th>
            <th className="font-normal text-left p-2">备注</th>
            <th className="font-normal text-right p-2">操作</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => {
            const meta = STATE_META[account.state] ?? STATE_META.destroyed;
            const busy = busyId === account.id;
            return (
              <tr key={account.id} data-testid={`account-row-${account.email}`}>
                <td className="p-2 font-mono">{account.email}</td>
                <td className="p-2">
                  <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 ${meta.cls}`}>
                    {meta.label}
                  </span>
                </td>
                <td className="p-2">{account.failure_count}</td>
                <td className="p-2 text-text-muted">{account.last_used_at ?? '—'}</td>
                <td className="p-2 text-text-muted">{account.notes ?? '—'}</td>
                <td className="p-2 text-right whitespace-nowrap">
                  {account.state === 'disabled' ? (
                    <button
                      type="button"
                      disabled={busy}
                      data-testid={`account-enable-${account.id}`}
                      onClick={() => onEnable(account)}
                      className="text-accent hover:underline disabled:opacity-50"
                    >
                      重新启用
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      data-testid={`account-isolate-${account.id}`}
                      onClick={() => onIsolate(account)}
                      className="text-warning hover:underline disabled:opacity-50"
                    >
                      隔离
                    </button>
                  )}
                  <span className="mx-1 text-border">|</span>
                  <button
                    type="button"
                    disabled={busy}
                    data-testid={`account-delete-${account.id}`}
                    onClick={() => onDelete(account)}
                    className="text-error hover:underline disabled:opacity-50"
                  >
                    删除
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
