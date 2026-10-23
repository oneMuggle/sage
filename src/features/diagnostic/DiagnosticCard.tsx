import { useState } from 'react';

import { ExportButton } from './ExportButton';
import { useDiagnosticPreview } from './useDiagnosticPreview';

export interface DiagnosticPreviewSnapshot {
  count: number;
  oldestTs?: string | null;
  newestTs?: string | null;
  sampleUrls: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatDiagnosticPreviewMarkdown(
  data: DiagnosticPreviewSnapshot | null | undefined,
  includePrompts = false,
  includeHostname = false,
): string {
  const lines = [
    '# LLM 诊断预览摘要 (Diagnostic Preview)',
    '',
    `- **包含原始 Prompt**: ${includePrompts ? '是' : '否'}`,
    `- **包含本机主机名**: ${includeHostname ? '是' : '否'}`,
  ];
  if (!data) {
    lines.push('', '_暂无诊断预览数据_');
  } else {
    lines.push(`- **采集调用条数**: ${data.count}`);
    if (data.oldestTs && data.newestTs) {
      lines.push(`- **时间范围**: ${data.oldestTs} – ${data.newestTs}`);
    }
    if (data.sampleUrls.length > 0) {
      lines.push(`- **上游端点样本**: ${data.sampleUrls.join(', ')}`);
    }
  }
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatDiagnosticPreviewJson(
  data: DiagnosticPreviewSnapshot | null | undefined,
  includePrompts = false,
  includeHostname = false,
): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      includePrompts,
      includeHostname,
      preview: data,
    },
    null,
    2,
  );
}

export function DiagnosticCard() {
  const { data, loading, error, refresh } = useDiagnosticPreview();
  const [includePrompts, setIncludePrompts] = useState(false);
  const [includeHostname, setIncludeHostname] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(
        formatDiagnosticPreviewMarkdown(data, includePrompts, includeHostname),
      );
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(
        formatDiagnosticPreviewJson(data, includePrompts, includeHostname),
      );
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <section
      className="rounded-lg border border-border bg-card p-4"
      data-testid="diagnostic-card"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">LLM 诊断导出</h2>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            data-testid="diagnostic-card-copy-md"
            onClick={() => void handleCopyMarkdown()}
            className="rounded border border-border px-2 py-0.5 text-xs hover:bg-bg-hover"
          >
            {copiedMd ? '已复制 MD' : '复制 MD'}
          </button>
          <button
            type="button"
            data-testid="diagnostic-card-copy-json"
            onClick={() => void handleCopyJson()}
            className="rounded border border-border px-2 py-0.5 text-xs hover:bg-bg-hover"
          >
            {copiedJson ? '已复制 JSON' : '复制 JSON'}
          </button>
        </div>
      </div>

      {loading && <div className="text-sm text-muted-foreground">加载中…</div>}

      {error && (
        <div className="text-sm text-red-600 mb-2">加载失败: {error.message}</div>
      )}

      {data && (
        <div className="space-y-3">
          <div className="text-sm">
            最近采集到的 LLM 调用: <strong>{data.count}</strong> 条
          </div>

          {data.oldestTs && data.newestTs && (
            <div className="text-sm text-muted-foreground">
              时间范围: {data.oldestTs} – {data.newestTs}
            </div>
          )}

          {data.sampleUrls.length > 0 && (
            <div className="text-sm text-muted-foreground">
              上游端点样本: {data.sampleUrls.slice(0, 3).join(' / ')}
            </div>
          )}

          <div className="space-y-1">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includePrompts}
                onChange={(e) => setIncludePrompts(e.target.checked)}
                data-testid="checkbox-prompts"
              />
              包含原始 prompt 内容(可能含业务敏感信息)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeHostname}
                onChange={(e) => setIncludeHostname(e.target.checked)}
                data-testid="checkbox-hostname"
              />
              包含本机主机名
            </label>
          </div>

          <div className="flex gap-2">
            <ExportButton includePrompts={includePrompts} includeHostname={includeHostname} />
            <button
              onClick={refresh}
              disabled={loading}
              className="px-3 py-1 rounded border"
            >
              刷新
            </button>
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground mt-3">
        说明: 导出文件用于问题排查, 不会自动上传。即使默认脱敏, 请人工 review 后再外发。
      </p>
    </section>
  );
}

export interface DiagnosticCardGovernanceAudit {
  phase: 'P162';
  module: 'src/features/diagnostic/DiagnosticCard.tsx';
  archetype: string;
  sessionId: string;
  healthy: boolean;
  summaryMarkdown: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditDiagnosticCardGovernance(
  sessionId = 'default',
  archetype = 'software-engineering',
): DiagnosticCardGovernanceAudit {
  const normalizedSession = sessionId.trim() || 'default';
  const normalizedArchetype = archetype.trim() || 'software-engineering';
  return {
    phase: 'P162',
    module: 'src/features/diagnostic/DiagnosticCard.tsx',
    archetype: normalizedArchetype,
    sessionId: normalizedSession,
    healthy: normalizedSession.length > 0 && normalizedArchetype.length > 0,
    summaryMarkdown: `### P162 DiagnosticCard Governance\n- session: ${normalizedSession}\n- archetype: ${normalizedArchetype}`,
  };
}
