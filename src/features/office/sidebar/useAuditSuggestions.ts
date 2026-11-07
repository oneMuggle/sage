import { useState } from 'react';
import type { RefObject } from 'react';

import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';
import type { SuggestionCardData } from '../../../entities/office/officeWorkspaceStore';
import { officeSpecApi } from '../../../shared/api/officeSpecApi';
import type { AiReviewIssue } from '../../../shared/api/officeSpecTypes';
import { fillTemplate } from '../../../shared/lib/fillTemplate';
import { useI18n } from '../../../shared/lib/i18n';
import { joinWorkspacePath } from '../latexPath';

import { toReviseIssue } from './suggestionFactory';
import { nextMessageId } from './useAiCapabilities';

export interface AuditSuggestionsApi {
  running: boolean;
  /** Triggers a full-document audit and appends an assistant message with cards. */
  runAudit: () => Promise<void>;
  /** Applies every `pending` card on the message with the given id in a single batch. */
  applyAll: (messageId: string) => Promise<void>;
}

export interface AuditSuggestionsDeps {
  /** Optional document-canvas ref. Currently unused but reserved for future scope selection. */
  rootRef?: RefObject<HTMLElement>;
}

export function useAuditSuggestions(_deps: AuditSuggestionsDeps = {}): AuditSuggestionsApi {
  const { t } = useI18n();
  const [running, setRunning] = useState(false);

  const activeDocument = useOfficeWorkspaceStore((s) => s.activeDocument);
  const conversation = useOfficeWorkspaceStore((s) => s.conversation);
  const appendMessage = useOfficeWorkspaceStore((s) => s.appendMessage);
  const updateSuggestionStatus = useOfficeWorkspaceStore((s) => s.updateSuggestionStatus);

  const derivePaths = (): { workspacePath: string; filePath: string; docId: string } | null => {
    if (!activeDocument) return null;
    const workspacePath = activeDocument.workspace_path ?? '';
    const filePath = joinWorkspacePath(workspacePath, activeDocument.generated_filename);
    if (!filePath) return null;
    return { workspacePath, filePath, docId: activeDocument.id };
  };

  const runAudit = async () => {
    if (!activeDocument) {
      appendMessage({
        id: nextMessageId(),
        role: 'system',
        content: t('office.ai.sidebar.no_document'),
        createdAt: Date.now(),
      });
      return;
    }
    const paths = derivePaths();
    if (!paths) {
      appendMessage({
        id: nextMessageId(),
        role: 'system',
        content: t('office.ai.sidebar.apply_disabled'),
        createdAt: Date.now(),
      });
      return;
    }

    setRunning(true);
    try {
      const result = await officeSpecApi.runAiReview({
        workspace_path: paths.workspacePath,
        file_path: paths.filePath,
        doc_id: paths.docId,
        use_llm: true,
      });

      const cards: SuggestionCardData[] = result.issues
        .filter((issue) => issue.fixable && issue.actual != null && issue.expected != null)
        .map((issue) => issueToCard(issue));

      appendMessage({
        id: nextMessageId(),
        role: 'assistant',
        content: t('office.ai.audit.title'),
        attachments: cards,
        createdAt: Date.now(),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      appendMessage({
        id: nextMessageId(),
        role: 'system',
        content: fillTemplate(t('office.ai.sidebar.request_failed'), { message }),
        createdAt: Date.now(),
      });
    } finally {
      setRunning(false);
    }
  };

  const applyAll = async (messageId: string) => {
    const paths = derivePaths();
    if (!paths) {
      appendMessage({
        id: nextMessageId(),
        role: 'system',
        content: t('office.ai.sidebar.apply_disabled'),
        createdAt: Date.now(),
      });
      return;
    }

    const message = conversation.find((m) => m.id === messageId);
    const pending: SuggestionCardData[] = (message?.attachments ?? []).filter(
      (attachment) => attachment.applied === 'pending',
    );
    if (pending.length === 0) return;

    setRunning(true);
    try {
      await officeSpecApi.reviseAiIssues({
        workspace_path: paths.workspacePath,
        file_path: paths.filePath,
        doc_id: paths.docId,
        issues: pending.map((suggestion) =>
          toReviseIssue(suggestion, t('office.ai.revise.default_message')),
        ),
        add_comments: true,
      });
      for (const suggestion of pending) {
        updateSuggestionStatus(messageId, suggestion.id, 'applied');
      }
      appendMessage({
        id: nextMessageId(),
        role: 'system',
        content: t('office.ai.sidebar.apply_done'),
        createdAt: Date.now(),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      appendMessage({
        id: nextMessageId(),
        role: 'system',
        content: fillTemplate(t('office.ai.sidebar.apply_failed'), { message }),
        createdAt: Date.now(),
      });
    } finally {
      setRunning(false);
    }
  };

  return { running, runAudit, applyAll };
}

function issueToCard(issue: AiReviewIssue): SuggestionCardData {
  const actual = issue.actual ?? '';
  const suggested = issue.expected ?? issue.suggestion ?? '';
  return {
    id: `au-${issue.id}`,
    paraIndex: issue.location?.paragraph_index ?? -1,
    severity: issue.severity,
    originalText: actual,
    suggestedText: suggested,
    ...(issue.message ? { ruleName: issue.message } : {}),
    applied: 'pending',
  };
}
