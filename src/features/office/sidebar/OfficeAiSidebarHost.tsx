import { useMemo, useState } from 'react';
import type { RefObject } from 'react';

import {
  useOfficeWorkspaceStore,
  type SuggestionCardData,
} from '../../../entities/office/officeWorkspaceStore';
import { fillTemplate } from '../../../shared/lib/fillTemplate';
import { useI18n } from '../../../shared/lib/i18n';
import { joinWorkspacePath } from '../latexPath';

import { AiSidebar } from './AiSidebar';
import { FloatingActionBar, type FloatingActionKind } from './FloatingActionBar';
import type { QuickActionTab } from './QuickActions';
import { collectDocumentParagraphs } from './selectionAnchor';
import { useAiCapabilities } from './useAiCapabilities';
import { useSelectionCapture } from './useSelectionCapture';

export interface OfficeAiSidebarHostProps {
  activeTab: QuickActionTab;
  onNavigateTab: (tab: QuickActionTab) => void;
  /** R10: canonical workspace directory (non-null — Office.tsx gates the mount). */
  workspacePath: string;
  /** R10: document canvas root used for selection capture and paragraph collection. */
  rootRef: RefObject<HTMLElement>;
}

/**
 * Page-level mount for the AI sidebar.
 *
 * Wires `useSelectionCapture` + `useAiCapabilities` into the floating
 * selection toolbar and the command input, and renders the sidebar shell.
 */
export function OfficeAiSidebarHost({
  activeTab,
  onNavigateTab,
  workspacePath,
  rootRef,
}: OfficeAiSidebarHostProps): JSX.Element {
  const { t } = useI18n();
  const sidebarOpen = useOfficeWorkspaceStore((s) => s.sidebarOpen);
  const toggleSidebar = useOfficeWorkspaceStore((s) => s.toggleSidebar);
  const conversation = useOfficeWorkspaceStore((s) => s.conversation);
  const setSidebarOpen = useOfficeWorkspaceStore((s) => s.setSidebarOpen);
  const activeDocument = useOfficeWorkspaceStore((s) => s.activeDocument);
  const selection = useOfficeWorkspaceStore((s) => s.selection);
  const setSelection = useOfficeWorkspaceStore((s) => s.setSelection);
  const appendMessage = useOfficeWorkspaceStore((s) => s.appendMessage);

  // Prefilled command draft (used by "就这段提问" in the floating bar).
  const [initialCommand, setInitialCommand] = useState<string | undefined>(undefined);

  // R10: derive the absolute path of the active document from the workspace
  // root + generated filename. Office.tsx does not drill this through
  // OfficePreviewPanel.
  const filePath = useMemo(
    () =>
      activeDocument ? joinWorkspacePath(workspacePath, activeDocument.generated_filename) : null,
    [activeDocument, workspacePath],
  );

  useSelectionCapture(rootRef);

  const { pending, errorText, runRewrite, runChat, applySuggestion, markSkipped } =
    useAiCapabilities({ rootRef, filePath, onNavigateTab });

  // Anchor for the floating selection toolbar. Recomputed whenever the
  // normalized selection changes; the DOM rect is only meaningful while the
  // browser still holds a live range.
  const anchorRect = useMemo(() => {
    if (!selection) return null;
    const domSelection = window.getSelection();
    if (!domSelection || domSelection.rangeCount === 0) return null;
    const rect = domSelection.getRangeAt(0).getBoundingClientRect();
    return { top: rect.top, left: rect.left, width: rect.width };
  }, [selection]);

  const canApply = activeDocument?.doc_type === 'word' && Boolean(filePath);

  const documentText = (): string => {
    const root = rootRef.current;
    if (!root) return '';
    return collectDocumentParagraphs(root)
      .map((p) => p.text)
      .join('\n');
  };

  const handleFloatingAction = (kind: FloatingActionKind) => {
    if (!selection) return;

    if (kind === 'rewrite') {
      void runRewrite({
        instruction: 'polish',
        text: selection.text,
        paraIndex: selection.anchorParaIndex,
      });
      return;
    }

    if (kind === 'chat') {
      setSidebarOpen(true);
      setInitialCommand(selection.rawContext);
      return;
    }

    // Task 6: edit / audit flows are implemented in the next milestone.
    // For now, prefill the selection for edit and drop a system placeholder
    // for audit so the user sees where the capability will land.
    setSidebarOpen(true);
    if (kind === 'edit') {
      setInitialCommand(selection.rawContext);
    } else {
      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'system',
        content: '审校功能将在 Task 6 实现',
        createdAt: Date.now(),
      });
    }
  };

  const handleDismissFloating = () => {
    setSelection(null);
  };

  const handleCommand = async (value: string) => {
    // Drop the prefilled draft once a command is actually submitted so the
    // next chat action starts from a clean slate.
    setInitialCommand(undefined);

    if (!value.startsWith('/')) {
      await runChat(value);
      return;
    }

    const command = value.split(/\s+/)[0].toLowerCase();

    if (command === '/audit') {
      // Task 6: full-document audit will replace this placeholder.
      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'system',
        content: '审校功能将在 Task 6 实现',
        createdAt: Date.now(),
      });
      return;
    }

    if (command === '/summarize') {
      await runRewrite({ instruction: 'summarize', text: documentText() });
      return;
    }

    if (command === '/translate') {
      await runRewrite({ instruction: 'translate', targetLang: '中文', text: documentText() });
      return;
    }

    if (command === '/rules') {
      onNavigateTab('rules');
      return;
    }

    appendMessage({
      id: `msg-${Date.now()}`,
      role: 'system',
      content: fillTemplate(t('office.ai.sidebar.unknown_command'), { command }),
      createdAt: Date.now(),
    });
  };

  const handleApply = (messageId: string, suggestion: SuggestionCardData) => {
    void applySuggestion(messageId, suggestion);
  };

  const handleSkip = (messageId: string, suggestionId: string) => {
    markSkipped(messageId, suggestionId);
  };

  return (
    <>
      {!sidebarOpen && (
        <button
          type="button"
          data-testid="office-ai-sidebar-toggle"
          aria-expanded={sidebarOpen}
          aria-controls="office-ai-sidebar-panel"
          className="fixed right-4 bottom-4 z-30 rounded-full bg-accent px-4 py-2 text-sm text-accent-foreground shadow-lg"
          onClick={toggleSidebar}
        >
          {t('office.ai.sidebar.open')}
        </button>
      )}
      {sidebarOpen ? (
        <AiSidebar
          activeTab={activeTab}
          messages={conversation}
          pending={pending}
          errorText={errorText}
          disabled={false}
          initialCommand={initialCommand}
          onCommand={handleCommand}
          onApply={handleApply}
          onSkip={handleSkip}
          onClose={() => setSidebarOpen(false)}
          floatingBar={null}
        />
      ) : null}
      <FloatingActionBar
        anchorRect={anchorRect}
        canApply={canApply}
        onAction={handleFloatingAction}
        onDismiss={handleDismissFloating}
      />
    </>
  );
}
