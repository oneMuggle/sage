import { FileSearch, Sparkles, Upload } from 'lucide-react';

import { type UseJournalTemplatesReturn } from '../useJournalTemplates';

export interface JournalActionsProps {
  templates: UseJournalTemplatesReturn;
  workspacePath: string | null;
}

export function JournalActions({ templates, workspacePath }: JournalActionsProps) {
  const { pickTemplate, validateFile, fillFromContent, spec, loading, error } = templates;
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void pickTemplate()}
          disabled={loading}
          data-testid="journal-pick-template"
          className="inline-flex items-center gap-1 rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          <Upload className="h-3 w-3" />
          选择模板
        </button>
        <button
          type="button"
          onClick={async () => {
            const picked = await window.electronAPI?.office.pickOfficeFile('word');
            if (picked) await validateFile(picked.path, spec?.spec_id);
          }}
          disabled={loading || !spec}
          data-testid="journal-validate"
          className="inline-flex items-center gap-1 rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
        >
          <FileSearch className="h-3 w-3" />
          校验已写论文
        </button>
        <button
          type="button"
          onClick={async () => {
            if (!workspacePath) return;
            await fillFromContent(workspacePath, `paper-${Date.now()}.docx`);
          }}
          disabled={loading || !spec || !workspacePath}
          data-testid="journal-fill"
          className="inline-flex items-center gap-1 rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          <Sparkles className="h-3 w-3" />
          结构化填充
        </button>
      </div>
      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}
