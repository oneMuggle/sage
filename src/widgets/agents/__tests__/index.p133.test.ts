import { describe, expect, it } from 'vitest';

import {
  auditAgentsWidgetBarrel,
  exportAgentsWidgetBarrelAuditJson,
} from '../index';

describe('agents widget barrel audit diagnostics', () => {
  it('audits exported symbols of src/widgets/agents/index.ts', () => {
    const report = auditAgentsWidgetBarrel();
    expect(report.schemaVersion).toBe('1.0');
    expect(report.module).toBe('src/widgets/agents/index.ts');
    expect(report.symbolCount).toBe(3);
    expect(report.exportedSymbols).toEqual(['AgentCard', 'AgentDetails', 'EditAgentForm']);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportAgentsWidgetBarrelAuditJson());
    expect(parsed.symbolCount).toBe(3);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
