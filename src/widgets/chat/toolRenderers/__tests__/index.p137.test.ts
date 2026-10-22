import { describe, expect, it } from 'vitest';

import { evaluateToolRenderersBarrelGovernanceAudit } from '../index';

describe('evaluateToolRenderersBarrelGovernanceAudit (Phase P137)', () => {
  it('returns healthy report when all tool renderer barrel exports are present', () => {
    const report = evaluateToolRenderersBarrelGovernanceAudit({
      exportedRendererCount: 4,
      hasRegistryExport: true,
      hasFallbackCardExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.completeExports).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags missing renderer exports and registry/fallback exports', () => {
    const report = evaluateToolRenderersBarrelGovernanceAudit({
      exportedRendererCount: 1,
      hasRegistryExport: false,
      hasFallbackCardExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'TOOL_RENDERERS_BARREL_COUNT_LOW',
      'TOOL_RENDERERS_REGISTRY_EXPORT_MISSING',
      'TOOL_RENDERERS_FALLBACK_CARD_MISSING',
    ]);
  });
});
