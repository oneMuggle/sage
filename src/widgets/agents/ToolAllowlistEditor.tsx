import { useEffect, useRef, useState, type ReactNode } from 'react';

import {
  describePermission,
  pluginClient,
  type PluginRecord,
  type PublishedPluginTool,
} from '../../shared/api/pluginClient';
import { Button } from '../../shared/ui/Button';

import {
  findStalePluginToolEntries,
  formatAgentToolsInput,
  parseAgentToolsInput,
  pluginToolSelectionState,
  STALE_STATUS_LABEL,
  toggleAgentToolSelection,
} from './toolAllowlist';

interface ToolAllowlistEditorProps {
  value: string[];
  onChange: (next: string[]) => void;
  /** id/testid 前缀，默认 `agent`（保持既有 id 不变）。 */
  idPrefix?: string;
  label?: string;
  hint?: ReactNode;
}

const DEFAULT_HINT = (
  <>
    每行一项（也可用逗号分隔），保存时自动去空白与重复项；清空表示该 Agent
    不暴露任何工具。插件工具可写完整名（如
    <code> plugin__demo__hello</code>），或用 <code>plugin__demo__*</code>{' '}
    放行该插件的全部能力（包含其将来新增的能力）、
    <code>plugin__*</code> 放行全部插件。通配只决定可见性，插件调用仍
    走逐次审批；最小权限场景请写完整名。
  </>
);

/**
 * 工具白名单编辑器：文本白名单 + 运行中插件工具勾选 + 未发布条目清理。
 *
 * 文本态本地承接逐字输入（允许写到一半的名字、逗号分隔、重复行存在），
 * 只在外部 `value` 与本地解析结果不一致时回写文本——勾选能力包等外部
 * 变更会同步，正常输入不会被去重打断光标。
 */
export function ToolAllowlistEditor({
  value,
  onChange,
  idPrefix = 'agent',
  label = '工具白名单',
  hint = DEFAULT_HINT,
}: ToolAllowlistEditorProps) {
  const [toolsText, setToolsText] = useState<string>(() => formatAgentToolsInput(value));
  const lastExternalSignature = useRef(value.join('\n'));

  // 只在外部 `value` 真正变化时回写文本（如勾选能力包）。父组件未回写 props
  // 时本地输入/草稿不能被旧值覆盖，否则逐字输入与移除操作都会被清掉。
  useEffect(() => {
    const externalSignature = value.join('\n');
    if (externalSignature === lastExternalSignature.current) return;
    lastExternalSignature.current = externalSignature;
    if (parseAgentToolsInput(toolsText).join('\n') !== externalSignature) {
      setToolsText(externalSignature);
    }
  }, [value, toolsText]);

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

  const applyTools = (next: string[]) => {
    setToolsText(formatAgentToolsInput(next));
    onChange(next);
  };
  const handlePluginToolToggle = (toolName: string, selected: boolean) => {
    applyTools(toggleAgentToolSelection(selectedTools, toolName, selected));
  };

  // 快照未知（加载中/失败）时传 null：分类只给已卸载/无记录两类。
  const stalePluginEntries = findStalePluginToolEntries(
    selectedTools,
    pluginToolsLoading || pluginToolsError ? null : publishedPluginTools,
    pluginRecords,
  );
  const handleRemoveStaleEntry = (entry: string) => {
    applyTools(selectedTools.filter((candidate) => candidate !== entry));
  };

  const toolsId = `${idPrefix}-tools`;

  return (
    <div>
      <label htmlFor={toolsId} className="block text-sm font-medium mb-1">
        {label}
      </label>
      <textarea
        id={toolsId}
        value={toolsText}
        onChange={(e) => {
          const next = e.target.value;
          setToolsText(next);
          onChange(parseAgentToolsInput(next));
        }}
        rows={6}
        spellCheck={false}
        className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated font-mono text-xs"
      />
      <p className="text-xs text-muted mt-1">{hint}</p>
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
            加载运行中插件工具失败：{pluginToolsError}。可点击刷新重试， 或继续手动编辑上方文本。
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
              const checkboxId = `${idPrefix}-plugin-tool-${tool.tool_name}`;
              const descriptionPrefix = `[Plugin:${tool.plugin_name}] `;
              const description = tool.description.startsWith(descriptionPrefix)
                ? tool.description.slice(descriptionPrefix.length)
                : tool.description;
              const permissionSummary =
                tool.permissions.length > 0
                  ? tool.permissions.map((permission) => describePermission(permission)).join('、')
                  : '未声明权限（按外部进程处理）';
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
          data-testid={`${idPrefix}-stale-plugin-entries`}
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
                data-testid={`${idPrefix}-stale-plugin-entry`}
              >
                <code className="flex-1 break-all font-mono">{stale.entry}</code>
                <span
                  className="px-1 border border-border rounded-radius-sm text-muted shrink-0"
                  data-testid={`${idPrefix}-stale-plugin-status-${stale.entry}`}
                >
                  {STALE_STATUS_LABEL[stale.status]}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  data-testid={`${idPrefix}-stale-plugin-remove-${stale.entry}`}
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
  );
}
