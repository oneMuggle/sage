import type { JournalContentDraft } from '../useJournalTemplates';

export interface JournalContentEditorProps {
  content: JournalContentDraft;
  onChange: (patch: Partial<JournalContentDraft>) => void;
  disabled?: boolean;
}

export function JournalContentEditor({ content, onChange, disabled }: JournalContentEditorProps) {
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
      <div>
        <label className="mb-1 block text-xs font-medium text-slate-700">标题</label>
        <input
          type="text"
          value={content.title}
          onChange={(e) => onChange({ title: e.target.value })}
          disabled={disabled}
          className="w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
        />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-slate-700">摘要</label>
        <textarea
          value={content.abstract}
          onChange={(e) => onChange({ abstract: e.target.value })}
          disabled={disabled}
          rows={4}
          className="w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
        />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-slate-700">关键词</label>
        <input
          type="text"
          value={content.sections.keywords ?? ''}
          onChange={(e) =>
            onChange({ sections: { ...content.sections, keywords: e.target.value } })
          }
          disabled={disabled}
          className="w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
        />
      </div>
    </div>
  );
}
