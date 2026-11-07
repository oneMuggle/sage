import {
  useOfficeWorkspaceStore,
  type SuggestionCardData,
} from '../../../entities/office/officeWorkspaceStore';
import { useI18n } from '../../../shared/lib/i18n';

import { AiSidebar } from './AiSidebar';
import type { QuickActionTab } from './QuickActions';

export interface OfficeAiSidebarHostProps {
  activeTab: QuickActionTab;
  onNavigateTab: (tab: QuickActionTab) => void;
}

/**
 * Page-level mount for the AI sidebar.
 *
 * Task 5 will wire `pending` / `errorText` from `useAiCapabilities`;
 * this stage uses local no-op stubs so the shell compiles and renders.
 */
export function OfficeAiSidebarHost({
  activeTab,
  onNavigateTab,
}: OfficeAiSidebarHostProps): JSX.Element {
  const { t } = useI18n();
  const sidebarOpen = useOfficeWorkspaceStore((s) => s.sidebarOpen);
  const toggleSidebar = useOfficeWorkspaceStore((s) => s.toggleSidebar);
  const conversation = useOfficeWorkspaceStore((s) => s.conversation);
  const setSidebarOpen = useOfficeWorkspaceStore((s) => s.setSidebarOpen);

  // Task 5 stubs — replaced when useAiCapabilities is wired
  const pending = false;
  const errorText: string | null = null;
  const disabled = false;

  const handleCommand = (_value: string) => {
    // Task 5: dispatch to AI pipeline
  };

  const handleApply = (_messageId: string, _suggestion: SuggestionCardData) => {
    // Task 5: apply tracked changes
  };

  const handleSkip = (_messageId: string, _suggestionId: string) => {
    // Task 5: mark suggestion skipped
  };

  // Suppress unused-var warnings for Task 5 stubs
  void onNavigateTab;

  return (
    <>
      <button
        type="button"
        data-testid="office-ai-sidebar-toggle"
        aria-expanded={sidebarOpen}
        className="fixed right-4 bottom-4 z-30 rounded-full bg-accent px-4 py-2 text-sm text-accent-foreground shadow-lg"
        onClick={toggleSidebar}
      >
        {sidebarOpen ? t('office.ai.sidebar.close') : t('office.ai.sidebar.open')}
      </button>
      {sidebarOpen ? (
        <AiSidebar
          activeTab={activeTab}
          messages={conversation}
          pending={pending}
          errorText={errorText}
          disabled={disabled}
          onCommand={handleCommand}
          onApply={handleApply}
          onSkip={handleSkip}
          onClose={() => setSidebarOpen(false)}
          floatingBar={null}
        />
      ) : null}
    </>
  );
}
