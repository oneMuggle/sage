import { describe, expect, it } from 'vitest';

import { evaluateModelCatalogBarrelGovernanceAudit } from '../index';

describe('evaluateModelCatalogBarrelGovernanceAudit (Phase P138)', () => {
  it('returns healthy report when all model catalog barrel exports are present', () => {
    const report = evaluateModelCatalogBarrelGovernanceAudit({
      exportedSymbols: ['CatalogTable', 'catalogItemKey', 'ModelDetails', 'SnapshotReview'],
      hasCatalogTableExport: true,
      hasModelDetailsExport: true,
      hasSnapshotReviewExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueSymbolCount).toBe(4);
    expect(report.completeCatalogExports).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags low symbol count and missing model catalog core exports', () => {
    const report = evaluateModelCatalogBarrelGovernanceAudit({
      exportedSymbols: ['CatalogTable'],
      hasCatalogTableExport: true,
      hasModelDetailsExport: false,
      hasSnapshotReviewExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'MODEL_CATALOG_BARREL_SYMBOLS_LOW',
      'MODEL_CATALOG_CORE_EXPORT_MISSING',
    ]);
  });
});
