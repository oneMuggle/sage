/**
 * Tool renderer registry — maps tool names to specialized renderer components.
 *
 * Usage in Message.tsx:
 *   const Renderer = resolveToolRenderer(tc.name);
 *   return <Renderer tc={tc} />;
 *
 * Unknown tool names return null — caller falls back to the generic card.
 */

import type { ComponentType } from 'react';

import type { ToolCall } from '../../../shared/lib/store';
import { BashToolRenderer } from './BashToolRenderer';
import { FileWriteToolRenderer } from './FileWriteToolRenderer';
import { WebSearchToolRenderer } from './WebSearchToolRenderer';

export type ToolRendererProps = { tc: ToolCall };
export type ToolRenderer = ComponentType<ToolRendererProps>;

/** 工具名 → 专用渲染器映射表 */
const REGISTRY: Readonly<Record<string, ToolRenderer>> = {
  // Shell / terminal
  bash: BashToolRenderer,
  terminal: BashToolRenderer,
  run_shell: BashToolRenderer,

  // File write / edit
  write_file: FileWriteToolRenderer,
  edit_file: FileWriteToolRenderer,

  // Web search
  web_search: WebSearchToolRenderer,
  search_web: WebSearchToolRenderer,
};

/**
 * 查找工具名对应的专用渲染器。
 * 未注册 → 返回 null，调用方应降级到通用卡片。
 */
export function resolveToolRenderer(toolName: string): ToolRenderer | null {
  return REGISTRY[toolName] ?? null;
}
