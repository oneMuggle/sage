import { FileText } from 'lucide-react';

import type { JournalSpec } from '../../../shared/api/types';

export interface JournalSpecCardProps {
  spec: JournalSpec | null;
}

export function JournalSpecCard({ spec }: JournalSpecCardProps) {
  if (!spec) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">
        尚未选择模板。点击「选择模板」开始。
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
      <div className="mb-2 flex items-center gap-2 font-semibold">
        <FileText className="h-4 w-4" />
        <span>{spec.template_filename}</span>
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
