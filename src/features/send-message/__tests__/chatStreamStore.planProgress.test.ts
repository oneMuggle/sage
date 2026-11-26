import { beforeEach, describe, expect, it } from 'vitest';

import { selectSessionSlots, useChatStreamStore } from '../chatStreamStore';

describe('chatStreamStore · planProgress', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('setPlanProgress 累积同一阶段', () => {
    const store = useChatStreamStore.getState();
    store.setPlanProgress('s1', {
      stage: 'scout',
      status: 'progress',
      kind: 'thinking',
      text: 'a',
    });
    store.setPlanProgress('s1', {
      stage: 'scout',
      status: 'done',
      kind: 'message',
      text: 'b',
    });
    const slots = selectSessionSlots(useChatStreamStore.getState(), 's1');
    expect(slots.planProgress).toHaveLength(1);
    expect(slots.planProgress?.[0].status).toBe('done');
    expect(slots.planProgress?.[0].lines.map((l) => l.text)).toEqual(['a', 'b']);
  });

  it('startStream 重置 planProgress 与 preflightPhase', () => {
    const store = useChatStreamStore.getState();
    store.setPlanProgress('s1', {
      stage: 'scout',
      status: 'started',
      kind: 'message',
      text: '',
    });
    store.setPreflightPhase('s1', 'scout');
    store.startStream('s1', 'm1');
    const slots = selectSessionSlots(useChatStreamStore.getState(), 's1');
    expect(slots.planProgress).toBeNull();
    expect(slots.preflightPhase).toBeNull();
  });
});
