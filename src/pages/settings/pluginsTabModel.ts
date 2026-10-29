// src/pages/settings/pluginsTabModel.ts
//
// R116: 自 PluginsTab.tsx 原样抽离的纯数据与纯函数（状态筛选
// 类型、徽章类名、manifest 模板、双语文案与状态/事件标签）。
// 行为逐字不变；抽离只为释放顶格文件的行数预算（819/820），
// 供后续插件面维护。
import type { PluginStatus } from '../../shared/api/pluginClient';

export type StatusFilter = '' | PluginStatus;

export const STATUS_BADGE_CLASSES: Record<PluginStatus, string> = {
  installed: 'bg-primary/15 text-primary',
  enabled: 'bg-success/15 text-success',
  disabled: 'bg-faint/15 text-faint',
  uninstalled: 'bg-error/15 text-error',
};

export const MANIFEST_TEMPLATE = JSON.stringify(
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
        entry_point: 'tools.example_tool:run',
        permissions: ['file:read'],
        input_schema: {
          type: 'object',
          properties: {},
          additionalProperties: false,
        },
      },
    ],
    dependencies: [],
    min_sage_version: '0.4.0',
  },
  null,
  2,
);

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function getPluginsTabCopy(en: boolean) {
  return {
    title: en ? 'Plugins' : '插件',
    refresh: en ? 'Refresh' : '刷新',
    desc: en
      ? 'Install and manage plugin lifecycle records, out-of-process runtimes, permissions, configuration, and event logs.'
      : '安装并管理插件生命周期记录、进程外运行进程、权限、配置与事件日志。',
    boundary: en
      ? 'Enabling a record never starts code automatically. “Start runtime” launches the plugin as the current OS user in a separate Python process; this contains crashes but is not a security sandbox. Saving configuration stops a running worker.'
      : '启用记录不会自动运行代码。“启动运行”会以当前 OS 用户在独立 Python 子进程中加载插件；进程隔离可隔离崩溃，但不是安全沙箱。保存配置会先停止正在运行的 worker。',
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
}

export function getPluginStatusLabels(en: boolean): Record<PluginStatus, string> {
  return en
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
}

export function getPluginEventLabel(en: boolean, event: string): string {
  const labels: Record<string, string> = en
    ? {
        installed: 'Installed',
        enabled: 'Enabled',
        disabled: 'Disabled',
        uninstalled: 'Uninstalled',
        restored: 'Restored',
        config_updated: 'Config updated',
        runtime_started: 'Runtime started',
        runtime_stopped: 'Runtime stopped',
        runtime_restarted: 'Runtime restarted',
        runtime_failed: 'Runtime failed',
        runtime_invoked: 'Tool invoked',
        runtime_invoke_failed: 'Tool invoke failed',
      }
    : {
        installed: '已安装',
        enabled: '已启用',
        disabled: '已停用',
        uninstalled: '已卸载',
        restored: '已恢复',
        config_updated: '配置已更新',
        runtime_started: '运行进程已启动',
        runtime_stopped: '运行进程已停止',
        runtime_restarted: '运行进程已重启',
        runtime_failed: '运行进程失败',
        runtime_invoked: '工具已调用',
        runtime_invoke_failed: '工具调用失败',
      };
  return labels[event] ?? event;
}
