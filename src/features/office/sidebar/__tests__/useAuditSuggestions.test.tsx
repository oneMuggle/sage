import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useOfficeWorkspaceStore } from '../../../../entities/office/officeWorkspaceStore';
import * as officeSpecApi from '../../../../shared/api/officeSpecApi';
import type { AiReviewResult } from '../../../../shared/api/officeSpecTypes';
import { useAuditSuggestions } from '../useAuditSuggestions';

vi.mock('../../../../shared/api/officeSpecApi', () => ({
  officeSpecApi: {
    runAiReview: vi.fn(),
    reviseAiIssues: vi.fn(),
  },
}));

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, string>) => {
      if (params) return `${key}:${JSON.stringify(params)}`;
      return key;
    },
    locale: 'zh',
    setLocale: vi.fn(),
  }),
}));

const mockOfficeSpecApi = vi.mocked(officeSpecApi.officeSpecApi);

const doc = {
  id: 'doc-123',
  workspace_path: '/workspace',
  generated_filename: 'audit.docx',
  doc_type: 'word',
} as never;

function makeIssue(
  overrides: Partial<{
    id: string;
    fixable: boolean;
    actual: string | null;
    expected: string | null;
    suggestion: string;
    severity: 'error' | 'warning' | 'info';
    paragraph_index: number | null;
    message: string;
  }>,
): Record<string, unknown> {
  const actual = overrides.actual === undefined ? 'Original' : overrides.actual;
  const expected = overrides.expected === undefined ? 'Fixed' : overrides.expected;
  return {
    id: overrides.id ?? 'i-1',
    severity: overrides.severity ?? 'warning',
    category: 'style',
    message: overrides.message ?? 'Fix this',
    suggestion: overrides.suggestion ?? 'Fixed',
    rationale: 'rationale',
    expected,
    actual,
    fixable: overrides.fixable ?? true,
    location: {
      paragraph_index: overrides.paragraph_index ?? 0,
      paragraph_text: actual,
    },
    source: { kind: 'llm', spec_id: null, spec_name: null, rule_id: null, rule_pack_id: null },
  };
}

function auditResult(issues: Array<Record<string, unknown>>): AiReviewResult {
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
    issues: issues as never,
    warnings: [],
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

  it('calls officeSpecApi.runAiReview with derived paths and appends an assistant message', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: doc });
    mockOfficeSpecApi.runAiReview.mockResolvedValue(
      auditResult([
        makeIssue({ id: 'i-1', actual: 'Original', expected: 'Fixed', paragraph_index: 3 }),
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

  it('filters out unfixable and empty suggestions', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: doc });
    mockOfficeSpecApi.runAiReview.mockResolvedValue(
      auditResult([
        makeIssue({ id: 'a', fixable: false, actual: 'X', expected: 'Y' }),
        makeIssue({ id: 'b', fixable: true, actual: null, expected: 'Y' }),
        makeIssue({ id: 'c', fixable: true, actual: 'X', expected: null }),
        makeIssue({ id: 'd', fixable: true, actual: 'X', expected: 'Y', paragraph_index: 2 }),
      ]),
    );

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.runAudit();
    });

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages[0].attachments).toHaveLength(1);
    expect(messages[0].attachments?.[0].id).toBe('au-d');
  });

  it('surfaces a system error when runAiReview rejects', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: doc });
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

  it('skips reviseAiIssues when no pending cards remain', async () => {
    useOfficeWorkspaceStore.setState({
      activeDocument: doc,
      conversation: [
        {
          id: 'msg-1',
          role: 'assistant',
          content: 'audit',
          createdAt: 1,
          attachments: [
            {
              id: 'au-a',
              paraIndex: 0,
              severity: 'warning' as const,
              originalText: 'X',
              suggestedText: 'Y',
              applied: 'applied' as const,
            },
          ],
        },
      ],
    });

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.applyAll('msg-1');
    });

    expect(mockOfficeSpecApi.reviseAiIssues).not.toHaveBeenCalled();
  });

  it('applyAll sends a batched revise and marks each card applied', async () => {
    useOfficeWorkspaceStore.setState({
      activeDocument: doc,
      conversation: [
        {
          id: 'msg-1',
          role: 'assistant',
          content: 'audit',
          createdAt: 1,
          attachments: [
            {
              id: 'au-a',
              paraIndex: 0,
              severity: 'warning' as const,
              originalText: 'A',
              suggestedText: 'B',
              applied: 'pending' as const,
              ruleName: 'R1',
            },
            {
              id: 'au-b',
              paraIndex: 2,
              severity: 'info' as const,
              originalText: 'C',
              suggestedText: 'D',
              applied: 'pending' as const,
            },
            {
              id: 'au-c',
              paraIndex: 4,
              severity: 'warning' as const,
              originalText: 'E',
              suggestedText: 'F',
              applied: 'skipped' as const,
            },
          ],
        },
      ],
    });

    mockOfficeSpecApi.reviseAiIssues.mockResolvedValue({
      ok: true,
      doc_id: 'doc-123',
      snapshot_path: null,
      source_path: '/workspace/audit.docx',
      output_path: '/workspace/audit.docx',
      overwritten: true,
      planned: 2,
      applied: 2,
      skipped: [],
      changes: [],
      warnings: [],
    } as never);

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
    expect(call.issues[0].message).toBe('R1');
    expect(call.issues[1].message).toBe('office.ai.revise.default_message');
    expect(call.add_comments).toBe(true);

    const state = useOfficeWorkspaceStore.getState();
    const attachments = state.conversation[0].attachments ?? [];
    expect(attachments[0].applied).toBe('applied');
    expect(attachments[1].applied).toBe('applied');
    expect(attachments[2].applied).toBe('skipped');

    expect(state.conversation[1].role).toBe('system');
    expect(state.conversation[1].content).toBe('office.ai.sidebar.apply_done');
  });

  it('applyAll surfaces a system message on failure', async () => {
    useOfficeWorkspaceStore.setState({
      activeDocument: doc,
      conversation: [
        {
          id: 'msg-1',
          role: 'assistant',
          content: 'audit',
          createdAt: 1,
          attachments: [
            {
              id: 'au-a',
              paraIndex: 0,
              severity: 'warning' as const,
              originalText: 'A',
              suggestedText: 'B',
              applied: 'pending' as const,
            },
          ],
        },
      ],
    });
    mockOfficeSpecApi.reviseAiIssues.mockRejectedValue(new Error('network'));

    const { result } = renderHook(() => useAuditSuggestions());

    await act(async () => {
      await result.current.applyAll('msg-1');
    });

    expect(useOfficeWorkspaceStore.getState().conversation[1].content).toContain(
      'office.ai.sidebar.apply_failed',
    );
  });
});
