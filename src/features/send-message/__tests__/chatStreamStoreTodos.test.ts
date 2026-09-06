import { beforeEach, describe, expect, it } from 'vitest';

import { selectSessionSlots, useChatStreamStore } from '../chatStreamStore';

const SESS = 'sess-1';

describe('chatStreamStore todos slice', () => {
  beforeEach(() => {
    useChatStreamStore.getState().resetAll();
  });

  it('setTodos stores full snapshot', () => {
    const todos = [{ content: '任务1', status: 'pending' as const }];
    useChatStreamStore.getState().setTodos(SESS, todos);
    expect(selectSessionSlots(useChatStreamStore.getState(), SESS).todos).toEqual(todos);
  });

  it('startStream resets todos', () => {
    useChatStreamStore.getState().setTodos(SESS, [{ content: 'x', status: 'pending' }]);
    useChatStreamStore.getState().startStream(SESS, 'm1');
    expect(selectSessionSlots(useChatStreamStore.getState(), SESS).todos).toEqual([]);
  });

  it('S2: startStream 只重置目标会话的 todos', () => {
    useChatStreamStore.getState().setTodos('sess-A', [{ content: 'A', status: 'pending' }]);
    useChatStreamStore.getState().startStream('sess-B', 'm1');
    expect(selectSessionSlots(useChatStreamStore.getState(), 'sess-A').todos).toHaveLength(1);
    expect(selectSessionSlots(useChatStreamStore.getState(), 'sess-B').todos).toEqual([]);
  });
});
