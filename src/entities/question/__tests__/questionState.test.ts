// src/entities/question/__tests__/questionState.test.ts
import { beforeEach, describe, expect, it } from 'vitest';

import type { UserQuestion } from '../../../shared/api';
import { useQuestionState } from '../questionState';

function makeQuestion(overrides: Partial<UserQuestion> = {}): UserQuestion {
  return {
    request_id: 'q-1',
    question: '选择输出格式?',
    header: '输出格式',
    options: [
      { label: 'Markdown', description: '纯文本报告' },
      { label: 'PDF', description: null },
    ],
    multi_select: false,
    created_at: 1753718400.123,
    ...overrides,
  };
}

describe('useQuestionState', () => {
  beforeEach(() => {
    useQuestionState.setState({ currentQuestion: null, pendingBySession: {} });
  });

  it('initial state: no pending question', () => {
    expect(useQuestionState.getState().currentQuestion).toBeNull();
  });

  it('setFromEvent() stores the question (dialog trigger)', () => {
    const q = makeQuestion();
    useQuestionState.getState().setFromEvent(q);
    expect(useQuestionState.getState().currentQuestion).toEqual(q);
  });

  it('setFromEvent() copies the payload (caller mutation must not leak)', () => {
    const q = makeQuestion();
    useQuestionState.getState().setFromEvent(q);
    // 模拟 IPC 层复用/篡改载荷对象
    q.question = 'mutated';
    expect(useQuestionState.getState().currentQuestion?.question).toBe('选择输出格式?');
  });

  it('setFromEvent() keeps displayed question; later ones queue per session (2026-09 修复)', () => {
    // 同 permissionState —— 后到者不覆盖已展示的提问, 按会话归档。
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'q-1' }), 'sess-A');
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'q-2' }), 'sess-B');
    expect(useQuestionState.getState().currentQuestion?.request_id).toBe('q-1');
    expect(Object.keys(useQuestionState.getState().pendingBySession)).toHaveLength(2);
    useQuestionState.getState().resolve('sess-A');
    expect(useQuestionState.getState().currentQuestion?.request_id).toBe('q-2');
  });

  it('resolve() clears the question (dialog close)', () => {
    useQuestionState.getState().setFromEvent(makeQuestion());
    useQuestionState.getState().resolve();
    expect(useQuestionState.getState().currentQuestion).toBeNull();
  });

  it('resolve() is idempotent on empty state', () => {
    useQuestionState.getState().resolve();
    expect(useQuestionState.getState().currentQuestion).toBeNull();
  });

  it('updates immutably: setFromEvent produces a new object per session slot', () => {
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'a' }));
    const first = useQuestionState.getState().currentQuestion;
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'b' }));
    expect(useQuestionState.getState().currentQuestion).toBe(first);
    const second = useQuestionState.getState().pendingBySession['__global__'];
    expect(second.request_id).toBe('b');
    expect(second).not.toBe(first);
  });
});
