/**
 * Model Catalog widget barrel (Task 6, 2026-09-15)
 *
 * 导出 CatalogTable / ModelDetails / SnapshotReview。
 * 调用方 (ModelCatalog 页面) 通过 import { ... } from '../../widgets/model-catalog' 取用。
 */
export { CatalogTable, catalogItemKey } from './CatalogTable';
export { ModelDetails } from './ModelDetails';
export { SnapshotReview } from './SnapshotReview';

export interface ModelCatalogBarrelAuditInput {
  exportedSymbols: string[];
  hasCatalogTableExport: boolean;
  hasModelDetailsExport: boolean;
  hasSnapshotReviewExport: boolean;
}

export interface ModelCatalogBarrelAuditReport {
  uniqueSymbolCount: number;
  completeCatalogExports: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateModelCatalogBarrelGovernanceAudit(
  input: ModelCatalogBarrelAuditInput,
): ModelCatalogBarrelAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.exportedSymbols
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
  const uniqueSymbolCount = new Set(normalized).size;
  if (uniqueSymbolCount < 3) {
    issueCodes.push('MODEL_CATALOG_BARREL_SYMBOLS_LOW');
  }
  const completeCatalogExports =
    input.hasCatalogTableExport && input.hasModelDetailsExport && input.hasSnapshotReviewExport;
  if (!completeCatalogExports) {
    issueCodes.push('MODEL_CATALOG_CORE_EXPORT_MISSING');
  }
  return {
    uniqueSymbolCount,
    completeCatalogExports,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
