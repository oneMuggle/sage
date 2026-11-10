import { useState } from 'react';
import type { RefObject } from 'react';

import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';
import type { SuggestionCardData } from '../../../entities/office/officeWorkspaceStore';
import { aiApi, type AiRewriteInstruction } from '../../../shared/api/aiApi';
import { officeSpecApi } from '../../../shared/api/officeSpecApi';
import { fillTemplate } from '../../../shared/lib/fillTemplate';
import { useI18n } from '../../../shared/lib/i18n';
import type { TranslationKey } from '../../../shared/lib/i18n';

import { collectDocumentParagraphs } from './selectionAnchor';
import { suggestionFromRewrite, toReviseIssue } from './suggestionFactory';

let messageSeq = 0;

/** Module-level monotonic id: unique even when two messages land in the same millisecond. */
export function nextMessageId(prefix = 'msg'): string {
  messageSeq += 1;
  return `${prefix}-${Date.now()}-${messageSeq}`;
}

/** i18n key of the user bubble that echoes a rewrite action. */
const REWRITE_ACTION_LABEL: Record<AiRewriteInstruction, TranslationKey> = {
  rewrite: 'office.ai.selection.rewrite',
  polish: 'office.ai.action.rewrite_polish',
  expand: 'office.ai.edit.expand',
  condense: 'office.ai.edit.condense',
  translate: 'office.ai.action.rewrite_translate',
  explain: 'office.ai.selection.rewrite',
  summarize: 'office.ai.action.rewrite_summarize',
  custom: 'office.ai.action.rewrite_custom',
};

export interface AiCapabilities {
  pending: boolean;
  errorText: string | null;
  runRewrite: (params: {
    instruction: AiRewriteInstruction;
    text: string;
    targetLang?: string;
    paraIndex?: number | null;
    customInstruction?: string;
  }) => Promise<void>;
  runChat: (message: string) => Promise<void>;
  applySuggestion: (messageId: string, suggestion: SuggestionCardData) => Promise<void>;
  markSkipped: (messageId: string, suggestionId: string) => void;
}

export function useAiCapabilities(deps: { rootRef: RefObject<HTMLElement> }): AiCapabilities {
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
    customInstruction?: string;
  }) => {
    if (!activeDocument) {
      appendMessage({
        id: nextMessageId(),
        role: 'system',
        content: t('office.ai.sidebar.no_document'),
        createdAt: Date.now(),
      });
      return;
    }

    setPending(true);
    setErrorText(null);

    // Echo the action as a user bubble so the conversation is not blank while
    // the LLM reply is still in flight.
    appendMessage({
      id: nextMessageId('msg-user'),
      role: 'user',
      content: t(REWRITE_ACTION_LABEL[params.instruction]),
      createdAt: Date.now(),
    });

    try {
      const result = await aiApi.rewrite({
        workspacePath: activeDocument.workspace_path ?? '',
        documentId: activeDocument.id,
        text: params.text,
        instruction: params.instruction,
        ...(params.targetLang ? { targetLang: params.targetLang } : {}),
        ...(params.customInstruction ? { customInstruction: params.customInstruction } : {}),
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
        id: nextMessageId(),
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
        id: nextMessageId(),
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
        id: nextMessageId(),
        role: 'system',
        content: t('office.ai.sidebar.no_document'),
        createdAt: Date.now(),
      });
      return;
    }

    setPending(true);
    setErrorText(null);

    appendMessage({
      id: nextMessageId('msg-user'),
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
        id: nextMessageId('msg-assistant'),
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
        id: nextMessageId('msg-system'),
        role: 'system',
        content: errorMessage,
        createdAt: Date.now(),
      });
    } finally {
      setPending(false);
    }
  };

  const applySuggestion = async (messageId: string, suggestion: SuggestionCardData) => {
    if (!activeDocument) {
      appendMessage({
        id: nextMessageId(),
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
        doc_id: activeDocument.id,
        issues: [toReviseIssue(suggestion, t('office.ai.revise.default_message'))],
        add_comments: true,
      });

      updateSuggestionStatus(messageId, suggestion.id, 'applied');
      appendMessage({
        id: nextMessageId(),
        role: 'system',
        content: t('office.ai.sidebar.apply_done'),
        createdAt: Date.now(),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const errorMessage = fillTemplate(t('office.ai.sidebar.apply_failed'), { message });
      setErrorText(errorMessage);
      appendMessage({
        id: nextMessageId(),
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
