import { describe, expect, it } from 'vitest';

import { evaluateCommandWidgetBarrelGovernanceAudit } from '../index';

describe('evaluateCommandWidgetBarrelGovernanceAudit (Phase P137)', () => {
  it('returns healthy report when command palette and command items are exported', () => {
    const report = evaluateCommandWidgetBarrelGovernanceAudit({
      exportedSymbolCount: 2,
      hasCommandPaletteExport: true,
      hasCommandItemsExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.completeExports).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty barrel and missing command exports', () => {
    const report = evaluateCommandWidgetBarrelGovernanceAudit({
      exportedSymbolCount: 0,
      hasCommandPaletteExport: false,
      hasCommandItemsExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'COMMAND_BARREL_EMPTY',
      'COMMAND_PALETTE_EXPORT_MISSING',
      'COMMAND_ITEMS_EXPORT_MISSING',
    ]);
  });
});
