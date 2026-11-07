import { X } from 'lucide-react';

import type {
  ConversationMessage,
  SuggestionCardData,
} from '../../../entities/office/officeWorkspaceStore';
import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';
import { useI18n } from '../../../shared/lib/i18n';

import { CommandInput } from './CommandInput';
import { ConversationArea } from './ConversationArea';
import { QuickActions, type QuickActionTab } from './QuickActions';

export interface AiSidebarProps {
  activeTab: QuickActionTab;
  messages: ConversationMessage[];
  pending: boolean;
  errorText: string | null;
  disabled: boolean;
  onCommand: (value: string) => void;
  onApply: (messageId: string, suggestion: SuggestionCardData) => void;
  onSkip: (messageId: string, suggestionId: string) => void;
  onClose: () => void;
  floatingBar: React.ReactNode;
}

export function AiSidebar({
  activeTab,
  messages,
  pending,
  errorText,
  disabled,
  onCommand,
  onApply,
  onSkip,
  onClose,
  floatingBar,
}: AiSidebarProps): JSX.Element {
  const { t } = useI18n();
  const activeDocument = useOfficeWorkspaceStore((s) => s.activeDocument);

  return (
    <aside
      data-testid="office-ai-sidebar"
      className="fixed right-0 top-0 z-30 flex h-full w-[360px] flex-col border-l border-border bg-surface shadow-xl"
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <h2 className="flex-1 text-sm font-medium">{t('office.ai.sidebar.title')}</h2>
        <span className="truncate text-xs text-text-muted">
          {activeDocument
            ? `${t('office.ai.sidebar.current_document')}: ${activeDocument.original_filename}`
            : t('office.ai.sidebar.no_document')}
        </span>
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
        <QuickActions tab={activeTab} onCommand={onCommand} />
      </div>

      {/* Conversation */}
      <ConversationArea messages={messages} pending={pending} onApply={onApply} onSkip={onSkip} />

      {/* Error */}
      {errorText && (
        <div className="border-t border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
          {errorText}
        </div>
      )}

      {/* Command input */}
      <CommandInput disabled={disabled} pending={pending} onSubmit={onCommand} />

      {/* Floating selection bar (portal-rendered, passed in) */}
      {floatingBar}
    </aside>
  );
}
