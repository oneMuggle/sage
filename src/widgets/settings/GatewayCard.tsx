// src/widgets/settings/GatewayCard.tsx
// Round 20: 「消息网关」设置卡 —— token/白名单/启用开关 + 状态与绑定列表。

import { RefreshCw, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  gatewayApi,
  type TelegramGatewayBind,
  type TelegramGatewayConfigView,
  type TelegramGatewayStatus,
} from '../../shared/api/gatewayApi';

export function GatewayCard(): JSX.Element | null {
  const [config, setConfig] = useState<TelegramGatewayConfigView | null>(null);
  const [status, setStatus] = useState<TelegramGatewayStatus | null>(null);
  const [binds, setBinds] = useState<TelegramGatewayBind[]>([]);
  const [token, setToken] = useState('');
  const [chatIds, setChatIds] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string>('');
  const [loadError, setLoadError] = useState<string>('');

  const reload = useCallback(async () => {
    setLoadError('');
    try {
      const [cfg, st, bd] = await Promise.all([
        gatewayApi.getConfig(),
        gatewayApi.status(),
        gatewayApi.listBinds().catch(() => ({ binds: [] })),
      ]);
      setConfig(cfg);
      setStatus(st);
      setBinds(bd.binds);
      setToken(cfg.bot_token_masked);
      setChatIds(cfg.allowed_chat_ids.join(', '));
      setEnabled(cfg.enabled);
    } catch (exc) {
      setLoadError(String(exc));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const handleSave = async () => {
    setSaving(true);
    setNotice('');
    try {
      const tokenChanged = !token.startsWith('****');
      const result = await gatewayApi.updateConfig({
        // 打码值原样传回 = 未修改（后端保留已存 token）；写新值即更新
        bot_token: tokenChanged ? token : '',
        allowed_chat_ids: chatIds
          .split(',')
          .map((c) => c.trim())
          .filter(Boolean),
        enabled,
      });
      setNotice(
        result.restart_required
          ? '已保存。重启 Sage 后端后网关按新配置启动。'
          : '已保存。'
      );
      await reload();
    } catch (exc) {
      setNotice(`保存失败: ${String(exc)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleUnbind = async (chatId: string) => {
    setNotice('');
    try {
      await gatewayApi.unbind(chatId);
      setBinds((prev) => prev.filter((b) => b.chat_id !== chatId));
    } catch (exc) {
      setNotice(`解绑失败: ${String(exc)}`);
    }
  };

  if (loadError && !config) {
    return null; // 后端不可达时静默隐藏（与其他设置卡一致）
  }

  return (
    <div
      data-testid="gateway-card"
      className="border border-border rounded-radius-md p-4 mb-4 bg-surface"
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold">消息网关（Telegram）</h3>
        <button
          type="button"
          className="p-1 rounded hover:bg-bg-hover text-text-secondary"
          title="刷新"
          onClick={() => void reload()}
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      <p className="text-xs text-muted mb-2">
        在 Telegram 上远程与 Sage 对话、远程审批危险操作。
        {status
          ? ` 运行中: ${status.running ? '是' : '否'}，绑定 ${status.bound_chats} 个会话。`
          : ''}
      </p>

      <div className="space-y-2 mb-2">
        <label className="block text-xs">
          <span className="text-text-secondary">
            Bot Token（读回为打码值；保持打码值 = 不修改）
          </span>
          <input
            type="text"
            className="mt-1 w-full text-xs border border-border rounded-radius-sm px-2 py-1 bg-surface text-text font-mono"
            value={token}
            placeholder="123456:ABC-DEF..."
            onChange={(e) => setToken(e.target.value)}
          />
        </label>
        <label className="block text-xs">
          <span className="text-text-secondary">允许的 Chat ID（逗号分隔白名单）</span>
          <input
            type="text"
            className="mt-1 w-full text-xs border border-border rounded-radius-sm px-2 py-1 bg-surface text-text font-mono"
            value={chatIds}
            placeholder="123456789, 987654321"
            onChange={(e) => setChatIds(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          启用网关
        </label>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          className="px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
          disabled={saving}
          onClick={() => void handleSave()}
        >
          {saving ? '保存中…' : '保存'}
        </button>
        {notice && <span className="text-xs text-muted">{notice}</span>}
      </div>

      {binds.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold mb-1">已绑定会话</p>
          <div className="space-y-1">
            {binds.map((b) => (
              <div
                key={b.chat_id}
                className="flex items-center justify-between border border-border rounded-radius-sm p-2"
              >
                <span className="text-xs font-mono">
                  chat {b.chat_id} → session {b.session_id.slice(0, 8)}…
                </span>
                <button
                  type="button"
                  className="p-1 rounded hover:bg-bg-hover text-text-secondary hover:text-red-500"
                  title="解绑"
                  onClick={() => void handleUnbind(b.chat_id)}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
