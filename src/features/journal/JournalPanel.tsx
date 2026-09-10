import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

import { JournalActions } from './components/JournalActions';
import { JournalContentEditor } from './components/JournalContentEditor';
import { JournalSpecCard } from './components/JournalSpecCard';
import { JournalValidationReport } from './components/JournalValidationReport';
import { useJournalTemplates } from './useJournalTemplates';

export interface JournalPanelProps {
  /** Optional override for workspace path; falls back to the active workspace from SessionWorkspaceProvider. */
  workspacePath?: string | null;
}

export function JournalPanel({ workspacePath: wsOverride }: JournalPanelProps) {
  // Source of truth for the active session's workspace binding (Task 5,
  // 2026-07-26). Mirrors src/pages/Office.tsx:79 — the /office page is
  // the canonical wiring; the /journal panel reuses the same hook so a
  // workspace change in either view is visible to both.
  const activeWorkspace = useCurrentWorkspace() ?? null;
  const workspacePath = wsOverride ?? activeWorkspace;
  const templates = useJournalTemplates();

  const errorCount = templates.violations.filter((v) => v.severity === 'error').length;
  const warningCount = templates.violations.filter((v) => v.severity === 'warning').length;

  return (
    <section className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <header>
        <h2 className="text-base font-semibold text-slate-800">期刊模板助手</h2>
        <p className="text-xs text-slate-500">
          选择 .docx 期刊模板 → 填写内容 → 一键生成或校验格式
        </p>
      </header>
      <JournalActions templates={templates} workspacePath={workspacePath} />
      <JournalSpecCard spec={templates.spec} />
      <JournalContentEditor
        content={templates.content}
        onChange={templates.setContent}
        disabled={!templates.spec}
      />
      <JournalValidationReport
        violations={templates.violations}
        errorCount={errorCount}
        warningCount={warningCount}
      />
    </section>
  );
}
