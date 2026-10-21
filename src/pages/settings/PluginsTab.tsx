/**
 * Settings 页面 - 插件 Tab（R82）。
 *
 * 管理后端保存的插件生命周期记录：安装（粘贴 manifest）、启停、配置、
 * 软卸载/恢复、权限确认与事件日志。插件代码的实际加载与托管属于 R83，
 * 本页明确标注这一边界，不把“已登记”冒充为“已运行”。
 */
import { clsx } from 'clsx';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  describePermission,
  extractManifestPermissions,
  parsePluginConfirmationError,
  pluginClient,
  PluginPermissionConfirmationRequiredError,
  type PermissionsConfirmationPayload,
  type PluginEvent,
  type PluginRecord,
  type PluginStatus,
} from '../../shared/api/pluginClient';
import { useI18n } from '../../shared/lib/i18n';

import { Toggle } from './components';

type StatusFilter = '' | PluginStatus;

const STATUS_BADGE_CLASSES: Record<PluginStatus, string> = {
  installed: 'bg-primary/15 text-primary',
  enabled: 'bg-success/15 text-success',
  disabled: 'bg-faint/15 text-faint',
  uninstalled: 'bg-error/15 text-error',
};

const MANIFEST_TEMPLATE = JSON.stringify(
  {
    schema_version: '1.0',
    name: 'example-plugin',
    version: '1.0.0',
    type: 'personal',
    metadata: {
      display_name: 'Example Plugin',
      description: 'Describe what this plugin provides',
      author: '',
    },
    capabilities: [
      {
        type: 'tool',
        name: 'example-tool',
        description: 'Describe this capability',
        entry_point: 'tools.example',
        permissions: ['file:read'],
        config_schema: {},
      },
    ],
    dependencies: [],
    min_sage_version: '0.4.0',
  },
  null,
  2,
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function PluginsTab() {
  const { locale } = useI18n();
  const en = locale === 'en';

  const copy = {
    title: en ? 'Plugins' : '插件',
    refresh: en ? 'Refresh' : '刷新',
    desc: en
      ? 'Install and manage plugin lifecycle records, permissions, configuration, and event logs.'
      : '安装并管理插件生命周期记录、权限、配置与事件日志。',
    boundary: en
      ? 'R82 manages records only. Plugin code loading and hosting will arrive in R83, so an enabled record does not mean plugin code is running yet.'
      : 'R82 只管理生命周期记录；插件代码加载与托管将在 R83 接入。因此“已启用”目前表示记录状态，不代表插件代码已经运行。',
    loading: en ? 'Loading…' : '加载中…',
    empty: en ? 'No plugins in this view.' : '当前筛选下没有插件。',
    filter: en ? 'Status filter' : '状态筛选',
    all: en ? 'All' : '全部',
    details: en ? 'Details' : '详情',
    collapse: en ? 'Collapse' : '收起',
    uninstall: en ? 'Uninstall' : '卸载',
    restore: en ? 'Restore' : '恢复',
    installPath: en ? 'Install path' : '安装路径',
    updated: en ? 'Updated' : '更新于',
    permissions: en ? 'Permissions' : '权限',
    noPermissions: en ? 'No declared permissions' : '未声明权限',
    capabilities: en ? 'Capabilities' : '能力',
    noCapabilities: en ? 'No capability details recorded.' : '没有记录能力详情。',
    config: en ? 'Configuration JSON' : '配置 JSON',
    saveConfig: en ? 'Save config' : '保存配置',
    logs: en ? 'Event log' : '事件日志',
    recentLogs: en ? 'Recent activity' : '最近事件',
    noLogs: en ? 'No events yet.' : '暂无事件。',
    installTitle: en ? 'Install a plugin record' : '安装插件记录',
    manifest: en ? 'Manifest JSON (plugin.json)' : 'Manifest JSON（plugin.json）',
    install: en ? 'Install' : '安装',
    installing: en ? 'Installing…' : '安装中…',
    confirmInstall: en ? 'Confirm permissions and install' : '确认权限并安装',
    requestedPermissions: en ? 'This manifest requests:' : '此 manifest 申请以下权限：',
    confirmPermissions: en
      ? 'I have reviewed and confirm these permissions.'
      : '我已逐项审阅并确认这些权限。',
    confirmationRequired: en
      ? 'The backend requires explicit permission confirmation before saving this plugin.'
      : '后端要求在保存此插件前逐项确认权限。',
    pathRequired: en ? 'Install path is required.' : '请填写安装路径。',
    manifestInvalid: en ? 'Manifest must be a JSON object.' : 'Manifest 必须是 JSON 对象。',
    configInvalid: en ? 'Configuration must be a JSON object.' : '配置必须是 JSON 对象。',
    installedNotice: en ? 'Plugin record installed.' : '插件记录已安装。',
    configSaved: en ? 'Configuration saved.' : '配置已保存。',
    count: en ? 'records' : '条记录',
  };

  const statusLabel: Record<PluginStatus, string> = en
    ? {
        installed: 'Installed',
        enabled: 'Enabled (record)',
        disabled: 'Disabled',
        uninstalled: 'Uninstalled',
      }
    : {
        installed: '已安装',
        enabled: '已启用（记录）',
        disabled: '已停用',
        uninstalled: '已卸载',
      };

  const eventLabel = (event: string): string => {
    const labels: Record<string, string> = en
      ? {
          installed: 'Installed',
          enabled: 'Enabled',
          disabled: 'Disabled',
          uninstalled: 'Uninstalled',
          restored: 'Restored',
          config_updated: 'Config updated',
        }
      : {
          installed: '已安装',
          enabled: '已启用',
          disabled: '已停用',
          uninstalled: '已卸载',
          restored: '已恢复',
          config_updated: '配置已更新',
        };
    return labels[event] ?? event;
  };

  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [recentLogs, setRecentLogs] = useState<PluginEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyName, setBusyName] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('');

  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [pluginLogs, setPluginLogs] = useState<PluginEvent[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [configText, setConfigText] = useState('{}');
  const [configError, setConfigError] = useState<string | null>(null);
  const [configSaving, setConfigSaving] = useState(false);

  const [installPath, setInstallPath] = useState('');
  const [manifestText, setManifestText] = useState(MANIFEST_TEMPLATE);
  const [confirmPermissions, setConfirmPermissions] = useState(false);
  const [confirmation, setConfirmation] = useState<PermissionsConfirmationPayload | null>(null);
  const [installing, setInstalling] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const parsedManifest = useMemo((): {
    value: Record<string, unknown> | null;
    error: string | null;
  } => {
    try {
      const value: unknown = JSON.parse(manifestText);
      if (!isRecord(value)) return { value: null, error: copy.manifestInvalid };
      return { value, error: null };
    } catch (error) {
      return { value: null, error: errorMessage(error) };
    }
  }, [manifestText, copy.manifestInvalid]);

  const pendingPermissions = useMemo(
    () => extractManifestPermissions(parsedManifest.value),
    [parsedManifest.value],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [list, events] = await Promise.all([
        pluginClient.list(statusFilter || undefined),
        pluginClient.logs(undefined, 20),
      ]);
      setPlugins(list);
      setRecentLogs(events);
      setSelectedName((current) =>
        current && list.some((item) => item.name === current) ? current : null,
      );
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const loadPluginLogs = useCallback(async (name: string) => {
    setDetailLoading(true);
    try {
      setPluginLogs(await pluginClient.logs(name, 50));
    } catch (error) {
      setActionError(errorMessage(error));
      setPluginLogs([]);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const replacePlugin = useCallback((record: PluginRecord) => {
    setPlugins((current) => current.map((item) => (item.name === record.name ? record : item)));
  }, []);

  const runAction = async (
    plugin: PluginRecord,
    action: 'enable' | 'disable' | 'restore' | 'uninstall',
  ): Promise<void> => {
    setBusyName(plugin.name);
    setActionError(null);
    setNotice(null);
    try {
      const updated =
        action === 'enable'
          ? await pluginClient.enable(plugin.name)
          : action === 'disable'
            ? await pluginClient.disable(plugin.name)
            : action === 'restore'
              ? await pluginClient.restore(plugin.name)
              : await pluginClient.uninstall(plugin.name);
      replacePlugin(updated);
      await refresh();
      if (selectedName === plugin.name) await loadPluginLogs(plugin.name);
    } catch (error) {
      setActionError(errorMessage(error));
      await refresh();
    } finally {
      setBusyName(null);
    }
  };

  const handleSelect = async (plugin: PluginRecord): Promise<void> => {
    if (selectedName === plugin.name) {
      setSelectedName(null);
      setPluginLogs([]);
      return;
    }
    setSelectedName(plugin.name);
    setConfigText(JSON.stringify(plugin.config ?? {}, null, 2));
    setConfigError(null);
    await loadPluginLogs(plugin.name);
  };

  const handleSaveConfig = async (plugin: PluginRecord): Promise<void> => {
    let config: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(configText);
      if (!isRecord(parsed)) throw new Error(copy.configInvalid);
      config = parsed;
    } catch (error) {
      setConfigError(errorMessage(error));
      return;
    }

    setConfigSaving(true);
    setConfigError(null);
    setActionError(null);
    try {
      const updated = await pluginClient.updateConfig(plugin.name, config);
      replacePlugin(updated);
      setNotice(copy.configSaved);
      await refresh();
      await loadPluginLogs(plugin.name);
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setConfigSaving(false);
    }
  };

  const submitInstall = async (): Promise<void> => {
    setFormError(null);
    setNotice(null);
    if (!installPath.trim()) {
      setFormError(copy.pathRequired);
      return;
    }
    if (parsedManifest.error || !parsedManifest.value) {
      setFormError(parsedManifest.error ?? copy.manifestInvalid);
      return;
    }

    setInstalling(true);
    try {
      const record = await pluginClient.install({
        manifest: parsedManifest.value,
        installPath: installPath.trim(),
        confirmPermissions,
      });
      setConfirmation(null);
      setConfirmPermissions(false);
      setNotice(copy.installedNotice);
      await refresh();
      setSelectedName(record.name);
      setConfigText(JSON.stringify(record.config ?? {}, null, 2));
      await loadPluginLogs(record.name);
    } catch (error) {
      const payload =
        error instanceof PluginPermissionConfirmationRequiredError
          ? error.payload
          : parsePluginConfirmationError(error);
      if (payload) {
        setConfirmation(payload);
        setConfirmPermissions(false);
      } else {
        setFormError(errorMessage(error));
      }
    } finally {
      setInstalling(false);
    }
  };

  const renderPermissions = (permissions: string[]) => {
    if (permissions.length === 0) {
      return <span className="text-xs text-muted">{copy.noPermissions}</span>;
    }
    return (
      <div className="flex flex-wrap gap-1.5">
        {permissions.map((permission) => {
          const label = describePermission(permission, locale);
          return (
            <span
              key={permission}
              title={permission}
              className="inline-flex items-center gap-1 rounded-full bg-warning/15 px-2 py-0.5 text-ui-2xs text-warning"
            >
              <span>{label}</span>
              {label !== permission && <code className="font-mono">{permission}</code>}
            </span>
          );
        })}
      </div>
    );
  };

  const renderLogs = (events: PluginEvent[], testId: string) => (
    <div data-testid={testId} className="space-y-1.5">
      {events.length === 0 ? (
        <p className="text-xs text-muted">{copy.noLogs}</p>
      ) : (
        events.map((event) => (
          <div key={event.id} className="flex flex-wrap items-baseline gap-x-2 text-xs">
            <span className="font-medium text-text">{eventLabel(event.event)}</span>
            <code className="font-mono text-muted">{event.plugin_name}</code>
            <span className="text-muted">{formatTime(event.created_at)}</span>
            {event.detail && <span className="text-muted">{event.detail}</span>}
          </div>
        ))
      )}
    </div>
  );

  const confirmationPermissions = confirmation?.permissions ?? pendingPermissions;

  return (
    <div className="space-y-6" data-settings-anchor="plugins">
      <section>
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-text">{copy.title}</h3>
            <span data-testid="plugin-count" className="text-xs text-muted">
              {plugins.length} {copy.count}
            </span>
          </div>
          <button
            type="button"
            data-testid="plugins-refresh"
            className="rounded-radius-sm border border-border px-3 py-1 text-xs text-muted hover:text-text disabled:opacity-50"
            onClick={() => void refresh()}
            disabled={loading}
          >
            {copy.refresh}
          </button>
        </div>

        <p className="mb-3 text-xs text-muted">{copy.desc}</p>
        <div className="mb-3 rounded-radius-sm border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          {copy.boundary}
        </div>

        {loadError && (
          <div role="alert" className="mb-3 text-xs text-error">
            {loadError}
          </div>
        )}
        {actionError && (
          <div role="alert" className="mb-3 text-xs text-error">
            {actionError}
          </div>
        )}
        {notice && (
          <div role="status" className="mb-3 text-xs text-success">
            {notice}
          </div>
        )}

        <label className="mb-3 flex items-center gap-2 text-xs text-muted">
          <span>{copy.filter}</span>
          <select
            data-testid="plugin-status-filter"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            className="rounded-radius-sm border border-border bg-surface px-2 py-1 text-xs text-text"
          >
            <option value="">{copy.all}</option>
            <option value="installed">{statusLabel.installed}</option>
            <option value="enabled">{statusLabel.enabled}</option>
            <option value="disabled">{statusLabel.disabled}</option>
            <option value="uninstalled">{statusLabel.uninstalled}</option>
          </select>
        </label>

        {loading && plugins.length === 0 ? (
          <div className="py-4 text-center text-xs text-muted">{copy.loading}</div>
        ) : plugins.length === 0 ? (
          <div className="py-4 text-center text-xs text-muted">{copy.empty}</div>
        ) : (
          <div className="space-y-3">
            {plugins.map((plugin) => {
              const selected = selectedName === plugin.name;
              const busy = busyName === plugin.name;
              return (
                <article
                  key={plugin.name}
                  data-testid={`plugin-card-${plugin.name}`}
                  className="rounded-radius-md border border-border bg-surface px-3 py-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="text-sm font-medium text-text">{plugin.display_name}</h4>
                        <span
                          data-testid={`plugin-state-${plugin.name}`}
                          className={clsx(
                            'rounded-full px-2 py-0.5 text-ui-2xs font-medium',
                            STATUS_BADGE_CLASSES[plugin.status],
                          )}
                        >
                          {statusLabel[plugin.status]}
                        </span>
                      </div>
                      <div className="mt-0.5 font-mono text-xs text-muted">
                        {plugin.name} · v{plugin.version}
                      </div>
                      {plugin.description && (
                        <p className="mt-1 text-xs text-muted">{plugin.description}</p>
                      )}
                    </div>
                    <Toggle
                      testId={`plugin-toggle-${plugin.name}`}
                      value={plugin.status === 'enabled'}
                      disabled={busy || plugin.status === 'uninstalled'}
                      onChange={(enabled) => void runAction(plugin, enabled ? 'enable' : 'disable')}
                    />
                  </div>

                  <dl className="mt-3 space-y-1 text-xs">
                    <div className="flex gap-2">
                      <dt className="shrink-0 text-muted">{copy.installPath}</dt>
                      <dd className="min-w-0 break-all font-mono text-text">
                        {plugin.install_path}
                      </dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="shrink-0 text-muted">{copy.updated}</dt>
                      <dd className="text-text">{formatTime(plugin.updated_at)}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="shrink-0 text-muted">{copy.permissions}</dt>
                      <dd>{renderPermissions(plugin.permissions)}</dd>
                    </div>
                  </dl>

                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      data-testid={`plugin-details-${plugin.name}`}
                      className="rounded-radius-sm border border-border px-2 py-1 text-xs text-muted hover:text-text"
                      onClick={() => void handleSelect(plugin)}
                    >
                      {selected ? copy.collapse : copy.details}
                    </button>
                    {plugin.status === 'uninstalled' ? (
                      <button
                        type="button"
                        data-testid={`plugin-restore-${plugin.name}`}
                        className="rounded-radius-sm border border-primary/40 px-2 py-1 text-xs text-primary hover:bg-primary/10 disabled:opacity-50"
                        disabled={busy}
                        onClick={() => void runAction(plugin, 'restore')}
                      >
                        {copy.restore}
                      </button>
                    ) : (
                      <button
                        type="button"
                        data-testid={`plugin-uninstall-${plugin.name}`}
                        className="rounded-radius-sm border border-error/40 px-2 py-1 text-xs text-error hover:bg-error/10 disabled:opacity-50"
                        disabled={busy}
                        onClick={() => void runAction(plugin, 'uninstall')}
                      >
                        {copy.uninstall}
                      </button>
                    )}
                  </div>

                  {selected && (
                    <div
                      data-testid={`plugin-detail-${plugin.name}`}
                      className="mt-4 space-y-4 border-t border-border pt-3"
                    >
                      <div>
                        <h5 className="mb-2 text-xs font-semibold text-text">
                          {copy.capabilities}
                        </h5>
                        {(plugin.manifest.capabilities ?? []).length === 0 ? (
                          <p className="text-xs text-muted">{copy.noCapabilities}</p>
                        ) : (
                          <ul className="space-y-2">
                            {(plugin.manifest.capabilities ?? []).map((capability) => (
                              <li key={capability.name} className="text-xs">
                                <span className="font-mono text-text">{capability.name}</span>
                                <span className="ml-2 text-muted">{capability.type}</span>
                                {capability.description && (
                                  <span className="block text-muted">{capability.description}</span>
                                )}
                                {(capability.permissions ?? []).length > 0 && (
                                  <span className="mt-1 block">
                                    {renderPermissions(capability.permissions ?? [])}
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>

                      <div>
                        <label className="space-y-1 text-xs text-muted">
                          <span>{copy.config}</span>
                          <textarea
                            data-testid={`plugin-config-${plugin.name}`}
                            value={configText}
                            onChange={(event) => setConfigText(event.target.value)}
                            rows={6}
                            spellCheck={false}
                            className="w-full rounded-radius-sm border border-border bg-surface px-2 py-1 font-mono text-xs text-text"
                          />
                        </label>
                        {configError && (
                          <div role="alert" className="mt-1 text-xs text-error">
                            {configError}
                          </div>
                        )}
                        <button
                          type="button"
                          data-testid={`plugin-save-config-${plugin.name}`}
                          className="mt-2 rounded-radius-sm bg-primary px-3 py-1.5 text-xs text-text-inverse hover:bg-primary-hover disabled:opacity-50"
                          disabled={configSaving}
                          onClick={() => void handleSaveConfig(plugin)}
                        >
                          {copy.saveConfig}
                        </button>
                      </div>

                      <div>
                        <h5 className="mb-2 text-xs font-semibold text-text">{copy.logs}</h5>
                        {detailLoading ? (
                          <p className="text-xs text-muted">{copy.loading}</p>
                        ) : (
                          renderLogs(pluginLogs, `plugin-logs-${plugin.name}`)
                        )}
                      </div>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold text-text">{copy.recentLogs}</h3>
        {renderLogs(recentLogs, 'plugin-recent-logs')}
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold text-text">{copy.installTitle}</h3>
        <div className="space-y-3">
          <label className="block space-y-1 text-xs text-muted">
            <span>{copy.installPath}</span>
            <input
              type="text"
              data-testid="plugin-install-path"
              value={installPath}
              onChange={(event) => setInstallPath(event.target.value)}
              placeholder="/path/to/plugin"
              className="w-full rounded-radius-sm border border-border bg-surface px-2 py-1 font-mono text-xs text-text"
            />
          </label>

          <label className="block space-y-1 text-xs text-muted">
            <span>{copy.manifest}</span>
            <textarea
              data-testid="plugin-manifest-json"
              value={manifestText}
              onChange={(event) => {
                setManifestText(event.target.value);
                setConfirmation(null);
                setConfirmPermissions(false);
              }}
              rows={16}
              spellCheck={false}
              className="w-full rounded-radius-sm border border-border bg-surface px-2 py-1 font-mono text-xs text-text"
            />
          </label>

          {parsedManifest.error && (
            <div role="alert" className="text-xs text-error">
              {parsedManifest.error}
            </div>
          )}

          {confirmationPermissions.length > 0 && (
            <div
              data-testid={
                confirmation ? 'plugin-confirmation-required' : 'plugin-permission-preview'
              }
              className="space-y-2 rounded-radius-sm border border-warning/30 bg-warning/10 px-3 py-2"
            >
              <p className="text-xs font-medium text-warning">
                {confirmation ? copy.confirmationRequired : copy.requestedPermissions}
              </p>
              {confirmation && confirmation.by_capability.length > 0 ? (
                <ul className="space-y-2">
                  {confirmation.by_capability.map((group) => (
                    <li key={`${group.capability}-${group.type}`} className="text-xs">
                      <span className="font-mono text-text">{group.capability}</span>
                      <span className="mt-1 block">{renderPermissions(group.permissions)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                renderPermissions(confirmationPermissions)
              )}
              <label className="flex items-center gap-2 text-xs text-text">
                <input
                  type="checkbox"
                  data-testid="plugin-confirm-permissions"
                  checked={confirmPermissions}
                  onChange={(event) => setConfirmPermissions(event.target.checked)}
                />
                <span>{copy.confirmPermissions}</span>
              </label>
            </div>
          )}

          {formError && (
            <div role="alert" className="text-xs text-error">
              {formError}
            </div>
          )}

          <button
            type="button"
            data-testid="plugin-install-submit"
            className="rounded-radius-sm bg-primary px-3 py-1.5 text-xs text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            disabled={installing || (confirmation !== null && !confirmPermissions)}
            onClick={() => void submitInstall()}
          >
            {installing ? copy.installing : confirmation ? copy.confirmInstall : copy.install}
          </button>
        </div>
      </section>
    </div>
  );
}
