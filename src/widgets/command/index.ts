export { CommandPalette } from './CommandPalette';

export interface CommandWidgetBarrelAuditInput {
  exportedSymbolCount: number;
  hasCommandPaletteExport: boolean;
  hasCommandItemsExport: boolean;
}

export interface CommandWidgetBarrelAuditReport {
  exportedSymbolCount: number;
  completeExports: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateCommandWidgetBarrelGovernanceAudit(
  input: CommandWidgetBarrelAuditInput,
): CommandWidgetBarrelAuditReport {
  const issueCodes: string[] = [];
  const exportedSymbolCount = Math.max(0, Math.trunc(input.exportedSymbolCount));
  if (exportedSymbolCount === 0) {
    issueCodes.push('COMMAND_BARREL_EMPTY');
  }
  if (!input.hasCommandPaletteExport) {
    issueCodes.push('COMMAND_PALETTE_EXPORT_MISSING');
  }
  if (!input.hasCommandItemsExport) {
    issueCodes.push('COMMAND_ITEMS_EXPORT_MISSING');
  }
  return {
    exportedSymbolCount,
    completeExports: input.hasCommandPaletteExport && input.hasCommandItemsExport,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
