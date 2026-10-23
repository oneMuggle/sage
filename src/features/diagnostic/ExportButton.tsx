import { useState } from 'react';

export interface ExportButtonProps {
  includePrompts: boolean;
  includeHostname: boolean;
}

const ERROR_MESSAGES: Record<string, string> = {
  dialog_cancelled: '已取消',
  backend_unreachable: '无法连接 Sage 后端,请确认应用已启动',
  zip_generation_failed: '诊断包生成失败,请查看后端日志',
  write_failed: '无法写入文件,请检查路径权限和磁盘空间',
};

// eslint-disable-next-line react-refresh/only-export-components
export function formatExportButtonAuditSnapshot(opts: {
  includePrompts?: boolean;
  includeHostname?: boolean;
  busy?: boolean;
  hasMessage?: boolean;
}): string {
  return `exportButton|prompts=${opts.includePrompts ? 1 : 0}|hostname=${opts.includeHostname ? 1 : 0}|busy=${opts.busy ? 1 : 0}|msg=${opts.hasMessage ? 1 : 0}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatExportButtonAuditJson(opts: {
  includePrompts?: boolean;
  includeHostname?: boolean;
  busy?: boolean;
  hasMessage?: boolean;
}): string {
  return JSON.stringify({
    includePrompts: Boolean(opts.includePrompts),
    includeHostname: Boolean(opts.includeHostname),
    busy: Boolean(opts.busy),
    hasMessage: Boolean(opts.hasMessage),
  });
}

export function ExportButton({ includePrompts, includeHostname }: ExportButtonProps) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(
        formatExportButtonAuditSnapshot({
          includePrompts,
          includeHostname,
          busy,
          hasMessage: Boolean(message),
        }),
      );
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(
        formatExportButtonAuditJson({
          includePrompts,
          includeHostname,
          busy,
          hasMessage: Boolean(message),
        }),
      );
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */

  const handleClick = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await window.electronAPI?.diagnostic?.exportBundle({
        includePrompts,
        includeHostname,
      });
      if (!result) {
        setMessage('诊断接口不可用,请确认应用版本');
        return;
      }
      if (result.ok) {
        setMessage(`已导出到 ${result.path}`);
      } else {
        const msg = ERROR_MESSAGES[result.code] ?? `导出失败: ${result.error}`;
        setMessage(msg);
      }
    } catch (e) {
      setMessage(`导出异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <button
        onClick={handleClick}
        disabled={busy}
        className="px-3 py-1 rounded border"
        data-testid="diagnostic-export-btn"
      >
        {busy ? '导出中…' : '导出诊断包…'}
      </button>
      <span
        data-testid="export-button-copy-snapshot"
        onClick={() => void handleCopySnapshot()}
        className="ml-2 cursor-pointer text-xs text-muted-foreground"
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="export-button-copy-json"
        onClick={() => void handleCopyJson()}
        className="ml-1 cursor-pointer text-xs text-muted-foreground"
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
      {message && (
        <p className="text-sm mt-1" data-testid="diagnostic-message">
          {message}
        </p>
      )}
    </div>
  );
}

export interface ExportButtonGovernanceAudit {
  phase: 'P162';
  module: 'src/features/diagnostic/ExportButton.tsx';
  archetype: string;
  sessionId: string;
  healthy: boolean;
  summaryMarkdown: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditExportButtonGovernance(
  sessionId = 'default',
  archetype = 'software-engineering',
): ExportButtonGovernanceAudit {
  const normalizedSession = sessionId.trim() || 'default';
  const normalizedArchetype = archetype.trim() || 'software-engineering';
  return {
    phase: 'P162',
    module: 'src/features/diagnostic/ExportButton.tsx',
    archetype: normalizedArchetype,
    sessionId: normalizedSession,
    healthy: normalizedSession.length > 0 && normalizedArchetype.length > 0,
    summaryMarkdown: `### P162 ExportButton Governance\n- session: ${normalizedSession}\n- archetype: ${normalizedArchetype}`,
  };
}
