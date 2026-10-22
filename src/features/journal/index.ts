export { JournalPanel } from './JournalPanel';
export type { JournalPanelProps } from './JournalPanel';
export { useJournalTemplates } from './useJournalTemplates';
export type { UseJournalTemplatesReturn, JournalContentDraft } from './useJournalTemplates';
export function formatJournalBarrelSummary(): string {
  return 'module=features/journal · exports=JournalPanel,useJournalTemplates · count=2';
}

export function formatJournalBarrelJson(): string {
  return JSON.stringify({
    module: 'features/journal',
    exports: ['JournalPanel', 'useJournalTemplates'],
    count: 2,
  });
}

