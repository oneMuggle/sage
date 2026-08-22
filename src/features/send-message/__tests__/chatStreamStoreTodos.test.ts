import { beforeEach, describe, expect, it } from 'vitest';

import { useChatStreamStore } from '../chatStreamStore';

describe('chatStreamStore todos slice', () => {
  beforeEach(() => {
    useChatStreamStore.getState().resetAll();
  });

  it('setTodos stores full snapshot', () => {
    const todos = [{ content: '任务1', status: 'pending' as const }];
    useChatStreamStore.getState().setTodos(todos);
    expect(useChatStreamStore.getState().todos).toEqual(todos);
  });

  it('startStream resets todos', () => {
    useChatStreamStore.getState().setTodos([{ content: 'x', status: 'pending' }]);
    useChatStreamStore.getState().startStream('m1');
    expect(useChatStreamStore.getState().todos).toEqual([]);
  });
});
