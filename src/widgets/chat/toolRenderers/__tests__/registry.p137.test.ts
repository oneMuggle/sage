import { describe, expect, it } from 'vitest';

import { evaluateToolRendererRegistryGovernanceAudit } from '../registry';

describe('evaluateToolRendererRegistryGovernanceAudit (Phase P137)', () => {
  it('validates clean tool renderer registry with default renderer', () => {
    const report = evaluateToolRendererRegistryGovernanceAudit({
      registeredToolNames: ['run_command', 'write_file', 'web_search'],
      hasDefaultRenderer: true,
      duplicateRegistrations: 0,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueToolCount).toBe(3);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty registry, missing default renderer, and duplicate tool names', () => {
    const report = evaluateToolRendererRegistryGovernanceAudit({
      registeredToolNames: [],
      hasDefaultRenderer: false,
      duplicateRegistrations: 2,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'TOOL_RENDERER_REGISTRY_EMPTY',
      'TOOL_RENDERER_DEFAULT_MISSING',
      'TOOL_RENDERER_DUPLICATE_REGISTRATION',
    ]);
  });
});
