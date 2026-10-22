// src/entities/chat/btwState.ts
import { create } from 'zustand';

import type { MessageSource } from '../../shared/api/types';

/**
 * Btw 状态机 — 与 spec Phase 6 一致
 *
 * 状态转移 (由 useBtwCommand 驱动):
 *   idle ──open()──▶ loading ──appendDelta()──▶ answered
 *                      │                         │
 *                      ├──setLoading(false)──▶ error
 *                      │                         │
 *                      └──close()──▶ idle (任何状态)
 *
 * 多 /btw 互斥: 第二次 open() 自动替换 question 并清空 answer,
 * 旧流由 useBtwCommand 负责取消
 */
export interface BtwState {
  isOpen: boolean;
  question: string;
  answer: string;
  isLoading: boolean;
  parentTaskRunning: boolean;
  /** R92: sources_used 事件带来的统一参考来源（/btw 走同一 /chat/stream 管道） */
  sources: MessageSource[];
  open: (question: string) => void;
  close: () => void;
  appendDelta: (delta: string) => void;
  setLoading: (v: boolean) => void;
  setSources: (sources: MessageSource[]) => void;
}

const initial = {
  isOpen: false,
  question: '',
  answer: '',
  isLoading: false,
  parentTaskRunning: false,
  sources: [] as MessageSource[],
};

export const useBtwState = create<BtwState>((set) => ({
  ...initial,
  open: (question) =>
    set({ isOpen: true, question, answer: '', isLoading: true, sources: [] }),
  close: () => set({ ...initial }),
  appendDelta: (delta) =>
    set((prev) => ({ ...prev, answer: prev.answer + delta, isLoading: false })),
  setLoading: (v) => set({ isLoading: v }),
  setSources: (sources) => set({ sources }),
}));

export interface BtwStateAuditInput {
  isOpen?: boolean;
  hasQuestion?: boolean;
  answerLength?: number;
  isLoading?: boolean;
  parentTaskRunning?: boolean;
  sourceCount?: number;
}

export function buildBtwStateAuditSnapshot(input: BtwStateAuditInput = {}): string {
  const isOpen = Boolean(input.isOpen);
  const hasQuestion = Boolean(input.hasQuestion);
  const answerLength = Math.max(0, input.answerLength ?? 0);
  const isLoading = Boolean(input.isLoading);
  const parentTaskRunning = Boolean(input.parentTaskRunning);
  const sourceCount = Math.max(0, input.sourceCount ?? 0);
  return `open:${isOpen ? 'yes' : 'no'}|question:${hasQuestion ? 'yes' : 'no'}|answerLen:${answerLength}|loading:${isLoading ? 'yes' : 'no'}|parentRunning:${parentTaskRunning ? 'yes' : 'no'}|sources:${sourceCount}`;
}

export function buildBtwStateAuditJson(input: BtwStateAuditInput = {}): string {
  const isOpen = Boolean(input.isOpen);
  const hasQuestion = Boolean(input.hasQuestion);
  const answerLength = Math.max(0, input.answerLength ?? 0);
  const isLoading = Boolean(input.isLoading);
  const parentTaskRunning = Boolean(input.parentTaskRunning);
  const sourceCount = Math.max(0, input.sourceCount ?? 0);
  return JSON.stringify({
    isOpen,
    hasQuestion,
    answerLength,
    isLoading,
    parentTaskRunning,
    sourceCount,
    snapshot: buildBtwStateAuditSnapshot(input),
  });
}

export function auditBtwStateGovernance(
  state: {
    isOpen?: boolean;
    messageCount?: number;
  } = {},
): {
  module: 'src/entities/chat/btwState.ts';
  phase: 'P153';
  isOpen: boolean;
  messageCount: number;
  healthy: boolean;
} {
  const isOpen = state.isOpen === true;
  const messageCount =
    typeof state.messageCount === 'number' && Number.isFinite(state.messageCount)
      ? Math.max(0, Math.trunc(state.messageCount))
      : 0;
  return {
    module: 'src/entities/chat/btwState.ts',
    phase: 'P153',
    isOpen,
    messageCount,
    healthy: messageCount >= 0 && messageCount <= 500,
  };
}
