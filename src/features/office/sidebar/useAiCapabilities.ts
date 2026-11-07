import { useState } from 'react';
import type { RefObject } from 'react';

import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';
import type { SuggestionCardData } from '../../../entities/office/officeWorkspaceStore';
import { aiApi, type AiRewriteInstruction } from '../../../shared/api/aiApi';
import { officeSpecApi } from '../../../shared/api/officeSpecApi';
import { fillTemplate } from '../../../shared/lib/fillTemplate';
import { useI18n } from '../../../shared/lib/i18n';

import type { QuickActionTab } from './QuickActions';
import { collectDocumentParagraphs } from './selectionAnchor';
import { suggestionFromRewrite, toReviseIssue } from './suggestionFactory';

export interface AiCapabilities {
  pending: boolean;
  errorText: string | null;
  runRewrite: (params: {
    instruction: AiRewriteInstruction;
    text: string;
    targetLang?: string;
    paraIndex?: number | null;
  }) => Promise<void>;
  runChat: (message: string) => Promise<void>;
  applySuggestion: (messageId: string, suggestion: SuggestionCardData) => Promise<void>;
  markSkipped: (messageId: string, suggestionId: string) => void;
}

export function useAiCapabilities(deps: {
  rootRef: RefObject<HTMLElement>;
  filePath: string | null;
  onNavigateTab: (tab: QuickActionTab) => void;
}): AiCapabilities {
  const { t } = useI18n();
  const [pending, setPending] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const activeDocument = useOfficeWorkspaceStore((s) => s.activeDocument);
  const conversation = useOfficeWorkspaceStore((s) => s.conversation);
  const appendMessage = useOfficeWorkspaceStore((s) => s.appendMessage);
  const updateSuggestionStatus = useOfficeWorkspaceStore((s) => s.updateSuggestionStatus);

  const runRewrite = async (params: {
    instruction: AiRewriteInstruction;
    text: string;
    targetLang?: string;
    paraIndex?: number | null;
  }) => {
    if (!activeDocument) {
      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'system',
        content: t('office.ai.sidebar.no_document'),
        createdAt: Date.now(),
      });
      return;
    }

    setPending(true);
    setErrorText(null);

    try {
      const result = await aiApi.rewrite({
        workspacePath: activeDocument.workspace_path ?? '',
        documentId: activeDocument.id,
        text: params.text,
        instruction: params.instruction,
        ...(params.targetLang ? { targetLang: params.targetLang } : {}),
      });

      const paraIndex = params.paraIndex ?? -1;
      const attachments: SuggestionCardData[] =
        paraIndex >= 0
          ? [
              suggestionFromRewrite({
                paraIndex,
                originalText: params.text,
                suggestedText: result.result,
              }),
            ]
          : [];

      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content: result.result,
        attachments,
        createdAt: Date.now(),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const errorMessage = fillTemplate(t('office.ai.sidebar.request_failed'), { message });
      setErrorText(errorMessage);
      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'system',
        content: errorMessage,
        createdAt: Date.now(),
      });
    } finally {
      setPending(false);
    }
  };

  const runChat = async (message: string) => {
    if (!activeDocument) {
      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'system',
        content: t('office.ai.sidebar.no_document'),
        createdAt: Date.now(),
      });
      return;
    }

    setPending(true);
    setErrorText(null);

    appendMessage({
      id: `msg-${Date.now()}-user`,
      role: 'user',
      content: message,
      createdAt: Date.now(),
    });

    try {
      const history = conversation
        .filter((m) => m.role !== 'system')
        .slice(-20)
        .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }));

      const root = deps.rootRef.current;
      const documentContext = root
        ? collectDocumentParagraphs(root)
            .map((p) => p.text)
            .join('\n')
            .slice(0, 4000)
        : '';

      const result = await aiApi.chat({
        workspacePath: activeDocument.workspace_path ?? '',
        documentId: activeDocument.id,
        message,
        history,
        documentContext,
      });

      appendMessage({
        id: `msg-${Date.now()}-assistant`,
        role: 'assistant',
        content: result.reply,
        createdAt: Date.now(),
      });
    } catch (error) {
      const messageText = error instanceof Error ? error.message : String(error);
      const errorMessage = fillTemplate(t('office.ai.sidebar.request_failed'), {
        message: messageText,
      });
      setErrorText(errorMessage);
      appendMessage({
        id: `msg-${Date.now()}-system`,
        role: 'system',
        content: errorMessage,
        createdAt: Date.now(),
      });
    } finally {
      setPending(false);
    }
  };

  const applySuggestion = async (messageId: string, suggestion: SuggestionCardData) => {
    if (!deps.filePath || !activeDocument) {
      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'system',
        content: t('office.ai.sidebar.apply_disabled'),
        createdAt: Date.now(),
      });
      return;
    }

    setPending(true);
    setErrorText(null);

    try {
      await officeSpecApi.reviseAiIssues({
        workspace_path: activeDocument.workspace_path ?? '',
        file_path: deps.filePath,
        doc_id: activeDocument.id,
        issues: [toReviseIssue(suggestion)],
        add_comments: true,
      });

      updateSuggestionStatus(messageId, suggestion.id, 'applied');
      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'system',
        content: t('office.ai.sidebar.apply_done'),
        createdAt: Date.now(),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const errorMessage = fillTemplate(t('office.ai.sidebar.apply_failed'), { message });
      setErrorText(errorMessage);
      appendMessage({
        id: `msg-${Date.now()}`,
        role: 'system',
        content: errorMessage,
        createdAt: Date.now(),
      });
    } finally {
      setPending(false);
    }
  };

  const markSkipped = (messageId: string, suggestionId: string) => {
    updateSuggestionStatus(messageId, suggestionId, 'skipped');
  };

  return {
    pending,
    errorText,
    runRewrite,
    runChat,
    applySuggestion,
    markSkipped,
  };
}
