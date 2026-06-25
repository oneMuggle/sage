// src/entities/chat/btwState.ts
import { create } from 'zustand';

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
  open: (question: string) => void;
  close: () => void;
  appendDelta: (delta: string) => void;
  setLoading: (v: boolean) => void;
}

const initial = {
  isOpen: false,
  question: '',
  answer: '',
  isLoading: false,
  parentTaskRunning: false,
};

export const useBtwState = create<BtwState>((set) => ({
  ...initial,
  open: (question) => set({ isOpen: true, question, answer: '', isLoading: true }),
  close: () => set({ ...initial }),
  appendDelta: (delta) =>
    set((prev) => ({ ...prev, answer: prev.answer + delta, isLoading: false })),
  setLoading: (v) => set({ isLoading: v }),
}));
