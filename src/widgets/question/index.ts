/**
 * Question Widgets — M2 part B: AskUserQuestion 提问 UI
 */
export { QuestionDialog } from './QuestionDialog';

export interface QuestionBarrelAuditInput {
  exportedSymbols: string[];
  hasQuestionDialogExport: boolean;
}

export interface QuestionBarrelAuditReport {
  uniqueSymbolCount: number;
  hasQuestionDialogExport: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateQuestionBarrelGovernanceAudit(
  input: QuestionBarrelAuditInput,
): QuestionBarrelAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.exportedSymbols
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
  const uniqueSymbolCount = new Set(normalized).size;
  if (uniqueSymbolCount === 0) {
    issueCodes.push('QUESTION_BARREL_EMPTY');
  }
  if (!input.hasQuestionDialogExport) {
    issueCodes.push('QUESTION_DIALOG_EXPORT_MISSING');
  }
  return {
    uniqueSymbolCount,
    hasQuestionDialogExport: input.hasQuestionDialogExport,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
