import { FileSpreadsheet, FileText, Presentation, X } from 'lucide-react';

import type {
  ConversationMessage,
  SuggestionCardData,
} from '../../../entities/office/officeWorkspaceStore';
import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';
import type { OfficeDocType } from '../../../shared/api/types';
import { useI18n } from '../../../shared/lib/i18n';

import { CommandInput } from './CommandInput';
import { ConversationArea } from './ConversationArea';
import { QuickActions, type QuickActionTab } from './QuickActions';

const DOC_TYPE_ICONS: Record<OfficeDocType, React.ReactNode> = {
  ppt: <Presentation className="h-3.5 w-3.5" />,
  word: <FileText className="h-3.5 w-3.5" />,
  excel: <FileSpreadsheet className="h-3.5 w-3.5" />,
  pdf: <FileText className="h-3.5 w-3.5" />,
};

export interface AiSidebarProps {
  activeTab: QuickActionTab;
  messages: ConversationMessage[];
  pending: boolean;
  errorText: string | null;
  disabled: boolean;
  initialCommand?: string;
  initialCommandKey?: number;
  onCommand: (value: string) => void;
  onApply: (messageId: string, suggestion: SuggestionCardData) => void;
  onSkip: (messageId: string, suggestionId: string) => void;
  onClose: () => void;
  floatingBar: React.ReactNode;
  /** R18: forwarded to ConversationArea for the last pending-assistant message. */
  onApplyAll?: (messageId: string) => void;
}

export function AiSidebar({
  activeTab,
  messages,
  pending,
  errorText,
  disabled,
  initialCommand,
  initialCommandKey,
  onCommand,
  onApply,
  onSkip,
  onClose,
  floatingBar,
  onApplyAll,
}: AiSidebarProps): JSX.Element {
  const { t } = useI18n();
  const activeDocument = useOfficeWorkspaceStore((s) => s.activeDocument);

  return (
    <aside
      id="office-ai-sidebar-panel"
      data-testid="office-ai-sidebar"
      className="fixed right-0 top-0 z-30 flex h-full w-[360px] flex-col border-l border-border bg-surface shadow-xl"
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <h2 className="flex-1 text-sm font-medium">{t('office.ai.sidebar.title')}</h2>
        {activeDocument ? (
          <div className="flex items-center gap-1.5 rounded-full border border-border bg-bg-subtle px-2 py-0.5 text-xs">
            {DOC_TYPE_ICONS[activeDocument.doc_type]}
            <span className="max-w-[180px] truncate text-text-secondary">
              {activeDocument.original_filename}
            </span>
            <button
              type="button"
              data-testid="office-ai-sidebar-clear-doc"
              aria-label={t('office.ai.sidebar.clear_document')}
              className="rounded p-0.5 text-text-muted hover:bg-surface-hover hover:text-text"
              onClick={() => useOfficeWorkspaceStore.getState().setActiveDocument(null)}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ) : (
          <span className="truncate text-xs text-text-muted">
            {t('office.ai.sidebar.hint_select_document')}
          </span>
        )}
        <button
          type="button"
          data-testid="office-ai-sidebar-close"
          aria-label={t('office.ai.sidebar.close')}
          className="rounded p-1 hover:bg-surface-hover"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Quick actions */}
      <div className="border-b border-border px-3 py-2">
        <QuickActions tab={activeTab} hasDocument={Boolean(activeDocument)} onCommand={onCommand} />
      </div>

      {/* Conversation */}
      <ConversationArea
        messages={messages}
        pending={pending}
        onApply={onApply}
        onSkip={onSkip}
        onApplyAll={onApplyAll}
      />

      {/* Error */}
      {errorText && (
        <div className="border-t border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
          {errorText}
        </div>
      )}

      {/* Command input */}
      <CommandInput
        disabled={disabled}
        pending={pending}
        initialValue={initialCommand}
        initialValueKey={initialCommandKey}
        onSubmit={onCommand}
      />

      {/* Floating selection bar (portal-rendered, passed in) */}
      {floatingBar}
    </aside>
  );
}
