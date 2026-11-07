import { beforeEach, describe, expect, it } from 'vitest';

import type { OfficeDocumentSummary } from '../../../shared/api/types';
import { useOfficeWorkspaceStore } from '../officeWorkspaceStore';

const docA: OfficeDocumentSummary = {
  id: 'doc-a',
  doc_type: 'word',
  original_filename: 'a.docx',
  generated_filename: 'a.docx',
  status: 'parsed',
  created_at: 0,
  updated_at: 0,
  metadata: { file_size_bytes: 0 },
  derived_from: null,
  archived_at: null,
};

const docB: OfficeDocumentSummary = { ...docA, id: 'doc-b', original_filename: 'b.docx' };

const initialState = useOfficeWorkspaceStore.getState();

describe('officeWorkspaceStore', () => {
  beforeEach(() => {
    useOfficeWorkspaceStore.setState(initialState, true);
  });

  it('starts with an empty workspace', () => {
    const s = useOfficeWorkspaceStore.getState();
    expect(s.activeDocument).toBeNull();
    expect(s.previewMode).toBe('fidelity');
    expect(s.sidebarOpen).toBe(false);
    expect(s.conversation).toEqual([]);
    expect(s.selection).toBeNull();
    expect(s.generateMode).toBe('idle');
    expect(s.generatedDoc).toBeNull();
    expect(s.activeRuleGroups).toEqual([]);
  });

  it('resets conversation and selection when switching to a different document', () => {
    const s = useOfficeWorkspaceStore.getState();
    s.setActiveDocument(docA);
    s.appendMessage({ id: 'm1', role: 'user', content: 'hi', createdAt: 1 });
    s.setSelection({ text: 'x', anchorParaIndex: 0, focusParaIndex: 0, rawContext: 'x' });

    useOfficeWorkspaceStore.getState().setActiveDocument(docB);

    const next = useOfficeWorkspaceStore.getState();
    expect(next.activeDocument?.id).toBe('doc-b');
    expect(next.conversation).toEqual([]);
    expect(next.selection).toBeNull();
  });

  it('keeps conversation when re-setting the same document', () => {
    const s = useOfficeWorkspaceStore.getState();
    s.setActiveDocument(docA);
    s.appendMessage({ id: 'm1', role: 'user', content: 'hi', createdAt: 1 });

    useOfficeWorkspaceStore.getState().setActiveDocument({ ...docA });

    expect(useOfficeWorkspaceStore.getState().conversation).toHaveLength(1);
  });

  it('appends and patches messages immutably', () => {
    const s = useOfficeWorkspaceStore.getState();
    s.appendMessage({ id: 'm1', role: 'user', content: 'hi', createdAt: 1 });
    const before = useOfficeWorkspaceStore.getState().conversation;

    useOfficeWorkspaceStore.getState().updateMessage('m1', { content: 'hello' });

    const after = useOfficeWorkspaceStore.getState().conversation;
    expect(after).not.toBe(before);
    expect(after[0].content).toBe('hello');
  });

  it('updates a suggestion status inside its message', () => {
    const s = useOfficeWorkspaceStore.getState();
    s.appendMessage({
      id: 'm1',
      role: 'assistant',
      content: 'audit',
      createdAt: 1,
      attachments: [
        {
          id: 's1',
          paraIndex: 2,
          severity: 'warning',
          originalText: 'a',
          suggestedText: 'b',
          applied: 'pending',
        },
      ],
    });

    useOfficeWorkspaceStore.getState().updateSuggestionStatus('m1', 's1', 'applied');

    expect(useOfficeWorkspaceStore.getState().conversation[0].attachments?.[0].applied).toBe(
      'applied',
    );
  });

  it('resets the whole workspace', () => {
    const s = useOfficeWorkspaceStore.getState();
    s.setActiveDocument(docA);
    s.setSidebarOpen(true);
    useOfficeWorkspaceStore.getState().resetWorkspace();

    const next = useOfficeWorkspaceStore.getState();
    expect(next.activeDocument).toBeNull();
    expect(next.sidebarOpen).toBe(false);
  });
});
