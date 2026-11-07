import { useI18n, type TranslationKey } from '../../../shared/lib/i18n';

export type QuickActionTab = 'documents' | 'generate' | 'rules' | 'latex';

export interface QuickCommand {
  id: string;
  labelKey: TranslationKey;
  command: string;
}

const COMMANDS: Record<QuickActionTab, QuickCommand[]> = {
  documents: [
    { id: 'audit', labelKey: 'office.ai.quick.documents.audit', command: '/audit' },
    { id: 'rules', labelKey: 'office.ai.quick.documents.rules', command: '/rules' },
    { id: 'summary', labelKey: 'office.ai.quick.documents.summary', command: '/summarize' },
    { id: 'translate', labelKey: 'office.ai.quick.documents.translate', command: '/translate' },
  ],
  generate: [
    { id: 'expand', labelKey: 'office.ai.quick.generate.expand', command: '/expand' },
    { id: 'structure', labelKey: 'office.ai.quick.generate.structure', command: '/structure' },
    { id: 'details', labelKey: 'office.ai.quick.generate.details', command: '/details' },
    {
      id: 'consistency',
      labelKey: 'office.ai.quick.generate.consistency',
      command: '/consistency',
    },
  ],
  rules: [
    { id: 'extract', labelKey: 'office.ai.quick.rules.extract', command: '/rules' },
    { id: 'conflicts', labelKey: 'office.ai.quick.rules.conflicts', command: '/conflicts' },
    { id: 'merge', labelKey: 'office.ai.quick.rules.merge', command: '/merge' },
  ],
  latex: [
    { id: 'compile', labelKey: 'office.ai.quick.latex.compile', command: '/compile' },
    { id: 'citations', labelKey: 'office.ai.quick.latex.citations', command: '/citations' },
    { id: 'formulas', labelKey: 'office.ai.quick.latex.formulas', command: '/formulas' },
  ],
};

// eslint-disable-next-line react-refresh/only-export-components
export function quickCommandsForTab(tab: QuickActionTab): QuickCommand[] {
  return COMMANDS[tab];
}

export interface QuickActionsProps {
  tab: QuickActionTab;
  onCommand: (command: string) => void;
}

export function QuickActions({ tab, onCommand }: QuickActionsProps): JSX.Element {
  const { t } = useI18n();
  return (
    <div data-testid="office-ai-quick-actions" className="flex flex-wrap gap-1.5">
      {quickCommandsForTab(tab).map((item) => (
        <button
          key={item.id}
          type="button"
          data-testid={`office-ai-quick-${item.id}`}
          className="rounded-full border border-border px-2.5 py-1 text-xs hover:bg-surface-hover"
          onClick={() => onCommand(item.command)}
        >
          {t(item.labelKey)}
        </button>
      ))}
    </div>
  );
}
