import { useEffect, useState } from 'react';

import type { AgentProfile, AgentUpdate } from '../../shared/api';
import {
  describePermission,
  pluginClient,
  type PluginRecord,
  type PluginStatus,
  type PublishedPluginTool,
} from '../../shared/api/pluginClient';
import { Button } from '../../shared/ui/Button';

/**
 * 工具白名单文本解析（R92）：按空白/逗号切分，去空白与重复项并保持
 * 首次出现顺序。`plugin__*` / `plugin__<插件名>__*` 等通配条目原样
 * 保留，合法性判定在后端 domain matcher，前端只做文本规范化。
 */
// eslint-disable-next-line react-refresh/only-export-components
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
// eslint-disable-next-line react-refresh/only-export-components
export function formatAgentToolsInput(tools: readonly string[] | undefined): string {
  return (tools ?? []).join('\n');
}

const PLUGIN_TOOL_PREFIX = 'plugin__';

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
// eslint-disable-next-line react-refresh/only-export-components
export function findPluginToolWildcardCover(
  entries: readonly string[],
  toolName: string,
  pluginName?: string,
): string | undefined {
  if (!pluginName) return undefined;
  const ownNamespace = `${PLUGIN_TOOL_PREFIX}${pluginName}__`;
  if (
    !toolName.startsWith(ownNamespace) ||
    toolName.length <= ownNamespace.length
  ) {
    return undefined;
  }

  for (const entry of entries) {
    if (entry === `${PLUGIN_TOOL_PREFIX}*`) return entry;
    if (entry === `${ownNamespace}*`) return entry;
  }
  return undefined;
}

/** 动态插件工具复选框状态：精确名与通配覆盖分开呈现。 */
// eslint-disable-next-line react-refresh/only-export-components
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
// eslint-disable-next-line react-refresh/only-export-components
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
// eslint-disable-next-line react-refresh/only-export-components
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

const STALE_STATUS_LABEL: Record<StalePluginEntryStatus, string> = {
  'not-published': '当前未发布',
  uninstalled: '插件已已卸载',
  missing: '插件无记录',
};

interface EditAgentFormProps {
  agent: AgentProfile;
  form: Partial<AgentUpdate>;
  onChange: (form: Partial<AgentUpdate>) => void;
  onSave: () => void;
  onCancel: () => void;
}

export function EditAgentForm({ agent, form, onChange, onSave, onCancel }: EditAgentFormProps) {
  // 取值优先用 form 中的草稿值, 缺则回退到 agent 原值。
  // 注: model_config 在 form 中是部分对象, 取时合并 agent 原值的字段。
  const value = <K extends keyof AgentProfile>(key: K): AgentProfile[K] =>
    form[key as keyof AgentUpdate] !== undefined
      ? (form[key as keyof AgentUpdate] as AgentProfile[K])
      : agent[key];

  // tools 用本地文本态承接逐字输入（允许写到一半的名字/重复行存在），
  // 每次变更把解析后的数组同步回 form 草稿；直接用 value('tools') 回显
  // 会在输入过程中被去重/重排打断光标。
  const [toolsText, setToolsText] = useState<string>(() =>
    formatAgentToolsInput(value('tools')),
  );
  useEffect(() => {
    setToolsText(formatAgentToolsInput(agent.tools));
  }, [agent]);

  const [publishedPluginTools, setPublishedPluginTools] = useState<PublishedPluginTool[]>([]);
  const [pluginToolsLoading, setPluginToolsLoading] = useState(true);
  const [pluginToolsError, setPluginToolsError] = useState<string | null>(null);
  const [pluginToolsRequestId, setPluginToolsRequestId] = useState(0);
  const [pluginRecords, setPluginRecords] = useState<PluginRecord[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    setPluginToolsLoading(true);
    setPluginToolsError(null);
    pluginClient
      .runtimeTools()
      .then((tools) => {
        if (!cancelled) setPublishedPluginTools(tools);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setPluginToolsError(error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        if (!cancelled) setPluginToolsLoading(false);
      });
    // R107：同刷新周期取生命周期名单（未发布条目标注的数据源）；
    // 失败置 null 整体降级不标注，不新增错误面——读不到只代表
    // 「不知道」，与 R101「读不到≠无记录」同口径。
    pluginClient
      .list()
      .then((records) => {
        if (!cancelled) setPluginRecords(records);
      })
      .catch(() => {
        if (!cancelled) setPluginRecords(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pluginToolsRequestId]);

  const selectedTools = parseAgentToolsInput(toolsText);
  const handlePluginToolToggle = (toolName: string, selected: boolean) => {
    const nextTools = toggleAgentToolSelection(selectedTools, toolName, selected);
    setToolsText(formatAgentToolsInput(nextTools));
    onChange({ ...form, tools: nextTools });
  };

  // 快照未知（加载中/失败）时传 null：分类只给已卸载/无记录两类。
  const stalePluginEntries = findStalePluginToolEntries(
    selectedTools,
    pluginToolsLoading || pluginToolsError ? null : publishedPluginTools,
    pluginRecords,
  );
  const handleRemoveStaleEntry = (entry: string) => {
    const nextTools = selectedTools.filter((candidate) => candidate !== entry);
    setToolsText(formatAgentToolsInput(nextTools));
    onChange({ ...form, tools: nextTools });
  };

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="agent-name" className="block text-sm font-medium mb-1">
          名称
        </label>
        <input
          id="agent-name"
          type="text"
          value={value('name')}
          onChange={(e) => onChange({ ...form, name: e.target.value })}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label htmlFor="agent-description" className="block text-sm font-medium mb-1">
          描述
        </label>
        <input
          id="agent-description"
          type="text"
          value={value('description')}
          onChange={(e) => onChange({ ...form, description: e.target.value })}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label htmlFor="agent-system-prompt" className="block text-sm font-medium mb-1">
          系统提示
        </label>
        <textarea
          id="agent-system-prompt"
          value={value('system_prompt')}
          onChange={(e) => onChange({ ...form, system_prompt: e.target.value })}
          rows={4}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label htmlFor="agent-tools" className="block text-sm font-medium mb-1">
          工具白名单
        </label>
        <textarea
          id="agent-tools"
          value={toolsText}
          onChange={(e) => {
            const next = e.target.value;
            setToolsText(next);
            onChange({ ...form, tools: parseAgentToolsInput(next) });
          }}
          rows={6}
          spellCheck={false}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated font-mono text-xs"
        />
        <p className="text-xs text-muted mt-1">
          每行一项（也可用逗号分隔），保存时自动去空白与重复项；清空表示该
          Agent 不暴露任何工具。插件工具可写完整名（如
          <code> plugin__demo__hello</code>），或用 <code>plugin__demo__*</code>{' '}
          放行该插件的全部能力（包含其将来新增的能力）、
          <code>plugin__*</code> 放行全部插件。通配只决定可见性，插件调用仍
          走逐次审批；最小权限场景请写完整名。
        </p>
        <div className="mt-3 rounded-lg border border-border p-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">运行中插件工具</p>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setPluginToolsRequestId((requestId) => requestId + 1)}
              disabled={pluginToolsLoading}
            >
              刷新
            </Button>
          </div>
          <p className="mt-1 text-xs text-muted">
            仅列出已启动且已发布到聊天的工具；勾选只把完整名写入上方
            白名单草稿，仍需保存，且不会跳过逐次审批。
          </p>
          {pluginToolsLoading ? (
            <p className="mt-3 text-xs text-muted">正在加载运行中插件工具…</p>
          ) : pluginToolsError ? (
            <p className="mt-3 text-xs text-error" role="alert">
              加载运行中插件工具失败：{pluginToolsError}。可点击刷新重试，
              或继续手动编辑上方文本。
            </p>
          ) : publishedPluginTools.length === 0 ? (
            <p className="mt-3 text-xs text-muted">
              当前没有已发布的运行中插件工具。先到插件页启动插件，再刷新。
            </p>
          ) : (
            <div className="mt-3 space-y-3">
              {publishedPluginTools.map((tool) => {
                const selection = pluginToolSelectionState(
                  selectedTools,
                  tool.tool_name,
                  tool.plugin_name,
                );
                const coveredOnly = !selection.exact && selection.coveredBy !== undefined;
                const checkboxId = `agent-plugin-tool-${tool.tool_name}`;
                const descriptionPrefix = `[Plugin:${tool.plugin_name}] `;
                const description = tool.description.startsWith(descriptionPrefix)
                  ? tool.description.slice(descriptionPrefix.length)
                  : tool.description;
                const permissionSummary =
                  tool.permissions.length > 0
                    ? tool.permissions.map((permission) => describePermission(permission)).join('、')
                    : '未声明权限（按外部进程执行处理）';
                return (
                  <div key={tool.tool_name} className="flex items-start gap-2">
                    <input
                      id={checkboxId}
                      type="checkbox"
                      checked={selection.selected}
                      disabled={coveredOnly}
                      onChange={(event) =>
                        handlePluginToolToggle(tool.tool_name, event.target.checked)
                      }
                      className="mt-1"
                    />
                    <div className="min-w-0">
                      <label htmlFor={checkboxId} className="block text-sm font-medium">
                        {tool.plugin_name} · {tool.capability_name}
                      </label>
                      <p className="break-all font-mono text-xs text-muted">{tool.tool_name}</p>
                      {description ? <p className="mt-1 text-xs">{description}</p> : null}
                      <p className="mt-1 text-xs text-muted">
                        风险 {tool.risk.toUpperCase()} · 权限：{permissionSummary}
                      </p>
                      {selection.coveredBy ? (
                        <p className="mt-1 text-xs text-warning">
                          {selection.exact
                            ? `同时被通配 ${selection.coveredBy} 覆盖；取消精确名后仍会可见。`
                            : `由通配 ${selection.coveredBy} 覆盖；取消需编辑上方通配条目。`}
                        </p>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {stalePluginEntries.length > 0 && (
          <div
            className="mt-3 rounded-lg border border-border p-3"
            data-testid="agent-stale-plugin-entries"
          >
            <p className="text-sm font-medium">未发布的插件条目</p>
            <p className="mt-1 text-xs text-muted">
              以下条目当前没有对应的已发布工具（插件未启动、已卸载或无记录
              时不会对任何调用生效）；保留它们只会在插件将来发布同名工具
              时生效。移除只改上方白名单草稿，仍需保存。
            </p>
            <ul className="mt-3 space-y-2">
              {stalePluginEntries.map((stale) => (
                <li
                  key={stale.entry}
                  className="flex items-center gap-2 text-xs"
                  data-testid="agent-stale-plugin-entry"
                >
                  <code className="flex-1 break-all font-mono">{stale.entry}</code>
                  <span
                    className="px-1 border border-border rounded-radius-sm text-muted shrink-0"
                    data-testid={`agent-stale-plugin-status-${stale.entry}`}
                  >
                    {STALE_STATUS_LABEL[stale.status]}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    data-testid={`agent-stale-plugin-remove-${stale.entry}`}
                    aria-label={`移除 ${stale.entry}`}
                    onClick={() => handleRemoveStaleEntry(stale.entry)}
                  >
                    移除
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label htmlFor="agent-model" className="block text-sm font-medium mb-1">
            模型
          </label>
          <input
            id="agent-model"
            type="text"
            value={value('model_config').model}
            onChange={(e) =>
              onChange({
                ...form,
                model_config: { ...value('model_config'), model: e.target.value },
              })
            }
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
        </div>
        <div>
          <label htmlFor="agent-temperature" className="block text-sm font-medium mb-1">
            Temperature
          </label>
          <input
            id="agent-temperature"
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={value('model_config').temperature}
            onChange={(e) =>
              onChange({
                ...form,
                model_config: {
                  ...value('model_config'),
                  temperature: parseFloat(e.target.value),
                },
              })
            }
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
        </div>
        <div>
          <label htmlFor="agent-max-tokens" className="block text-sm font-medium mb-1">
            Max Tokens
          </label>
          <input
            id="agent-max-tokens"
            type="number"
            min="256"
            max="8192"
            step="256"
            value={value('model_config').max_tokens}
            onChange={(e) =>
              onChange({
                ...form,
                model_config: {
                  ...value('model_config'),
                  max_tokens: parseInt(e.target.value),
                },
              })
            }
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
        </div>
      </div>

      <div>
        <label htmlFor="agent-max-iterations" className="block text-sm font-medium mb-1">
          最大迭代次数
        </label>
        <input
          id="agent-max-iterations"
          type="number"
          min="1"
          max="50"
          step="1"
          value={value('max_iterations')}
          onChange={(e) =>
            onChange({
              ...form,
              max_iterations: Math.max(1, parseInt(e.target.value || '1', 10) || 1),
            })
          }
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
        <p className="text-xs text-muted mt-1">
          单轮 ReAct 循环允许的最大步数；任务超出该上限会被标记为迭代超限
        </p>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          取消
        </Button>
        <Button variant="primary" onClick={onSave}>
          保存
        </Button>
      </div>
    </div>
  );
}

export interface EditAgentFormAuditReport {
  schemaVersion: '1.0';
  module: 'src/widgets/agents/EditAgentForm.tsx';
  componentName: 'EditAgentForm';
  hasNameField: boolean;
  hasSystemPromptField: boolean;
  isDirty: boolean;
  exportedAt: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditEditAgentForm(
  name = 'Research Agent',
  systemPrompt = 'You are a helpful research assistant.',
  isDirty = false,
): EditAgentFormAuditReport {
  return {
    schemaVersion: '1.0',
    module: 'src/widgets/agents/EditAgentForm.tsx',
    componentName: 'EditAgentForm',
    hasNameField: name.trim().length > 0,
    hasSystemPromptField: systemPrompt.trim().length > 0,
    isDirty: Boolean(isDirty),
    exportedAt: '2026-10-22',
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportEditAgentFormAuditJson(
  name = 'Research Agent',
  systemPrompt = 'You are a helpful research assistant.',
  isDirty = false,
): string {
  return JSON.stringify(auditEditAgentForm(name, systemPrompt, isDirty), null, 2);
}
