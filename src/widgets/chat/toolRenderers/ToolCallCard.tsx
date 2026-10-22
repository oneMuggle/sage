/**
 * Tool call card wrapper — ZCode-inspired status-aware tool call visualization.
 *
 * Provides a consistent card shell: status icon + collapsible header + body area.
 * Individual tool renderers fill the body via `children`.
 */

import { ChevronDown, ChevronRight, Loader2, XCircle, CheckCircle2 } from 'lucide-react';
import { useState } from 'react';

import type { ToolCall } from '../../../shared/lib/store';

export type ToolStatus = 'running' | 'success' | 'error';

/** 推断工具调用状态：无 result → running；result 含 "error"/"failed" → error */
// eslint-disable-next-line react-refresh/only-export-components
export function inferToolStatus(tc: ToolCall): ToolStatus {
  if (tc.result === undefined) return 'running';
  const r = typeof tc.result === 'string' ? tc.result.toLowerCase() : '';
  if (tc.metadata?.blockReason) return 'error';
  if (r.includes('error:') || r.includes('failed') || r.includes('traceback')) return 'error';
  return 'success';
}

const STATUS_ICON: Record<ToolStatus, typeof Loader2> = {
  running: Loader2,
  success: CheckCircle2,
  error: XCircle,
};

const STATUS_COLOR: Record<ToolStatus, string> = {
  running: 'text-info',
  success: 'text-success',
  error: 'text-error',
};

interface ToolCallCardProps {
  tc: ToolCall;
  /** 标题区域（左侧，在状态图标右侧） */
  title: React.ReactNode;
  /** 可选摘要（右侧，折叠时可见） */
  summary?: React.ReactNode;
  /** 卡片主体内容 */
  children: React.ReactNode;
  /** 是否默认折叠（工具结果很长时有用） */
  defaultCollapsed?: boolean;
}

export function ToolCallCard({
  tc,
  title,
  summary,
  children,
  defaultCollapsed = false,
}: ToolCallCardProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const status = inferToolStatus(tc);
  const StatusIcon = STATUS_ICON[status];
  const statusColor = STATUS_COLOR[status];

  return (
    <div
      className="rounded border border-border bg-bg-subtle text-ui-sm overflow-hidden"
      data-testid="tool-call-card"
    >
      {/* Header — 可点击折叠 */}
      <button
        type="button"
        onClick={() => setCollapsed((prev) => !prev)}
        className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left hover:bg-bg-hover transition-colors"
        aria-expanded={!collapsed}
      >
        {collapsed ? (
          <ChevronRight className="w-3 h-3 text-text-muted shrink-0" />
        ) : (
          <ChevronDown className="w-3 h-3 text-text-muted shrink-0" />
        )}
        <StatusIcon
          className={`w-3.5 h-3.5 shrink-0 ${statusColor} ${status === 'running' ? 'animate-spin' : ''}`}
        />
        <span className="flex-1 min-w-0">{title}</span>
        {summary && <span className="text-text-muted shrink-0">{summary}</span>}
      </button>

      {/* Body — 折叠时隐藏 */}
      {!collapsed && <div className="px-2 pb-1.5">{children}</div>}
    </div>
  );
}

export interface ToolCallCardAuditInput {
  toolName: string;
  callId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  durationMs: number;
}

export interface ToolCallCardAuditReport {
  toolName: string;
  callId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  durationMs: number;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateToolCallCardAudit(
  input: ToolCallCardAuditInput,
): ToolCallCardAuditReport {
  const toolName = input.toolName.trim();
  const callId = input.callId.trim();
  const durationMs = Math.max(0, Math.trunc(input.durationMs));
  const issueCodes: string[] = [];

  if (!toolName) {
    issueCodes.push('missing_tool_name');
  }
  if (!callId) {
    issueCodes.push('missing_tool_call_id');
  }
  if (input.status === 'failed') {
    issueCodes.push('tool_call_failed');
  }

  return {
    toolName,
    callId,
    status: input.status,
    durationMs,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportToolCallCardAuditJson(
  input: ToolCallCardAuditInput,
): string {
  return JSON.stringify(evaluateToolCallCardAudit(input));
}
