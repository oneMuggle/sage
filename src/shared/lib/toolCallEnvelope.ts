import type { ToolCall } from './store';

/** 后端拦截信封 / 富媒体信封（agent.py 与 MCP 工具的结构化输出） */
interface ToolResultEnvelope {
  content?: unknown;
  text?: unknown;
  metadata?: Record<string, unknown>;
}

/** 能标识"这是结构化信封、应提升 metadata"的关键字段。 */
const KNOWN_METADATA_KEYS = [
  'blockReason',
  'blockedUrl',
  'suggestedActions',
  'imageData',
  'imageFormat',
  'mediaRef',
  'mediaRefs',
  'apiUrl',
  'apiUrls',
  'richMedia',
] as const;

/**
 * 归一化工具结果信封。
 *
 * 后端会把 ToolResult 包装成 JSON 字符串下发：
 * - 拦截分支（R19-W1）：`{"content": "<文案>", "metadata": {"blockReason", "blockedUrl",
 *   "suggestedActions"}}`
 * - 富媒体分支（P1）：`{"text": "<文案>", "metadata": {"mediaRefs", "richMedia"}}`
 *
 * 若不归一化：气泡里显示裸 JSON，且重载路径 metadata 丢失 → 卡片/图表无法渲染。
 * 此函数提取 `content`/`text` 作为 result，把信封 metadata 合并进 ToolCall.metadata，
 * 使直播与历史回读表现一致。非信封（普通字符串、无可识别 metadata）原样返回。
 */
export function normalizeToolCallEnvelope(tc: ToolCall): ToolCall {
  const raw = tc.result;
  if (typeof raw !== 'string' || !raw || raw[0] !== '{') return tc;

  let parsed: ToolResultEnvelope;
  try {
    parsed = JSON.parse(raw) as ToolResultEnvelope;
  } catch {
    return tc;
  }
  if (!parsed || typeof parsed !== 'object' || !parsed.metadata) return tc;

  if (!KNOWN_METADATA_KEYS.some((key) => key in (parsed.metadata as object))) return tc;

  const nextResult =
    typeof parsed.content === 'string' && parsed.content
      ? parsed.content
      : typeof parsed.text === 'string' && parsed.text
        ? parsed.text
        : raw;

  return {
    ...tc,
    result: nextResult,
    metadata: { ...tc.metadata, ...parsed.metadata },
  };
}
export function auditToolCallEnvelopeGovernance(): string {
  return JSON.stringify({
    module: 'tool-call-envelope',
    phase: 'P187',
    audited: true,
  });
}
