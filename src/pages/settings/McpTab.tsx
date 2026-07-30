/**
 * Settings 页面 - MCP Tab (M3)
 *
 * Multi-server MCP 管理:状态表(名称/状态徽章/工具数/错误)、启用开关
 * (PATCH)、添加表单(客户端 slug 校验)、删除(内置禁用)、刷新。
 * 数据走 mcpClient → IPC → backend /api/v1/mcp/*。
 */
import { clsx } from 'clsx';
import { useCallback, useEffect, useState } from 'react';

import {
  MCP_NAME_REGEX,
  mcpClient,
  type McpServerConfig,
  type McpServerState,
  type McpStatusReport,
} from '../../shared/api/mcpClient';
import { useI18n } from '../../shared/lib/i18n';
import type { TranslationKey } from '../../shared/lib/i18n/zh';

import { Toggle } from './components';

const STATE_BADGE_CLASSES: Record<McpServerState, string> = {
  ready: 'bg-green-500/15 text-green-500',
  discovering: 'bg-amber-500/15 text-amber-500',
  failed: 'bg-red-500/15 text-red-500',
  disabled: 'bg-faint/15 text-faint',
};

const STATE_LABEL_KEYS: Record<McpServerState, TranslationKey> = {
  ready: 'settings.mcp.state.ready',
  discovering: 'settings.mcp.state.discovering',
  failed: 'settings.mcp.state.failed',
  disabled: 'settings.mcp.state.disabled',
};

interface AddFormState {
  name: string;
  command: string;
  args: string;
  required: boolean;
}

const EMPTY_FORM: AddFormState = { name: '', command: '', args: '', required: false };

export function McpTab() {
  const { t } = useI18n();
  const [report, setReport] = useState<McpStatusReport | null>(null);
  const [servers, setServers] = useState<McpServerConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [form, setForm] = useState<AddFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [status, list] = await Promise.all([mcpClient.status(), mcpClient.listServers()]);
      setReport(status);
      setServers(list);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleToggle = async (name: string, enabled: boolean): Promise<void> => {
    setActionError(null);
    try {
      await mcpClient.updateServer(name, { enabled });
      await refresh();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
      await refresh();
    }
  };

  const handleDelete = async (name: string): Promise<void> => {
    setActionError(null);
    try {
      await mcpClient.deleteServer(name);
      await refresh();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    }
  };

  const validateForm = (): string | null => {
    if (!MCP_NAME_REGEX.test(form.name)) return t('settings.mcp.error.name_invalid');
    if (form.command.trim().length === 0) return t('settings.mcp.error.command_required');
    return null;
  };

  const handleAdd = async (): Promise<void> => {
    const error = validateForm();
    setFormError(error);
    if (error) return;
    setAdding(true);
    setActionError(null);
    try {
      const args = form.args
        .split(/\s+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      await mcpClient.addServer({
        name: form.name,
        command: form.command.trim(),
        args,
        required: form.required,
      });
      setForm(EMPTY_FORM);
      await refresh();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setAdding(false);
    }
  };

  const stateByKey = new Map((report?.servers ?? []).map((s) => [s.name, s]));
  const inputClass =
    'px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text';

  return (
    <div className="space-y-6">
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-text">{t('settings.mcp.title')}</h3>
          <button
            className="px-3 py-1 text-xs border border-border rounded-radius-sm text-muted hover:text-text"
            onClick={() => void refresh()}
            disabled={loading}
            aria-label={t('settings.mcp.refresh')}
          >
            {t('settings.mcp.refresh')}
          </button>
        </div>
        <p className="text-xs text-muted mb-3">{t('settings.mcp.desc')}</p>

        {loadError && (
          <div role="alert" className="text-xs text-red-500 mb-3">
            {loadError}
          </div>
        )}
        {actionError && (
          <div role="alert" className="text-xs text-red-500 mb-3">
            {actionError}
          </div>
        )}

        {servers.length === 0 && !loading ? (
          <div className="text-xs text-muted py-4 text-center">{t('settings.mcp.empty')}</div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted border-b border-border">
                <th className="text-left py-2 font-medium">{t('settings.mcp.col.name')}</th>
                <th className="text-left py-2 font-medium">{t('settings.mcp.col.state')}</th>
                <th className="text-left py-2 font-medium">{t('settings.mcp.col.tools')}</th>
                <th className="text-left py-2 font-medium">{t('settings.mcp.col.error')}</th>
                <th className="text-left py-2 font-medium">{t('settings.mcp.col.enabled')}</th>
                <th className="text-left py-2 font-medium">{t('settings.mcp.col.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {servers.map((srv) => {
                const entry = stateByKey.get(srv.name);
                const state: McpServerState = entry?.state ?? 'discovering';
                return (
                  <tr key={srv.name} className="border-b border-border">
                    <td className="py-2 text-text font-mono">
                      {srv.name}
                      {srv.required && (
                        <span className="ml-1 text-amber-500" title={t('settings.mcp.required')}>
                          *
                        </span>
                      )}
                    </td>
                    <td className="py-2">
                      <span
                        data-testid={`state-badge-${srv.name}`}
                        className={clsx(
                          'px-2 py-0.5 rounded-full text-[11px] font-medium',
                          STATE_BADGE_CLASSES[state],
                        )}
                      >
                        {t(STATE_LABEL_KEYS[state])}
                      </span>
                    </td>
                    <td className="py-2 text-text">{entry?.tool_count ?? 0}</td>
                    <td className="py-2 text-muted max-w-[240px]">
                      <span className="block truncate" title={entry?.last_error ?? ''}>
                        {entry?.last_error ?? ''}
                      </span>
                    </td>
                    <td className="py-2">
                      <Toggle
                        value={srv.enabled}
                        onChange={(v) => void handleToggle(srv.name, v)}
                      />
                    </td>
                    <td className="py-2">
                      <button
                        className={clsx(
                          'px-2 py-0.5 text-xs rounded-radius-sm border',
                          srv.builtin
                            ? 'border-border text-muted opacity-50 cursor-not-allowed'
                            : 'border-red-500/40 text-red-500 hover:bg-red-500/10',
                        )}
                        disabled={srv.builtin}
                        title={srv.builtin ? t('settings.mcp.builtin_hint') : t('common.delete')}
                        onClick={() => void handleDelete(srv.name)}
                      >
                        {t('settings.mcp.delete')}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('settings.mcp.add.title')}</h3>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs text-muted space-y-1">
            <span>{t('settings.mcp.add.name')}</span>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="my-server"
              className={clsx(inputClass, 'w-full')}
            />
          </label>
          <label className="text-xs text-muted space-y-1">
            <span>{t('settings.mcp.add.command')}</span>
            <input
              type="text"
              value={form.command}
              onChange={(e) => setForm({ ...form, command: e.target.value })}
              placeholder="node"
              className={clsx(inputClass, 'w-full')}
            />
          </label>
          <label className="text-xs text-muted space-y-1">
            <span>{t('settings.mcp.add.args')}</span>
            <input
              type="text"
              value={form.args}
              onChange={(e) => setForm({ ...form, args: e.target.value })}
              placeholder="/path/to/server.js --flag"
              className={clsx(inputClass, 'w-full')}
            />
          </label>
          <label className="text-xs text-muted flex items-center gap-2 self-end pb-1.5">
            <input
              type="checkbox"
              checked={form.required}
              onChange={(e) => setForm({ ...form, required: e.target.checked })}
            />
            <span>{t('settings.mcp.add.required')}</span>
          </label>
        </div>
        {formError && (
          <div role="alert" className="text-xs text-red-500 mt-2">
            {formError}
          </div>
        )}
        <button
          className="mt-3 px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover disabled:opacity-50"
          onClick={() => void handleAdd()}
          disabled={adding}
        >
          {t('settings.mcp.add.submit')}
        </button>
      </section>
    </div>
  );
}
