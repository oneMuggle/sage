import { describe, expect, it } from 'vitest';

import {
  auditLlmStreamGovernance,
  formatAgentEventJson,
  formatAgentEventSummary,
} from '../llmStream';

describe('llmStream P176 governance audit', () => {
  it('audits llmStream governance contract and agent event formatters', () => {
    const raw = auditLlmStreamGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.llm_stream.governance.v1');
    expect(parsed.phase).toBe('P176');
    expect(parsed.supportsNdjson).toBe(true);
    expect(formatAgentEventSummary({ state: 'done', run_id: 'r1', task_id: 't1' })).toBe(
      'done · run=r1 · task=t1',
    );
    expect(JSON.parse(formatAgentEventJson({ state: 'done', run_id: 'r1' })).state).toBe('done');
  });
});
