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
    useQuestionState.setState({ currentQuestion: null });
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

  it('setFromEvent() replaces an in-flight question (后到者覆盖)', () => {
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'q-1' }));
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'q-2' }));
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

  it('updates immutably: setState produces a new question object reference', () => {
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'a' }));
    const first = useQuestionState.getState().currentQuestion;
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'b' }));
    const second = useQuestionState.getState().currentQuestion;
    expect(second).not.toBe(first);
  });
});
