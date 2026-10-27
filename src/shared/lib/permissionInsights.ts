// src/shared/lib/permissionInsights.ts
//
// 权限列表的只读派生标注（R109 起自 PermissionRulesManager 落地，
// R110 下沉共享供聊天顶栏弹层同源复用）：
//
// - findShadowedRules：同列表内被更高优先级规则覆盖、恒不生效的行。
// - findPluginToolOwner：精确工具名对生命周期权威名的结构化归属。
// - formatPermissionModeMarkdown/Json：聊天顶栏弹层的模式与审
//   计导出（R112 自 PermissionModeSwitch 下沉，函数体原样；
//   与派生同为纯函数，供组件与测试从共享层引用）。
//
// 两者都只是渲染期派生，不写任何存储；身份维度只用权威数据源
// （R101 标注 / 生命周期名单），绝不切分名字猜插件。
import type {
  AutoApprovalRecord,
  PermissionPreset,
  PermissionRuleItem,
} from '../api/permissionApi';

const PLUGIN_TOOL_PREFIX = 'plugin__';

/** 裁决优先级（后端恒为 deny > allow > ask，见 permissions.py）。 */
const DECISION_RANK: Record<string, number> = { deny: 3, allow: 2, ask: 1 };

/**
 * R109 已保存规则遮蔽派生（R110 起会话规则列表同口径复用）：
 * 返回被同列表内更高优先级规则覆盖的规则下标 → 覆盖方
 * pattern。后端裁决恒取命中的最高优先级决定，故被覆盖的低
 * 优先级行恒不胜出、实际不会生效。覆盖只认严格可证的三类：
 * pattern 等值；覆盖方为 `plugin__*`；覆盖方为由本行权威
 * `plugin_name` 标注（R101）结构化派生的
 * `plugin__<name>__*`（只做等值比对，不切分本行 pattern 猜
 * 名；与 R107 前端派生同口径）。一般 fnmatch 包含关系不
 * 判，故所示恒真、至多漏标；无归属标注的行只判等值。
 */
export function findShadowedRules(rules: PermissionRuleItem[]): Map<number, string> {
  const shadowed = new Map<number, string>();
  rules.forEach((rule, index) => {
    const rank = DECISION_RANK[rule.decision] ?? 0;
    const coverPatterns: string[] = [rule.tool_pattern];
    if (rule.plugin_name) {
      coverPatterns.push('plugin__*', `plugin__${rule.plugin_name}__*`);
    }
    const covering = rules.find(
      (other, otherIndex) =>
        otherIndex !== index &&
        (DECISION_RANK[other.decision] ?? 0) > rank &&
        coverPatterns.includes(other.tool_pattern),
    );
    if (covering) shadowed.set(index, covering.tool_pattern);
  });
  return shadowed;
}

/** 与后端 `_is_valid_plugin_name_chars` 同一字符集（R107/R110 镜像）。 */
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

/**
 * 精确工具名的生命周期权威归属（镜像后端 belonging 与 R107 前
 * 端口径）：长名优先，逐个用权威名构造命名空间做结构化比对
 * ——`a` 与 `a__b` 共存时 `plugin__a__b__run` 归更具体的
 * `a__b`，不按字符串切分猜名。`pluginNames=null`（名单读不
 * 到）→ null 整体不归属（与 R107 降级一致）；非插件形（含
 * 通配形）→ null。
 */
export function findPluginToolOwner(
  toolName: string,
  pluginNames: readonly string[] | null,
): string | null {
  if (pluginNames === null) return null;
  if (!isPluginToolNameShape(toolName)) return null;
  const sorted = [...pluginNames].sort((a, b) => b.length - a.length);
  for (const name of sorted) {
    if (!isValidPluginNameChars(name)) continue;
    const namespace = `${PLUGIN_TOOL_PREFIX}${name}__`;
    if (toolName.startsWith(namespace) && toolName.length > namespace.length) return name;
  }
  return null;
}

/** 审计行的时间小帮手（秒级 HH:MM:SS，导出与弹层渲染共用）。 */
export function formatPermissionAuditTime(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

/** 聊天顶栏弹层的模式与自动放行审计导出（Markdown）。 */
export function formatPermissionModeMarkdown(params: {
  sessionId: string | null;
  preset: PermissionPreset;
  custom: boolean;
  count: number;
  items: ReadonlyArray<AutoApprovalRecord>;
}): string {
  const lines = [
    '# 会话权限模式与自动放行审计 (Permission Mode Summary)',
    '',
    `- **会话 ID**: ${params.sessionId ? `\`${params.sessionId}\`` : '全局'}`,
    `- **当前权限预设**: \`${params.preset}\`${params.custom ? ' (自定义)' : ''}`,
    `- **自动放行次数**: ${params.count}`,
  ];
  if (params.items.length === 0) {
    lines.push('', '_暂无自动放行审计记录_');
  } else {
    lines.push('', '## 自动放行审计明细');
    for (const it of params.items) {
      lines.push(
        `- **${it.tool_name}** (\`${it.capability}\`, ${formatPermissionAuditTime(it.created_at)}): ${it.summary || '-'}`,
      );
    }
  }
  return lines.join('\n');
}

/** 聊天顶栏弹层的模式与自动放行审计导出（JSON）。 */
export function formatPermissionModeJson(params: {
  sessionId: string | null;
  preset: PermissionPreset;
  custom: boolean;
  count: number;
  items: ReadonlyArray<AutoApprovalRecord>;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      ...params,
    },
    null,
    2,
  );
}
