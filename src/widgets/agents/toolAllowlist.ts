/**
 * 工具白名单的纯函数与类型（自 `EditAgentForm` 抽取，供 `ToolAllowlistEditor`
 * 与专家向导共用）。后端 `tool_name_in_allowlist` 是合法性的唯一权威，
 * 这里只做文本规范化与 UI 状态镜像。
 */
import type { PluginStatus } from '../../shared/api/pluginClient';

/**
 * 工具白名单文本解析（R92）：按空白/逗号切分，去空白与重复项并保持
 * 首次出现顺序。`plugin__*` / `plugin__<插件名>__*` 等通配条目原样
 * 保留，合法性判定在后端 domain matcher，前端只做文本规范化。
 */
export function parseAgentToolsInput(text: string): string[] {
  const seen = new Set<string>();
  const tools: string[] = [];
  for (const part of text.split(/[\s,]+/)) {
    const entry = part.trim();
    if (entry && !seen.has(entry)) {
      seen.add(entry);
      tools.push(entry);
    }
  }
  return tools;
}

/** 工具白名单回显格式：一行一项。 */
export function formatAgentToolsInput(tools: readonly string[] | undefined): string {
  return (tools ?? []).join('\n');
}

export const PLUGIN_TOOL_PREFIX = 'plugin__';

export interface PluginToolSelectionState {
  selected: boolean;
  exact: boolean;
  coveredBy?: string;
}

/**
 * 返回覆盖某插件工具的合法插件通配条目（R92/R94，R98 结构化）。
 *
 * 这里只为 UI 状态镜像后端 `tool_name_in_allowlist` 的两个插件
 * 通配：`plugin__*` 与 `plugin__<plugin>__*`。覆盖不再按完整
 * 工具名字符串前缀猜测归属（插件名与 capability 名都可含
 * `__`，同一字符串可能对应不同插件），必须以已发布快照的
 * 权威 `pluginName` 为准：工具名确实落在
 * `plugin__<pluginName>__` 命名空间内，且单插件通配与由该
 * 权威名派生的通配完全一致。缺少 `pluginName` 时不算覆盖
 * （fail-closed），与后端可见性/执行边界同口径。
 */
export function findPluginToolWildcardCover(
  entries: readonly string[],
  toolName: string,
  pluginName?: string,
): string | undefined {
  if (!pluginName) return undefined;
  const ownNamespace = `${PLUGIN_TOOL_PREFIX}${pluginName}__`;
  if (!toolName.startsWith(ownNamespace) || toolName.length <= ownNamespace.length) {
    return undefined;
  }

  for (const entry of entries) {
    if (entry === `${PLUGIN_TOOL_PREFIX}*`) return entry;
    if (entry === `${ownNamespace}*`) return entry;
  }
  return undefined;
}

/** 动态插件工具复选框状态：精确名与通配覆盖分开呈现。 */
export function pluginToolSelectionState(
  entries: readonly string[],
  toolName: string,
  pluginName?: string,
): PluginToolSelectionState {
  const exact = entries.includes(toolName);
  const coveredBy = findPluginToolWildcardCover(entries, toolName, pluginName);
  return { selected: exact || coveredBy !== undefined, exact, coveredBy };
}

/** 只增删完整工具名；通配与未运行工具条目原样保留。 */
export function toggleAgentToolSelection(
  entries: readonly string[],
  toolName: string,
  selected: boolean,
): string[] {
  if (selected) {
    return entries.includes(toolName) ? [...entries] : [...entries, toolName];
  }
  return entries.filter((entry) => entry !== toolName);
}

export type StalePluginEntryStatus = 'not-published' | 'uninstalled' | 'missing';

export interface StalePluginToolEntry {
  entry: string;
  /** 生命周期权威归属插件名；无记录时为 null（绝不切分条目猜名）。 */
  pluginName: string | null;
  status: StalePluginEntryStatus;
}

/** 与后端 `_is_valid_plugin_name_chars` 同一字符集（R107 镜像）。 */
function isValidPluginNameChars(value: string): boolean {
  return value.length > 0 && /^[A-Za-z0-9_.-]+$/.test(value);
}

/** 与后端 `is_plugin_tool_name` 同口径的形状判定（只判形状）。 */
function isPluginToolNameShape(name: string): boolean {
  if (name.includes('*') || !name.startsWith(PLUGIN_TOOL_PREFIX)) return false;
  if (!isValidPluginNameChars(name)) return false;
  const rest = name.slice(PLUGIN_TOOL_PREFIX.length);
  const separator = rest.indexOf('__');
  return separator > 0 && separator + 2 < rest.length;
}

/** 与后端 `is_plugin_tool_wildcard` 同口径：只认 plugin__* 与单插件通配。 */
function isPluginToolWildcardShape(entry: string): boolean {
  if (entry === `${PLUGIN_TOOL_PREFIX}*`) return true;
  if (!entry.startsWith(PLUGIN_TOOL_PREFIX) || !entry.endsWith('__*')) return false;
  const segment = entry.slice(PLUGIN_TOOL_PREFIX.length, -3);
  return segment.length > 0 && !segment.includes('*') && isValidPluginNameChars(segment);
}

/**
 * 条目的生命周期权威归属（镜像后端 `_rule_plugin_owner`）：长名优先
 * 逐个用权威名构造派生通配/命名空间做结构化比对——`a` 与 `a__b`
 * 共存时 `plugin__a__b__run` 归更具体的 `a__b`，不按字符串切分猜名。
 */
function findPluginEntryOwner(
  entry: string,
  records: readonly { name: string; status: PluginStatus }[],
): { name: string; status: PluginStatus } | undefined {
  const sorted = [...records].sort((a, b) => b.name.length - a.name.length);
  for (const record of sorted) {
    if (!isValidPluginNameChars(record.name)) continue;
    if (entry === `${PLUGIN_TOOL_PREFIX}${record.name}__*`) return record;
    const namespace = `${PLUGIN_TOOL_PREFIX}${record.name}__`;
    if (
      isPluginToolNameShape(entry) &&
      entry.startsWith(namespace) &&
      entry.length > namespace.length
    ) {
      return record;
    }
  }
  return undefined;
}

/**
 * 找出当前不对任何已发布工具生效的插件形白名单条目（R107）。
 *
 * 分类镜像后端 R101 归属标注：`plugin__*` 全局通配、非插件形条目，
 * 以及与发布快照精确同名/等于某已发布插件派生通配的在效条目都不
 * 返回。`pluginRecords=null`（名单读不到）→ [] 整体不标注，不把
 * 「读不到」误报成「无记录」；`publishedTools=null`（快照未知）→
 * 只给已卸载/无记录，「当前未发布」不猜。标注是只读派生，不写
 * 任何存储，profile 保存形状不变。
 */
export function findStalePluginToolEntries(
  entries: readonly string[],
  publishedTools: readonly { plugin_name: string; tool_name: string }[] | null,
  pluginRecords: readonly { name: string; status: PluginStatus }[] | null,
): StalePluginToolEntry[] {
  if (pluginRecords === null) return [];
  const publishedToolNames = new Set((publishedTools ?? []).map((tool) => tool.tool_name));
  const publishedWildcards = new Set(
    (publishedTools ?? [])
      .filter((tool) => isValidPluginNameChars(tool.plugin_name))
      .map((tool) => `${PLUGIN_TOOL_PREFIX}${tool.plugin_name}__*`),
  );
  const stale: StalePluginToolEntry[] = [];
  for (const entry of entries) {
    if (entry === `${PLUGIN_TOOL_PREFIX}*`) continue;
    if (!isPluginToolNameShape(entry) && !isPluginToolWildcardShape(entry)) continue;
    if (publishedToolNames.has(entry) || publishedWildcards.has(entry)) continue;
    const owner = findPluginEntryOwner(entry, pluginRecords);
    if (owner === undefined) {
      stale.push({ entry, pluginName: null, status: 'missing' });
    } else if (owner.status === 'uninstalled') {
      stale.push({ entry, pluginName: owner.name, status: 'uninstalled' });
    } else if (publishedTools !== null) {
      stale.push({ entry, pluginName: owner.name, status: 'not-published' });
    }
  }
  return stale;
}

export const STALE_STATUS_LABEL: Record<StalePluginEntryStatus, string> = {
  'not-published': '当前未发布',
  uninstalled: '插件已已卸载',
  missing: '插件无记录',
};
