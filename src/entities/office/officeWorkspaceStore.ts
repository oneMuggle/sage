import { create } from 'zustand';

import type { AiReviewSeverity } from '../../shared/api/officeSpecTypes';
import type { OfficeDocumentSummary } from '../../shared/api/types';

export type PreviewMode = 'fidelity' | 'structured';
export type GenerateMode = 'idle' | 'nl' | 'refs' | 'template' | 'iterate';
export type SuggestionStatus = 'pending' | 'applied' | 'skipped';

export interface SelectionState {
  text: string;
  anchorParaIndex: number | null;
  focusParaIndex: number | null;
  rawContext: string;
}

export interface SuggestionCardData {
  id: string;
  paraIndex: number;
  severity: AiReviewSeverity;
  originalText: string;
  suggestedText: string;
  ruleName?: string;
  applied: SuggestionStatus;
}

export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  attachments?: SuggestionCardData[];
  createdAt: number;
}

export interface OfficeWorkspaceState {
  activeDocument: OfficeDocumentSummary | null;
  previewMode: PreviewMode;
  fidelityFailed: boolean;
  sidebarOpen: boolean;
  conversation: ConversationMessage[];
  selection: SelectionState | null;
  generateMode: GenerateMode;
  generatedDoc: OfficeDocumentSummary | null;
  activeRuleGroups: string[];
  setActiveDocument: (doc: OfficeDocumentSummary | null) => void;
  setPreviewMode: (mode: PreviewMode) => void;
  setFidelityFailed: (failed: boolean) => void;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  appendMessage: (message: ConversationMessage) => void;
  updateMessage: (id: string, patch: Partial<Omit<ConversationMessage, 'id'>>) => void;
  clearConversation: () => void;
  setSelection: (selection: SelectionState | null) => void;
  setGenerateMode: (mode: GenerateMode) => void;
  setGeneratedDoc: (doc: OfficeDocumentSummary | null) => void;
  setActiveRuleGroups: (groups: string[]) => void;
  updateSuggestionStatus: (
    messageId: string,
    suggestionId: string,
    status: SuggestionStatus,
  ) => void;
  resetWorkspace: () => void;
}

const EMPTY = {
  activeDocument: null,
  previewMode: 'fidelity' as PreviewMode,
  fidelityFailed: false,
  sidebarOpen: false,
  conversation: [] as ConversationMessage[],
  selection: null,
  generateMode: 'idle' as GenerateMode,
  generatedDoc: null,
  activeRuleGroups: [] as string[],
};

export const useOfficeWorkspaceStore = create<OfficeWorkspaceState>((set, get) => ({
  ...EMPTY,

  setActiveDocument: (doc) => {
    const currentId = get().activeDocument?.id ?? null;
    const nextId = doc?.id ?? null;
    if (currentId === nextId) {
      set({ activeDocument: doc });
      return;
    }
    set({ activeDocument: doc, conversation: [], selection: null });
  },

  setPreviewMode: (previewMode) => set({ previewMode }),
  setFidelityFailed: (fidelityFailed) => set({ fidelityFailed }),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  appendMessage: (message) => set((s) => ({ conversation: [...s.conversation, message] })),

  updateMessage: (id, patch) =>
    set((s) => ({
      conversation: s.conversation.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),

  clearConversation: () => set({ conversation: [] }),
  setSelection: (selection) => set({ selection }),
  setGenerateMode: (generateMode) => set({ generateMode }),
  setGeneratedDoc: (generatedDoc) => set({ generatedDoc }),
  setActiveRuleGroups: (activeRuleGroups) => set({ activeRuleGroups }),

  updateSuggestionStatus: (messageId, suggestionId, status) =>
    set((s) => ({
      conversation: s.conversation.map((m) =>
        m.id !== messageId || !m.attachments
          ? m
          : {
              ...m,
              attachments: m.attachments.map((a) =>
                a.id === suggestionId ? { ...a, applied: status } : a,
              ),
            },
      ),
    })),

  resetWorkspace: () => set({ ...EMPTY }),
}));
