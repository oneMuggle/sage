// src/features/office/rules/RulePackBar.tsx
import { useI18n } from '../../../shared/lib/i18n';

import type { RuleGroup } from './ruleTypes';

export interface RulePackBarProps {
  group: RuleGroup | null;
  busy: boolean;
  onExport: () => void | Promise<void>;
  onExportMarkdown?: () => void | Promise<void>;
  onImport: (file: File) => void | Promise<void>;
  onCheckConflicts: () => void | Promise<void>;
}

export function RulePackBar({
  group,
  busy,
  onExport,
  onExportMarkdown,
  onImport,
  onCheckConflicts,
}: RulePackBarProps) {
  const { t } = useI18n();

  return (
    <section
      className="flex flex-wrap items-center gap-2 rounded border border-border bg-bg-subtle p-3"
      data-testid="rules-pack-bar"
    >
      <button
        type="button"
        data-testid="rules-export"
        disabled={busy || !group}
        className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
        onClick={() => void onExport()}
      >
        {t('office.rules.workspace.export')}
      </button>
      {onExportMarkdown ? (
        <button
          type="button"
          data-testid="rules-export-markdown"
          disabled={busy || !group}
          className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
          onClick={() => void onExportMarkdown()}
        >
          {t('office.rules.workspace.exportMarkdown')}
        </button>
      ) : null}
      <label
        aria-disabled={busy || undefined}
        className={`rounded border border-border px-3 py-1.5 text-xs text-text-secondary ${
          busy ? 'pointer-events-none opacity-50' : 'cursor-pointer hover:bg-bg-hover'
        }`}
      >
        {t('office.rules.workspace.import')}
        <input
          type="file"
          accept=".sage-rules,application/json"
          data-testid="rules-import-input"
          className="hidden"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void onImport(file);
            event.target.value = '';
          }}
        />
      </label>
      <button
        type="button"
        data-testid="rules-check-conflicts"
        disabled={busy || !group || group.rules.length < 2}
        className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
        onClick={() => void onCheckConflicts()}
      >
        {t('office.rules.workspace.checkConflicts')}
      </button>
    </section>
  );
}
