/**
 * 插件生命周期与进程外 runtime API 客户端（R82/R83）。
 *
 * 经 Electron ``backendRequest`` 中继调用 ``/api/v1/plugins/*``。
 * 生命周期记录与 runtime 状态是两套语义：enabled 不代表代码正在运行。
 */
import { backendRequest } from './backendRequest';

const BASE = '/api/v1/plugins';

export type PluginStatus = 'installed' | 'enabled' | 'disabled' | 'uninstalled';

export type PluginRuntimeState =
  | 'pending'
  | 'loading'
  | 'active'
  | 'failed'
  | 'unloading'
  | 'disposed';

export interface PluginRuntimeLimits {
  startup_timeout_seconds: number;
  request_timeout_seconds: number;
  shutdown_timeout_seconds: number;
  max_message_bytes: number;
  memory_bytes: number;
  cpu_seconds: number;
  memory_limit_enforced: boolean;
  cpu_limit_enforced: boolean;
}

export interface PluginRuntimeStatus {
  plugin_name: string;
  state: PluginRuntimeState;
  running: boolean;
  pid: number | null;
  started_at: number | null;
  stopped_at: number | null;
  exit_code: number | null;
  restart_count: number;
  capabilities: string[];
  last_error: string | null;
  stderr_tail: string;
  limits: PluginRuntimeLimits;
}

export interface PluginCapability {
  type: string;
  name: string;
  description?: string;
  version?: string;
  entry_point?: string | null;
  permissions?: string[];
  input_schema?: Record<string, unknown> | null;
  config_schema?: Record<string, unknown> | null;
}

export interface PluginManifestData {
  schema_version?: string;
  name?: string;
  version?: string;
  type?: string;
  metadata?: {
    display_name?: string;
    description?: string;
    author?: string;
    homepage?: string | null;
    repository?: string | null;
    license?: string;
    categories?: string[];
    tags?: string[];
    [key: string]: unknown;
  };
  capabilities?: PluginCapability[];
  [key: string]: unknown;
}

export interface PluginPermissionGroup {
  capability: string;
  type: string;
  description: string;
  entry_point: string | null;
  permissions: string[];
}

export interface PluginRecord {
  name: string;
  version: string;
  status: PluginStatus;
  install_path: string;
  config: Record<string, unknown>;
  manifest: PluginManifestData;
  display_name: string;
  description: string;
  permissions: string[];
  by_capability: PluginPermissionGroup[];
  runtime: PluginRuntimeStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  installed_at: string;
}

export interface PluginEvent {
  id: number;
  plugin_name: string;
  event: string;
  detail: string;
  created_at: string;
}

export interface PluginPermissions {
  plugin: string;
  permissions: string[];
  by_capability: PluginPermissionGroup[];
}

export interface PluginRuntimeActionResponse {
  plugin: PluginRecord;
  runtime: PluginRuntimeStatus;
}

export interface PluginInvokeResponse {
  plugin_name: string;
  capability: string;
  result: unknown;
  runtime: PluginRuntimeStatus;
}

export interface PublishedPluginTool {
  plugin_name: string;
  capability_name: string;
  tool_name: string;
  description: string;
  risk: string;
  permissions: string[];
}

export interface InstallPluginInput {
  manifest: Record<string, unknown>;
  installPath: string;
  confirmPermissions?: boolean;
}

export interface PermissionsConfirmationPayload {
  ok: false;
  error: 'permissions_confirmation_required';
  detail: string;
  plugin: string;
  permissions: string[];
  by_capability: PluginPermissionGroup[];
}

export class PluginPermissionConfirmationRequiredError extends Error {
  readonly status = 409;

  constructor(readonly payload: PermissionsConfirmationPayload) {
    super(payload.detail || '插件声明了权限，安装前必须显式确认');
    this.name = 'PluginPermissionConfirmationRequiredError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeGroup(value: unknown): PluginPermissionGroup | null {
  if (!isRecord(value)) return null;
  const permissions = Array.isArray(value.permissions)
    ? value.permissions.filter((item): item is string => typeof item === 'string')
    : [];
  return {
    capability: typeof value.capability === 'string' ? value.capability : '',
    type: typeof value.type === 'string' ? value.type : '',
    description: typeof value.description === 'string' ? value.description : '',
    entry_point: typeof value.entry_point === 'string' ? value.entry_point : null,
    permissions,
  };
}

/**
 * Electron relay 对非 2xx 响应抛普通 Error，message 含原始 JSON body。
 * 这里把后端 409 载荷还原为类型化错误，供 UI 展示逐项权限确认。
 */
export function parsePluginConfirmationError(
  error: unknown,
): PermissionsConfirmationPayload | null {
  const raw = error instanceof Error ? error.message : String(error);
  const start = raw.indexOf('{');
  if (start < 0) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw.slice(start));
  } catch {
    return null;
  }
  if (!isRecord(parsed) || parsed.error !== 'permissions_confirmation_required') return null;

  const groups = Array.isArray(parsed.by_capability)
    ? parsed.by_capability
        .map(normalizeGroup)
        .filter((group): group is PluginPermissionGroup => group !== null)
    : [];

  return {
    ok: false,
    error: 'permissions_confirmation_required',
    detail: typeof parsed.detail === 'string' ? parsed.detail : '',
    plugin: typeof parsed.plugin === 'string' ? parsed.plugin : '',
    permissions: Array.isArray(parsed.permissions)
      ? parsed.permissions.filter((item): item is string => typeof item === 'string')
      : [],
    by_capability: groups,
  };
}

const PERMISSION_DESCRIPTIONS_ZH: Record<string, string> = {
  'file:read': '读取文件',
  'file:write': '写入或修改文件',
  'file:delete': '删除文件',
  'network:read': '读取网络资源',
  'network:write': '发送网络请求',
  'network:fetch': '抓取网络资源',
  'shell:execute': '执行 shell 命令',
  'process:execute': '启动外部进程',
  'database:read': '读取数据库',
  'database:write': '写入数据库',
  'memory:read': '读取记忆',
  'memory:write': '写入记忆',
  'settings:read': '读取设置',
  'settings:write': '修改设置',
  'llm:call': '调用语言模型',
};

const PERMISSION_DESCRIPTIONS_EN: Record<string, string> = {
  'file:read': 'Read files',
  'file:write': 'Write or modify files',
  'file:delete': 'Delete files',
  'network:read': 'Read network resources',
  'network:write': 'Send network requests',
  'network:fetch': 'Fetch network resources',
  'shell:execute': 'Run shell commands',
  'process:execute': 'Start external processes',
  'database:read': 'Read the database',
  'database:write': 'Write to the database',
  'memory:read': 'Read memories',
  'memory:write': 'Write memories',
  'settings:read': 'Read settings',
  'settings:write': 'Modify settings',
  'llm:call': 'Call language models',
};

/** 将权限串翻成人话；未知权限回退原文，避免把未知能力说小。 */
export function describePermission(permission: string, locale = 'zh'): string {
  const table = locale === 'en' ? PERMISSION_DESCRIPTIONS_EN : PERMISSION_DESCRIPTIONS_ZH;
  return table[permission] ?? permission;
}

/** 从待安装 manifest 中提取权限（去重、保序），供提交前预检展示。 */
export function extractManifestPermissions(manifest: unknown): string[] {
  if (!isRecord(manifest) || !Array.isArray(manifest.capabilities)) return [];
  const seen = new Set<string>();
  const permissions: string[] = [];
  for (const capability of manifest.capabilities) {
    if (!isRecord(capability) || !Array.isArray(capability.permissions)) continue;
    for (const item of capability.permissions) {
      if (typeof item !== 'string') continue;
      const permission = item.trim();
      if (!permission || seen.has(permission)) continue;
      seen.add(permission);
      permissions.push(permission);
    }
  }
  return permissions;
}

function pluginPath(name: string): string {
  return `${BASE}/${encodeURIComponent(name)}`;
}

async function runAction(name: string, action: string): Promise<PluginRecord> {
  const response = await backendRequest<{ plugin: PluginRecord }>({
    method: action === 'uninstall' ? 'DELETE' : 'POST',
    path: action === 'uninstall' ? pluginPath(name) : `${pluginPath(name)}/${action}`,
  });
  return response.plugin;
}

async function runRuntimeAction(
  name: string,
  action: 'start' | 'stop' | 'restart',
): Promise<PluginRuntimeActionResponse> {
  return backendRequest<PluginRuntimeActionResponse>({
    method: 'POST',
    path: `${pluginPath(name)}/runtime/${action}`,
  });
}

export const pluginClient = {
  async list(status?: PluginStatus): Promise<PluginRecord[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    const response = await backendRequest<{ plugins: PluginRecord[] }>({
      method: 'GET',
      path: `${BASE}${query}`,
    });
    return response.plugins;
  },

  async get(name: string): Promise<PluginRecord> {
    const response = await backendRequest<{ plugin: PluginRecord }>({
      method: 'GET',
      path: pluginPath(name),
    });
    return response.plugin;
  },

  async install(input: InstallPluginInput): Promise<PluginRecord> {
    try {
      const response = await backendRequest<{ plugin: PluginRecord }>({
        method: 'POST',
        path: BASE,
        body: {
          manifest: input.manifest,
          install_path: input.installPath,
          confirm_permissions: Boolean(input.confirmPermissions),
        },
      });
      return response.plugin;
    } catch (error) {
      const confirmation = parsePluginConfirmationError(error);
      if (confirmation) throw new PluginPermissionConfirmationRequiredError(confirmation);
      throw error;
    }
  },

  enable(name: string): Promise<PluginRecord> {
    return runAction(name, 'enable');
  },

  disable(name: string): Promise<PluginRecord> {
    return runAction(name, 'disable');
  },

  restore(name: string): Promise<PluginRecord> {
    return runAction(name, 'restore');
  },

  uninstall(name: string): Promise<PluginRecord> {
    return runAction(name, 'uninstall');
  },

  async updateConfig(name: string, config: Record<string, unknown>): Promise<PluginRecord> {
    const response = await backendRequest<{ plugin: PluginRecord }>({
      method: 'PATCH',
      path: `${pluginPath(name)}/config`,
      body: { config },
    });
    return response.plugin;
  },

  async runtime(name: string): Promise<PluginRuntimeActionResponse> {
    return backendRequest<PluginRuntimeActionResponse>({
      method: 'GET',
      path: `${pluginPath(name)}/runtime`,
    });
  },

  async runtimeTools(): Promise<PublishedPluginTool[]> {
    const response = await backendRequest<{ tools: PublishedPluginTool[]; count: number }>({
      method: 'GET',
      path: `${BASE}/runtime/tools`,
    });
    return response.tools;
  },

  startRuntime(name: string): Promise<PluginRuntimeActionResponse> {
    return runRuntimeAction(name, 'start');
  },

  stopRuntime(name: string): Promise<PluginRuntimeActionResponse> {
    return runRuntimeAction(name, 'stop');
  },

  restartRuntime(name: string): Promise<PluginRuntimeActionResponse> {
    return runRuntimeAction(name, 'restart');
  },

  async invokeRuntime(
    name: string,
    capability: string,
    args: Record<string, unknown>,
  ): Promise<PluginInvokeResponse> {
    return backendRequest<PluginInvokeResponse>({
      method: 'POST',
      path: `${pluginPath(name)}/runtime/invoke`,
      body: { capability, arguments: args },
    });
  },

  async permissions(name: string): Promise<PluginPermissions> {
    return backendRequest<PluginPermissions>({
      method: 'GET',
      path: `${pluginPath(name)}/permissions`,
    });
  },

  async logs(name?: string, limit = 50): Promise<PluginEvent[]> {
    const query = `?limit=${encodeURIComponent(String(limit))}`;
    const response = await backendRequest<{ logs: PluginEvent[] }>({
      method: 'GET',
      path: name ? `${pluginPath(name)}/logs${query}` : `${BASE}/logs${query}`,
    });
    return response.logs;
  },
};
export function auditPluginClientGovernance(): string {
  return JSON.stringify({
    module: 'plugin-client',
    phase: 'P189',
    audited: true,
  });
}
