// src/entities/question/__tests__/questionState.test.ts
import { beforeEach, describe, expect, it } from 'vitest';

import type { UserQuestion } from '../../../shared/api';
import {
  buildQuestionStateAuditJson,
  buildQuestionStateAuditSnapshot,
  useQuestionState,
} from '../questionState';

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

  it('same-session replace yields a new object; cross-session keeps displayed', () => {
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'a' }), 'sess-A');
    const first = useQuestionState.getState().currentQuestion;
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'b' }), 'sess-A');
    const replaced = useQuestionState.getState().currentQuestion;
    expect(replaced).not.toBe(first);
    expect(replaced?.request_id).toBe('b');
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'c' }), 'sess-B');
    expect(useQuestionState.getState().currentQuestion).toBe(replaced);
    expect(useQuestionState.getState().pendingBySession['sess-B'].request_id).toBe('c');
  });

  it('exports questionState audit snapshot and JSON helpers', () => {
    expect(buildQuestionStateAuditSnapshot()).toBe(
      'pending:0|req:none|options:0|multi:no|session:none',
    );
    expect(
      buildQuestionStateAuditSnapshot({
        pendingCount: 2,
        currentRequestId: 'q-1',
        optionCount: 3,
        multiSelect: true,
        currentSessionId: 'sess-A',
      }),
    ).toBe('pending:2|req:q-1|options:3|multi:yes|session:sess-A');

    const parsed = JSON.parse(
      buildQuestionStateAuditJson({
        pendingCount: 1,
        currentRequestId: 'q-2',
        optionCount: 2,
      }),
    );
    expect(parsed).toEqual({
      pendingCount: 1,
      currentRequestId: 'q-2',
      optionCount: 2,
      multiSelect: false,
      currentSessionId: 'none',
      snapshot: 'pending:1|req:q-2|options:2|multi:no|session:none',
    });
  });
});
