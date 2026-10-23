import { describe, expect, it } from 'vitest';

import {
  auditActiveAgentIndicator,
  exportActiveAgentIndicatorAuditJson,
} from '../ActiveAgentIndicator';

describe('ActiveAgentIndicator audit diagnostics', () => {
  it('audits active agent and streaming state', () => {
    const def = auditActiveAgentIndicator();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/widgets/chat/ActiveAgentIndicator.tsx');
    expect(def.hasActiveAgent).toBe(true);
    expect(def.isStreaming).toBe(false);

    const idle = auditActiveAgentIndicator(null, true);
    expect(idle.hasActiveAgent).toBe(false);
    expect(idle.isStreaming).toBe(true);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportActiveAgentIndicatorAuditJson('Planner', true));
    expect(parsed.componentName).toBe('ActiveAgentIndicator');
    expect(parsed.isStreaming).toBe(true);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
