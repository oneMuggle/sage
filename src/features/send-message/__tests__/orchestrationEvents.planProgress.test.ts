import { beforeEach, describe, expect, it } from 'vitest';

import { applyOrchestrationEventToBoard } from '../orchestrationEvents';
import { useChatStreamStore } from '../chatStreamStore';

describe('applyOrchestrationEventToBoard · plan_progress', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('plan_progress 写入槽位并消费事件', () => {
    const handled = applyOrchestrationEventToBoard(
      {
        state: 'plan_progress',
        iteration: 0,
        plan_progress: {
          stage: 'mode_classify',
          status: 'started',
          kind: 'message',
          text: '',
        },
      },
      's1',
    );
    expect(handled).toBe(true);
    const slots = useChatStreamStore.getState().sessions['s1'];
    expect(slots?.planProgress?.[0].stage).toBe('mode_classify');
  });

  it('orch_preflight 兼容后端 phase 字段', () => {
    const handled = applyOrchestrationEventToBoard(
      { state: 'orch_preflight', iteration: 0, phase: 'scout_deep' },
      's1',
    );
    expect(handled).toBe(true);
    expect(useChatStreamStore.getState().sessions['s1']?.preflightPhase).toBe('scout_deep');
  });

  it('缺载荷时不消费事件', () => {
    const handled = applyOrchestrationEventToBoard({ state: 'plan_progress', iteration: 0 }, 's1');
    expect(handled).toBe(false);
  });
});
