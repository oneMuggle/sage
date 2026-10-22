export { ToolCallCard, inferToolStatus } from './ToolCallCard';
export type { ToolStatus } from './ToolCallCard';
export { BashToolRenderer } from './BashToolRenderer';
export { FileWriteToolRenderer, isFileWriteTool } from './FileWriteToolRenderer';
export { WebSearchToolRenderer } from './WebSearchToolRenderer';
export { resolveToolRenderer } from './registry';
export type { ToolRenderer, ToolRendererProps } from './registry';

export interface ToolRenderersBarrelAuditInput {
  exportedRendererCount: number;
  hasRegistryExport: boolean;
  hasFallbackCardExport: boolean;
}

export interface ToolRenderersBarrelAuditReport {
  exportedRendererCount: number;
  completeExports: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateToolRenderersBarrelGovernanceAudit(
  input: ToolRenderersBarrelAuditInput,
): ToolRenderersBarrelAuditReport {
  const issueCodes: string[] = [];
  const exportedRendererCount = Math.max(0, Math.trunc(input.exportedRendererCount));
  if (exportedRendererCount < 3) {
    issueCodes.push('TOOL_RENDERERS_BARREL_COUNT_LOW');
  }
  if (!input.hasRegistryExport) {
    issueCodes.push('TOOL_RENDERERS_REGISTRY_EXPORT_MISSING');
  }
  if (!input.hasFallbackCardExport) {
    issueCodes.push('TOOL_RENDERERS_FALLBACK_CARD_MISSING');
  }
  return {
    exportedRendererCount,
    completeExports: input.hasRegistryExport && input.hasFallbackCardExport,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
