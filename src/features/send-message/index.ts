// src/features/send-message/index.ts
export { useChat } from './useChat';

/** btw 流式响应 payload (Phase 6) */
export interface BtwPayload {
  question: string;
  sessionId: string;
  onDelta: (delta: string) => void;
  onDone: () => void;
  onError: (err: Error) => void;
}
