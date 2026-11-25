import { describe, expect, it } from 'vitest';

import { agentStateToPhase, agentStateToText } from '../../../shared/lib/agentStateMapping';

describe('plan_progress state 映射', () => {
  it('不进占位文本、不产生阶段指示', () => {
    expect(agentStateToText('plan_progress')).toBeNull();
    expect(agentStateToPhase('plan_progress')).toBeNull();
  });
});
