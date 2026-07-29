// src/entities/question/questionState.ts
import { create } from 'zustand';

import type { UserQuestion } from '../../shared/api';

/**
 * 用户提问状态 — M2 part B: AskUserQuestion。
 *
 * 后端 agent 循环在 ask_user_question 工具调用前发出
 * `state: 'ask_user_question'` 流事件（携带 UserQuestion 载荷），然后阻塞
 * 等待（最长 300s；超时 = 空应答，agent 带"用户未回答"软结果继续）。
 * 本 store 持有「当前待应答提问」，驱动 QuestionDialog 模态框的显示/隐藏。
 *
 * 状态转移:
 *   null ──setFromEvent()──▶ UserQuestion (对话框弹出)
 *     ▲                          │
 *     └──────── resolve() ───────┘ (提交/流结束/流错误)
 *
 * 与 permissionState 同构：同一时刻至多一个待应答提问（后端单 agent 循环
 * 串行卡点）；重复 setFromEvent 直接替换（后到者覆盖）。
 */
export interface QuestionState {
  /** 当前待应答提问；null 表示无挂起提问（对话框隐藏） */
  currentQuestion: UserQuestion | null;
  /** 流事件到达 → 弹出对话框（不可变替换，不 mutate 旧对象） */
  setFromEvent: (payload: UserQuestion) => void;
  /** 应答完成 / 流结束 / 流错误 → 关闭对话框 */
  resolve: () => void;
}

export const useQuestionState = create<QuestionState>((set) => ({
  currentQuestion: null,
  // 浅拷贝载荷：流事件对象来自 IPC 反序列化，复制一份避免调用方
  // 后续 mutate 同一引用造成 UI 与 store 不一致。
  setFromEvent: (payload) => set({ currentQuestion: { ...payload } }),
  resolve: () => set({ currentQuestion: null }),
}));
