import { useRef, useState } from 'react';
import type { RefObject } from 'react';

import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';
import type { SuggestionCardData } from '../../../entities/office/officeWorkspaceStore';
import { officeSpecApi } from '../../../shared/api/officeSpecApi';
import type { AiReviewIssue, AiReviseResult } from '../../../shared/api/officeSpecTypes';
import { fillTemplate } from '../../../shared/lib/fillTemplate';
import { useI18n } from '../../../shared/lib/i18n';

import { toReviseIssue } from './suggestionFactory';
import { nextMessageId } from './useAiCapabilities';

const MAX_AUDIT_ISSUES = 50;

/** R23: `expected` is the literal replacement text; `suggestion` is only a hint. */
type FixableIssue = AiReviewIssue & {
  actual: string;
  expected: string;
  location: { paragraph_index: number; paragraph_text: string | null };
};

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
  // M4: ref-based guard so a second call cannot slip through the stale `running` state.
  const inFlightRef = useRef(false);

  const activeDocument = useOfficeWorkspaceStore((s) => s.activeDocument);
  const conversation = useOfficeWorkspaceStore((s) => s.conversation);
  const appendMessage = useOfficeWorkspaceStore((s) => s.appendMessage);
  const updateSuggestionStatus = useOfficeWorkspaceStore((s) => s.updateSuggestionStatus);

  const appendSystem = (content: string) => {
    appendMessage({ id: nextMessageId(), role: 'system', content, createdAt: Date.now() });
  };

  const deriveTarget = (): { workspacePath: string; docId: string } | null => {
    if (!activeDocument) return null;
    const workspacePath = activeDocument.workspace_path ?? '';
    if (!workspacePath.trim()) return null;
    return { workspacePath, docId: activeDocument.id };
  };

  const runAudit = async () => {
    if (inFlightRef.current) return;
    if (!activeDocument) {
      appendSystem(t('office.ai.sidebar.no_document'));
      return;
    }
    const target = deriveTarget();
    if (!target) {
      appendSystem(t('office.ai.sidebar.apply_disabled'));
      return;
    }

    inFlightRef.current = true;
    setRunning(true);
    // Echo the action as a user bubble so the conversation shows the request
    // immediately, not only once the audit result lands.
    appendMessage({
      id: nextMessageId('msg-user'),
      role: 'user',
      content: t('office.ai.action.audit_full'),
      createdAt: Date.now(),
    });
    try {
      const result = await officeSpecApi.runAiReview({
        workspace_path: target.workspacePath,
        doc_id: target.docId,
        use_llm: true,
        max_issues: MAX_AUDIT_ISSUES,
      });
      appendMessage({
        id: nextMessageId(),
        role: 'assistant',
        content: t('office.ai.audit.title'),
        attachments: buildCards(result.issues),
        createdAt: Date.now(),
      });
    } catch (error) {
      appendSystem(
        fillTemplate(t('office.ai.sidebar.request_failed'), { message: errorMessage(error) }),
      );
    } finally {
      inFlightRef.current = false;
      setRunning(false);
    }
  };

  const applyReviseResult = (
    result: AiReviseResult,
    pending: SuggestionCardData[],
    messageId: string,
  ) => {
    if (result.skipped === 0) {
      for (const suggestion of pending) {
        updateSuggestionStatus(messageId, suggestion.id, 'applied');
      }
      appendSystem(t('office.ai.sidebar.apply_done'));
      return;
    }
    // R24: only cards whose replacement actually landed may be marked applied.
    // Use ordered pairing to handle duplicate suggestedText correctly: each card
    // consumes the earliest unmatched applied change with matching replace text.
    const claimed = new Set<number>();
    for (const suggestion of pending) {
      const matchIndex = result.changes.findIndex(
        (change, index) =>
          !claimed.has(index) && change.applied && change.replace === suggestion.suggestedText,
      );
      if (matchIndex >= 0) {
        claimed.add(matchIndex);
        updateSuggestionStatus(messageId, suggestion.id, 'applied');
      }
    }
    appendSystem(
      fillTemplate(t('office.ai.audit.apply_skipped'), { count: String(result.skipped) }),
    );
  };

  const applyAll = async (messageId: string) => {
    if (inFlightRef.current) return;
    const target = deriveTarget();
    if (!target) {
      appendSystem(t('office.ai.sidebar.apply_disabled'));
      return;
    }

    const message = conversation.find((m) => m.id === messageId);
    const pending = (message?.attachments ?? []).filter((card) => card.applied === 'pending');
    if (pending.length === 0) return;

    inFlightRef.current = true;
    setRunning(true);
    appendMessage({
      id: nextMessageId('msg-user'),
      role: 'user',
      content: t('office.ai.action.apply_all'),
      createdAt: Date.now(),
    });
    try {
      const result = await officeSpecApi.reviseAiIssues({
        workspace_path: target.workspacePath,
        doc_id: target.docId,
        issues: pending.map((suggestion) =>
          toReviseIssue(suggestion, t('office.ai.revise.default_message')),
        ),
        add_comments: true,
      });
      applyReviseResult(result, pending, messageId);
    } catch (error) {
      appendSystem(
        fillTemplate(t('office.ai.sidebar.apply_failed'), { message: errorMessage(error) }),
      );
    } finally {
      inFlightRef.current = false;
      setRunning(false);
    }
  };

  return { running, runAudit, applyAll };
}

function buildCards(issues: AiReviewIssue[]): SuggestionCardData[] {
  return issues.filter(isFixableIssue).map(issueToCard);
}

/**
 * R23: keep `expected` strictly (empty strings are rejected) and require a
 * non-negative paragraph index — `-1` would make the whole revise batch 422.
 */
function isFixableIssue(issue: AiReviewIssue): issue is FixableIssue {
  const index = issue.location?.paragraph_index;
  return (
    issue.fixable &&
    Boolean(issue.actual) &&
    Boolean(issue.expected) &&
    typeof index === 'number' &&
    index >= 0
  );
}

function issueToCard(issue: FixableIssue): SuggestionCardData {
  return {
    id: `au-${issue.id}`,
    paraIndex: issue.location.paragraph_index,
    severity: issue.severity,
    originalText: issue.actual,
    suggestedText: issue.expected,
    ...(issue.message ? { ruleName: issue.message } : {}),
    applied: 'pending',
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
