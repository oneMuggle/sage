import { invoke } from './desktopInvoke';
import { handleApiError } from './utils';

export type AiRewriteInstruction =
  | 'rewrite'
  | 'polish'
  | 'expand'
  | 'condense'
  | 'translate'
  | 'explain'
  | 'summarize'
  | 'custom';

export interface AiRewriteRequest {
  workspacePath: string;
  documentId: string;
  text: string;
  instruction: AiRewriteInstruction;
  targetLang?: string;
  customInstruction?: string;
  contextBefore?: string;
  contextAfter?: string;
}

export interface AiRewriteResult {
  ok: boolean;
  result: string;
  model: string | null;
}

export interface AiChatHistoryItem {
  role: 'user' | 'assistant';
  content: string;
}

export interface AiChatRequest {
  workspacePath: string;
  documentId: string;
  message: string;
  history: AiChatHistoryItem[];
  documentContext?: string;
}

export interface AiChatResult {
  ok: boolean;
  reply: string;
  model: string | null;
}

export const aiApi = {
  async rewrite(req: AiRewriteRequest): Promise<AiRewriteResult> {
    try {
      return await invoke<AiRewriteResult>('office_ai_rewrite', { ...req });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async chat(req: AiChatRequest): Promise<AiChatResult> {
    try {
      return await invoke<AiChatResult>('office_ai_chat', { ...req });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
