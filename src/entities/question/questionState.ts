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
 *
 * S4 (2026-09-06) 多会话并行：请求记录归属会话（session_id），侧边栏
 * 据此按会话聚合"待应答"注意力点；resolve(sessionId) 定向清除 ——
 * 会话 A 的流结束不能误关会话 B 的提问对话框。无参 resolve() 保留
 * QuestionDialog 等旧调用方的全清语义。
 */
export type PendingUserQuestion = UserQuestion & { /** 事件来源会话（S4） */ session_id?: string };

export interface QuestionState {
  /** 按会话归档的挂起请求 (2026-09 修复: 并行会话互不覆盖) */
  pendingBySession: Record<string, PendingUserQuestion>;
  /** 当前待待应答提问；null 表示无挂起提问（对话框隐藏） */
  currentQuestion: PendingUserQuestion | null;
  /** 流事件到达 → 弹出对话框（不可变替换，不 mutate 旧对象）；sessionId 记录归属 */
  setFromEvent: (payload: UserQuestion, sessionId?: string) => void;
  /** 应答完成 / 流结束 / 流错误 → 关闭对话框；传 sessionId 时仅清除该会话的提问 */
  resolve: (sessionId?: string) => void;
}

function pickDisplayedQuestion(
  pending: Record<string, PendingUserQuestion>,
): PendingUserQuestion | null {
  const list = Object.values(pending);
  return list.length > 0 ? list[0] : null;
}

export const useQuestionState = create<QuestionState>((set) => ({
  currentQuestion: null,
  pendingBySession: {},
  // 浅拷贝载荷：流事件对象来自 IPC 反序列化，复制一份避免调用方
  // 后续 mutate 同一引用造成 UI 与 store 不一致。
  setFromEvent: (payload, sessionId) =>
    set((prev) => {
      const question: PendingUserQuestion = { ...payload, session_id: sessionId };
      // 2026-09 修复: 同 permissionState —— 按会话归档, 后到者不顶掉已展示的
      const key = sessionId ?? '__global__';
      const pending = { ...prev.pendingBySession, [key]: question };
      const currentQuestion = prev.currentQuestion ?? pickDisplayedQuestion(pending);
      return { pendingBySession: pending, currentQuestion };
    }),
  resolve: (sessionId) =>
    set((prev) => {
      // 未指定会话 = 全清（QuestionDialog 提交后调用）
      if (sessionId == null) return { currentQuestion: null, pendingBySession: {} };
      const pending: Record<string, PendingUserQuestion> = {};
      let removedDisplayed = false;
      for (const [k, q] of Object.entries(prev.pendingBySession)) {
        if (q.session_id === sessionId) {
          if (prev.currentQuestion === q) removedDisplayed = true;
          continue;
        }
        pending[k] = q;
      }
      if (!removedDisplayed) return { pendingBySession: pending };
      return { pendingBySession: pending, currentQuestion: pickDisplayedQuestion(pending) };
    }),
}));
