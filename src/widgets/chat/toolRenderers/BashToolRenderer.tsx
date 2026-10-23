/**
 * BashToolRenderer — 专用 bash/terminal/run_shell 工具卡片。
 *
 * 显示: 命令（mono 代码块）+ 输出（可折叠，截断至 8 行）。
 */

import { Terminal } from 'lucide-react';

import type { ToolCall } from '../../../shared/lib/store';

import { ToolCallCard } from './ToolCallCard';

const MAX_OUTPUT_LINES = 8;

function truncateOutput(text: string, maxLines: number): { text: string; truncated: boolean } {
  const lines = text.split('\n');
  if (lines.length <= maxLines) return { text, truncated: false };
  return { text: lines.slice(0, maxLines).join('\n'), truncated: true };
}

export function BashToolRenderer({ tc }: { tc: ToolCall }) {
  const command = String(tc.args.command ?? '');
  const result = typeof tc.result === 'string' ? tc.result : '';
  const { text: outputPreview, truncated } = truncateOutput(result, MAX_OUTPUT_LINES);

  return (
    <ToolCallCard
      tc={tc}
      title={
        <span className="flex items-center gap-1.5">
          <Terminal className="w-3.5 h-3.5 text-primary shrink-0" />
          <span className="font-medium">Run command</span>
        </span>
      }
      summary={
        command ? <code className="text-ui-xs max-w-[120px] truncate">{command}</code> : undefined
      }
      defaultCollapsed={!!result}
    >
      {/* Command */}
      <div className="mt-1 rounded bg-bg px-2 py-1 font-mono text-ui-2xs text-text overflow-x-auto">
        <span className="text-success">$</span> {command}
      </div>

      {/* Output */}
      {outputPreview && (
        <pre className="mt-1 rounded bg-bg px-2 py-1 font-mono text-ui-2xs text-text-secondary overflow-x-auto whitespace-pre-wrap">
          {outputPreview}
          {truncated && '\n…'}
        </pre>
      )}
    </ToolCallCard>
  );
}

export interface BashToolRendererAuditInput {
  commandText: string;
  exitCode: number | null;
  outputLineCount: number;
  timedOut: boolean;
}

export interface BashToolRendererAuditReport {
  hasCommand: boolean;
  exitCode: number | null;
  outputLineCount: number;
  timedOut: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateBashToolRendererAudit(
  input: BashToolRendererAuditInput,
): BashToolRendererAuditReport {
  const hasCommand = input.commandText.trim().length > 0;
  const outputLineCount = Math.max(0, Math.trunc(input.outputLineCount));
  const timedOut = Boolean(input.timedOut);
  const issueCodes: string[] = [];

  if (!hasCommand) {
    issueCodes.push('empty_bash_command');
  }
  if (timedOut) {
    issueCodes.push('bash_command_timed_out');
  }
  if (input.exitCode !== null && input.exitCode !== 0) {
    issueCodes.push('non_zero_bash_exit_code');
  }

  return {
    hasCommand,
    exitCode: input.exitCode,
    outputLineCount,
    timedOut,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportBashToolRendererAuditJson(
  input: BashToolRendererAuditInput,
): string {
  return JSON.stringify(evaluateBashToolRendererAudit(input));
}
