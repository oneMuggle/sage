import { useMemo, useState } from 'react';
import type { RefObject } from 'react';

import {
  useOfficeWorkspaceStore,
  type SuggestionCardData,
} from '../../../entities/office/officeWorkspaceStore';
import { fillTemplate } from '../../../shared/lib/fillTemplate';
import { useI18n } from '../../../shared/lib/i18n';

import { AiSidebar } from './AiSidebar';
import { FloatingActionBar, type FloatingActionKind } from './FloatingActionBar';
import type { QuickActionTab } from './QuickActions';
import { collectDocumentParagraphs } from './selectionAnchor';
import { nextMessageId, useAiCapabilities } from './useAiCapabilities';
import { useAuditSuggestions } from './useAuditSuggestions';
import { useSelectionCapture } from './useSelectionCapture';

/** Prefilled command draft. `seq` bumps on every prefill so equal text still re-syncs. */
interface InitialCommand {
  value: string;
  seq: number;
}

/** Pending edit flow — carries the anchor para-index and paragraph text. */
interface PendingEdit {
  anchorParaIndex: number;
  paragraphText: string;
  seq: number;
}

export interface OfficeAiSidebarHostProps {
  activeTab: QuickActionTab;
  onNavigateTab: (tab: QuickActionTab) => void;
  /** Document canvas root used for selection capture and paragraph collection. */
  rootRef: RefObject<HTMLElement>;
}

/**
 * Page-level mount for the AI sidebar.
 *
 * Wires `useSelectionCapture` + `useAiCapabilities` + `useAuditSuggestions`
 * into the floating selection toolbar and the command input, and renders the
 * sidebar shell.
 */
export function OfficeAiSidebarHost({
  activeTab,
  onNavigateTab,
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

  // Prefilled command draft (used by "就这段提问" / "按指令修改" in the floating bar).
  const [initialCommand, setInitialCommand] = useState<InitialCommand | null>(null);
  // Pending edit — cleared once the user submits the instruction.
  const [pendingEdit, setPendingEdit] = useState<PendingEdit | null>(null);

  const prefillInitialCommand = (value: string) => {
    setInitialCommand((prev) => ({ value, seq: (prev?.seq ?? 0) + 1 }));
  };

  const startPendingEdit = (anchorParaIndex: number, paragraphText: string, draftTail: string) => {
    setPendingEdit((prev) => ({
      anchorParaIndex,
      paragraphText,
      seq: (prev?.seq ?? 0) + 1,
    }));
    prefillInitialCommand(`${t('office.ai.edit.prefix')}${draftTail}`);
  };

  useSelectionCapture(rootRef);

  const { pending, errorText, runRewrite, runChat, applySuggestion, markSkipped } =
    useAiCapabilities({ rootRef });
  const { running: auditRunning, runAudit, applyAll } = useAuditSuggestions({ rootRef });

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

  const canApply = activeDocument?.doc_type === 'word';

  const documentText = (): string => {
    const root = rootRef.current;
    if (!root) return '';
    return collectDocumentParagraphs(root)
      .map((p) => p.text)
      .join('\n');
  };

  const paragraphByIndex = (index: number): string | null => {
    const root = rootRef.current;
    if (!root) return null;
    const found = collectDocumentParagraphs(root).find((p) => p.index === index);
    return found ? found.text : null;
  };

  const busy = pending || auditRunning;

  const handleFloatingAction = (kind: FloatingActionKind) => {
    // Ignore floating-bar actions while an AI request is in flight so rapid
    // clicks cannot interleave awaits and desync `pending` / reply order.
    if (!selection || busy) return;
    // Every floating action operates on the active document. Without one the
    // request would be rejected downstream — skip it instead of surfacing an
    // error inside the conversation.
    if (!activeDocument) return;

    if (kind === 'rewrite') {
      setPendingEdit(null);
      setSidebarOpen(true);
      void runRewrite({
        instruction: 'polish',
        text: selection.text,
        paraIndex: selection.anchorParaIndex,
      });
      return;
    }

    if (kind === 'chat') {
      setPendingEdit(null);
      setSidebarOpen(true);
      prefillInitialCommand(selection.rawContext);
      return;
    }

    if (kind === 'edit') {
      if (selection.anchorParaIndex == null) {
        setSidebarOpen(true);
        appendMessage({
          id: nextMessageId(),
          role: 'system',
          content: t('office.ai.edit.no_match'),
          createdAt: Date.now(),
        });
        return;
      }
      const paragraphText = paragraphByIndex(selection.anchorParaIndex);
      if (!paragraphText) {
        setSidebarOpen(true);
        appendMessage({
          id: nextMessageId(),
          role: 'system',
          content: t('office.ai.edit.no_match'),
          createdAt: Date.now(),
        });
        return;
      }
      setSidebarOpen(true);
      startPendingEdit(selection.anchorParaIndex, paragraphText, selection.text);
      return;
    }

    // kind === 'audit'
    setPendingEdit(null);
    setSidebarOpen(true);
    void runAudit();
  };

  const handleDismissFloating = () => {
    setSelection(null);
  };

  const handleSlashCommand = async (command: string) => {
    if (command === '/audit') {
      setPendingEdit(null);
      void runAudit();
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
      id: nextMessageId(),
      role: 'system',
      content: fillTemplate(t('office.ai.sidebar.unknown_command'), { command }),
      createdAt: Date.now(),
    });
  };

  const handleCommand = async (value: string) => {
    // M1: only a draft that still carries the edit prefix is an edit command.
    const prefix = t('office.ai.edit.prefix');
    if (pendingEdit && value.startsWith(prefix)) {
      const edit = pendingEdit;
      const instruction = value.slice(prefix.length).trim();
      setPendingEdit(null);
      setInitialCommand(null);
      if (!instruction) return;
      await runRewrite({
        instruction: 'custom',
        customInstruction: instruction,
        text: edit.paragraphText,
        paraIndex: edit.anchorParaIndex,
      });
      return;
    }

    // Any other submission invalidates a previously prefilled edit draft.
    setPendingEdit(null);
    setInitialCommand(null);

    if (!value.startsWith('/')) {
      await runChat(value);
      return;
    }

    await handleSlashCommand(value.split(/\s+/)[0].toLowerCase());
  };

  const handleApply = (messageId: string, suggestion: SuggestionCardData) => {
    void applySuggestion(messageId, suggestion);
  };

  const handleSkip = (messageId: string, suggestionId: string) => {
    markSkipped(messageId, suggestionId);
  };

  const handleApplyAll = (messageId: string) => {
    void applyAll(messageId);
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
          pending={busy}
          errorText={errorText}
          disabled={false}
          initialCommand={initialCommand?.value}
          initialCommandKey={initialCommand?.seq}
          onCommand={handleCommand}
          onApply={handleApply}
          onSkip={handleSkip}
          onApplyAll={handleApplyAll}
          onClose={() => {
            setSidebarOpen(false);
            setInitialCommand(null);
            setPendingEdit(null);
          }}
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
