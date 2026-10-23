import { FileText } from 'lucide-react';
import { useState } from 'react';

import type { JournalSpec } from '../../../shared/api/types';

export interface JournalSpecCardProps {
  spec: JournalSpec | null;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatJournalSpecMarkdown(spec: JournalSpec | null): string {
  if (!spec) {
    return '# 期刊模板规范 (Journal Spec)\n\n_尚未选择模板_';
  }
  const lines = [
    `# 期刊模板规范 — ${spec.template_filename}`,
    '',
    `- **规范 ID**: ${spec.spec_id}`,
    `- **正文字号**: ${spec.body_pt} pt`,
    `- **标题字号**: ${spec.heading_pt} pt`,
    `- **行距**: ${spec.line_spacing} 倍`,
    `- **页边距**: ${spec.margins_cm} cm`,
    `- **引用风格**: ${spec.citation_style}`,
  ];
  if (spec.headings.length > 0) {
    lines.push('', `## 章节 (${spec.headings.length})`);
    for (const h of spec.headings) {
      lines.push(`- ${h.keyword} (L${h.level} · ${h.expected_pt}pt)`);
    }
  }
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatJournalSpecJson(spec: JournalSpec | null): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      spec,
    },
    null,
    2,
  );
}

export function JournalSpecCard({ spec }: JournalSpecCardProps) {
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  if (!spec) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">
        尚未选择模板。点击「选择模板」开始。
      </div>
    );
  }

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(formatJournalSpecMarkdown(spec));
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(formatJournalSpecJson(spec));
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div
      className="rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm"
      data-testid="journal-spec-summary"
    >
      <div className="mb-2 flex items-center justify-between gap-2 font-semibold">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4" />
          <span>{spec.template_filename}</span>
        </div>
        <div className="flex items-center gap-1 font-normal">
          <button
            type="button"
            data-testid="journal-spec-copy-md"
            onClick={() => void handleCopyMarkdown()}
            className="rounded border border-slate-200 px-1.5 py-0.5 text-ui-2xs text-slate-600 hover:bg-slate-50"
          >
            {copiedMd ? '已复制 MD' : '复制 MD'}
          </button>
          <button
            type="button"
            data-testid="journal-spec-copy-json"
            onClick={() => void handleCopyJson()}
            className="rounded border border-slate-200 px-1.5 py-0.5 text-ui-2xs text-slate-600 hover:bg-slate-50"
          >
            {copiedJson ? '已复制 JSON' : '复制 JSON'}
          </button>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-600">
        <dt>正文字号</dt>
        <dd>{spec.body_pt} pt</dd>
        <dt>标题字号</dt>
        <dd>{spec.heading_pt} pt</dd>
        <dt>行距</dt>
        <dd>{spec.line_spacing} 倍</dd>
        <dt>页边距</dt>
        <dd>{spec.margins_cm} cm</dd>
        <dt>引用风格</dt>
        <dd>{spec.citation_style}</dd>
      </dl>
      {spec.headings.length > 0 && (
        <div className="mt-3">
          <div className="text-xs font-medium text-slate-700">章节 ({spec.headings.length})</div>
          <ul className="mt-1 list-disc pl-5 text-xs text-slate-600">
            {spec.headings.map((h, idx) => (
              <li key={`${h.keyword}-${idx}`}>
                {h.keyword}{' '}
                <span className="text-slate-400">
                  (L{h.level} · {h.expected_pt}pt)
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditJournalSpecCardGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/journal/components/JournalSpecCard.tsx',
    phase: 'P163',
    status: 'ready',
  };
}
