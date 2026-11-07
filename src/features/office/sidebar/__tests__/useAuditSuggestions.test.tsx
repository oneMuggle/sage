import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  useOfficeWorkspaceStore,
  type ConversationMessage,
} from '../../../../entities/office/officeWorkspaceStore';
import * as officeSpecApi from '../../../../shared/api/officeSpecApi';
import type {
  AiReviewIssue,
  AiReviewResult,
  AiReviseResult,
} from '../../../../shared/api/officeSpecTypes';
import type { OfficeDocumentSummary } from '../../../../shared/api/types';
import { useAuditSuggestions } from '../useAuditSuggestions';

vi.mock('../../../../shared/api/officeSpecApi', () => ({
  officeSpecApi: {
    runAiReview: vi.fn(),
    reviseAiIssues: vi.fn(),
  },
}));

// Templates keep the i18n key plus the placeholder so `fillTemplate` can be
// asserted end-to-end without hardcoding product copy.
const { TEMPLATES } = vi.hoisted(() => ({
  TEMPLATES: {
    'office.ai.audit.apply_skipped': 'office.ai.audit.apply_skipped:{count}',
    'office.ai.sidebar.request_failed': 'office.ai.sidebar.request_failed:{message}',
    'office.ai.sidebar.apply_failed': 'office.ai.sidebar.apply_failed:{message}',
  } as Record<string, string>,
}));

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => TEMPLATES[key] ?? key,
    locale: 'zh',
    setLocale: vi.fn(),
  }),
}));

const mockOfficeSpecApi = vi.mocked(officeSpecApi.officeSpecApi);

const baseDoc: OfficeDocumentSummary = {
  id: 'doc-123',
  workspace_path: '/workspace',
  generated_filename: 'audit.docx',
  doc_type: 'word',
  original_filename: 'audit.docx',
  status: 'parsed',
  created_at: 0,
  updated_at: 0,
  metadata: { file_size_bytes: 0 },
  derived_from: null,
  archived_at: null,
};

function makeIssue(overrides: Partial<AiReviewIssue> = {}): AiReviewIssue {
  const actual = overrides.actual === undefined ? 'Original' : overrides.actual;
  const expected = overrides.expected === undefined ? 'Fixed' : overrides.expected;
  return {
    id: overrides.id ?? 'i-1',
    severity: overrides.severity ?? 'warning',
    category: 'style',
    message: overrides.message ?? 'Fix this',
    suggestion: overrides.suggestion ?? 'Fixed',
    rationale: 'rationale',
    actual,
    expected,
    fixable: overrides.fixable ?? true,
    location:
      overrides.location === undefined
        ? { paragraph_index: 0, paragraph_text: actual }
        : overrides.location,
    source: { kind: 'llm', spec_id: null, spec_name: null, rule_id: null, rule_pack_id: null },
  };
}

function auditResult(issues: AiReviewIssue[]): AiReviewResult {
  return {
    ok: true,
    doc_id: 'doc-123',
    file_path: '/workspace/audit.docx',
    scope: 'full',
    spec_id: null,
    spec_name: null,
    summary: {
      rules_checked: 0,
      issue_count: issues.length,
      error_count: 0,
      warning_count: issues.length,
      info_count: 0,
      spec_issue_count: 0,
      llm_issue_count: issues.length,
      duration_ms: 0,
      model: null,
      prompt_tokens: null,
      completion_tokens: null,
    },
    issues,
    warnings: [],
  };
}

function reviseResult(overrides: Partial<AiReviseResult> = {}): AiReviseResult {
  return {
    ok: true,
    doc_id: 'doc-123',
    snapshot_path: null,
    source_path: '/workspace/audit.docx',
    output_path: '/workspace/audit.docx',
    overwritten: true,
    planned: 0,
    applied: 0,
    skipped: 0,
    changes: [],
    warnings: [],
    ...overrides,
  };
}

function seedConversation(message: ConversationMessage): void {
  useOfficeWorkspaceStore.setState({
    activeDocument: baseDoc,
    conversation: [message],
  });
}

function pendingMessage(...ids: string[]): ConversationMessage {
  return {
    id: 'msg-1',
    role: 'assistant',
    content: 'audit',
    createdAt: 1,
    attachments: ids.map((id, index) => ({
      id,
      paraIndex: index,
      severity: 'warning' as const,
      originalText: `old-${id}`,
      suggestedText: `new-${id}`,
      applied: 'pending' as const,
    })),
  };
}

describe('useAuditSuggestions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOfficeWorkspaceStore.setState({
      activeDocument: null,
      conversation: [],
      selection: null,
    });
  });

  it('writes a system error when no activeDocument on runAudit', async () => {
    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.runAudit();
    });

    expect(mockOfficeSpecApi.runAiReview).not.toHaveBeenCalled();
    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe('system');
    expect(messages[0].content).toBe('office.ai.sidebar.no_document');
  });

  it('calls runAiReview with derived paths and appends an assistant message', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: baseDoc });
    mockOfficeSpecApi.runAiReview.mockResolvedValue(
      auditResult([
        makeIssue({ id: 'i-1', location: { paragraph_index: 3, paragraph_text: 'O' } }),
      ]),
    );

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.runAudit();
    });

    expect(mockOfficeSpecApi.runAiReview).toHaveBeenCalledWith({
      workspace_path: '/workspace',
      file_path: '/workspace/audit.docx',
      doc_id: 'doc-123',
      use_llm: true,
      max_issues: 50,
    });

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe('assistant');
    expect(messages[0].content).toBe('office.ai.audit.title');
    expect(messages[0].attachments).toHaveLength(1);
    expect(messages[0].attachments?.[0].paraIndex).toBe(3);
    expect(messages[0].attachments?.[0].originalText).toBe('Original');
    expect(messages[0].attachments?.[0].suggestedText).toBe('Fixed');
    expect(messages[0].attachments?.[0].applied).toBe('pending');
  });

  it('filters out issues that cannot be applied as literal replacements', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: baseDoc });
    mockOfficeSpecApi.runAiReview.mockResolvedValue(
      auditResult([
        makeIssue({ id: 'unfixable', fixable: false }),
        makeIssue({ id: 'no-actual', actual: null }),
        makeIssue({ id: 'no-expected', expected: null }),
        // R23: empty strings are not usable replacement text.
        makeIssue({ id: 'empty-actual', actual: '' }),
        makeIssue({ id: 'empty-expected', expected: '' }),
        // R23: `suggestion` maps to `fix_hint` (backend/office/ai_review.py:159) —
        // it is advice, never the literal replacement, so it cannot stand in
        // for a missing `expected`.
        makeIssue({ id: 'hint-only', expected: null, suggestion: 'Add a citation' }),
        // R23: a missing or negative paragraph index makes reviseAiIssues 422.
        makeIssue({ id: 'null-location', location: null }),
        makeIssue({ id: 'null-index', location: { paragraph_index: null, paragraph_text: 'X' } }),
        makeIssue({ id: 'negative-index', location: { paragraph_index: -1, paragraph_text: 'X' } }),
        makeIssue({ id: 'ok', location: { paragraph_index: 2, paragraph_text: 'X' } }),
      ]),
    );

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.runAudit();
    });

    const attachments = useOfficeWorkspaceStore.getState().conversation[0].attachments ?? [];
    expect(attachments).toHaveLength(1);
    expect(attachments[0].id).toBe('au-ok');
  });

  it('surfaces a system error when runAiReview rejects', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: baseDoc });
    mockOfficeSpecApi.runAiReview.mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.runAudit();
    });

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe('system');
    expect(messages[0].content).toContain('office.ai.sidebar.request_failed');
  });

  it('ignores a second runAudit while one request is in flight', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: baseDoc });
    mockOfficeSpecApi.runAiReview.mockResolvedValue(auditResult([]));

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await Promise.all([result.current.runAudit(), result.current.runAudit()]);
    });

    expect(mockOfficeSpecApi.runAiReview).toHaveBeenCalledTimes(1);
  });

  it('writes apply_disabled when workspace_path is empty', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: { ...baseDoc, workspace_path: '' } });

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.runAudit();
    });

    expect(mockOfficeSpecApi.runAiReview).not.toHaveBeenCalled();
    expect(useOfficeWorkspaceStore.getState().conversation[0].content).toBe(
      'office.ai.sidebar.apply_disabled',
    );
  });

  it('writes apply_disabled when generated_filename is empty', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: { ...baseDoc, generated_filename: '' } });

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.runAudit();
    });

    expect(mockOfficeSpecApi.runAiReview).not.toHaveBeenCalled();
    expect(useOfficeWorkspaceStore.getState().conversation[0].content).toBe(
      'office.ai.sidebar.apply_disabled',
    );
  });

  it('writes apply_disabled when applyAll has no derivable path', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: null });

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.applyAll('msg-1');
    });

    expect(mockOfficeSpecApi.reviseAiIssues).not.toHaveBeenCalled();
    expect(useOfficeWorkspaceStore.getState().conversation[0].content).toBe(
      'office.ai.sidebar.apply_disabled',
    );
  });

  it('skips reviseAiIssues when no pending cards remain', async () => {
    seedConversation({
      ...pendingMessage('au-a'),
      attachments: [{ ...pendingMessage('au-a').attachments![0], applied: 'applied' }],
    });

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.applyAll('msg-1');
    });

    expect(mockOfficeSpecApi.reviseAiIssues).not.toHaveBeenCalled();
  });

  it('applyAll sends a batched revise and marks each card applied', async () => {
    seedConversation(pendingMessage('au-a', 'au-b', 'au-c'));
    useOfficeWorkspaceStore.setState((state) => ({
      conversation: state.conversation.map((message) => ({
        ...message,
        attachments: message.attachments?.map((card) =>
          card.id === 'au-c' ? { ...card, applied: 'skipped' } : card,
        ),
      })),
    }));
    mockOfficeSpecApi.reviseAiIssues.mockResolvedValue(reviseResult({ planned: 2, applied: 2 }));

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.applyAll('msg-1');
    });

    expect(mockOfficeSpecApi.reviseAiIssues).toHaveBeenCalledTimes(1);
    const call = mockOfficeSpecApi.reviseAiIssues.mock.calls[0][0];
    expect(call.workspace_path).toBe('/workspace');
    expect(call.file_path).toBe('/workspace/audit.docx');
    expect(call.doc_id).toBe('doc-123');
    expect(call.issues).toHaveLength(2);
    expect(call.issues[0].message).toBe('office.ai.revise.default_message');
    expect(call.add_comments).toBe(true);

    const state = useOfficeWorkspaceStore.getState();
    const attachments = state.conversation[0].attachments ?? [];
    expect(attachments[0].applied).toBe('applied');
    expect(attachments[1].applied).toBe('applied');
    expect(attachments[2].applied).toBe('skipped');

    expect(state.conversation[1].role).toBe('system');
    expect(state.conversation[1].content).toBe('office.ai.sidebar.apply_done');
  });

  it('applyAll keeps skipped cards pending and reports the skipped count', async () => {
    seedConversation(pendingMessage('au-a', 'au-b'));
    mockOfficeSpecApi.reviseAiIssues.mockResolvedValue(
      reviseResult({
        planned: 2,
        applied: 1,
        skipped: 1,
        changes: [
          {
            rule_id: null,
            find: 'old-au-a',
            replace: 'new-au-a',
            comment: '',
            applied: true,
            reason: '',
          },
          {
            rule_id: null,
            find: 'old-au-b',
            replace: 'new-au-b',
            comment: '',
            applied: false,
            reason: 'text not found',
          },
        ],
      }),
    );

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.applyAll('msg-1');
    });

    const state = useOfficeWorkspaceStore.getState();
    const attachments = state.conversation[0].attachments ?? [];
    expect(attachments[0].applied).toBe('applied');
    expect(attachments[1].applied).toBe('pending');
    expect(state.conversation[1].content).toBe('office.ai.audit.apply_skipped:1');
  });

  it('applyAll surfaces a system message on failure and leaves cards pending', async () => {
    seedConversation(pendingMessage('au-a'));
    mockOfficeSpecApi.reviseAiIssues.mockRejectedValue(new Error('network'));

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.applyAll('msg-1');
    });

    const state = useOfficeWorkspaceStore.getState();
    expect(state.conversation[1].content).toContain('office.ai.sidebar.apply_failed');
    expect(state.conversation[0].attachments?.[0].applied).toBe('pending');
  });

  it('matches cards to changes by order when two cards share the same suggestedText', async () => {
    // Two cards with identical suggestedText. Backend applied one and skipped one.
    seedConversation({
      id: 'msg-dup',
      role: 'assistant',
      content: 'audit',
      createdAt: 1,
      attachments: [
        {
          id: 'au-first',
          paraIndex: 0,
          severity: 'warning',
          originalText: 'old-first',
          suggestedText: 'shared-replacement',
          applied: 'pending',
        },
        {
          id: 'au-second',
          paraIndex: 1,
          severity: 'warning',
          originalText: 'old-second',
          suggestedText: 'shared-replacement',
          applied: 'pending',
        },
      ],
    });
    mockOfficeSpecApi.reviseAiIssues.mockResolvedValue(
      reviseResult({
        planned: 2,
        applied: 1,
        skipped: 1,
        changes: [
          {
            rule_id: null,
            find: 'old-first',
            replace: 'shared-replacement',
            comment: '',
            applied: true,
            reason: '',
          },
          {
            rule_id: null,
            find: 'old-second',
            replace: 'shared-replacement',
            comment: '',
            applied: false,
            reason: 'text not found',
          },
        ],
      }),
    );

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.applyAll('msg-dup');
    });

    const attachments = useOfficeWorkspaceStore.getState().conversation[0].attachments ?? [];
    // Exactly one card is applied, one stays pending — not both applied.
    expect(attachments[0].applied).toBe('applied');
    expect(attachments[1].applied).toBe('pending');
  });
});
