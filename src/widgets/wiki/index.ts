/**
 * Wiki Widgets - LLM Wiki workspace UI components
 */
export { WikiChat } from './WikiChat';
export { WikiEditor } from './WikiEditor';
export { WikiFileTree } from './WikiFileTree';
export { WikiGraphView } from './WikiGraphView';
export { WikiInsightsPanel } from './WikiInsightsPanel';
export { WikiQueuePanel } from './WikiQueuePanel';
export { WikiLintView } from './WikiLintView';
export { WikiReviewView } from './WikiReviewView';
export { WikiResearchPanel } from './WikiResearchPanel';
export { CommunityColoredGraph } from './CommunityColoredGraph';
export { WikiProjectPicker } from './WikiProjectPicker';
export { WikiSearch } from './WikiSearch';
export { WikiToolbar } from './WikiToolbar';
export { WikiIngestProgress } from './WikiIngestProgress';
export { MarkdownPreview } from './MarkdownPreview';

// New components (参考 llm_wiki)
export { IconSidebar } from './IconSidebar';
export { LeftPanel } from './LeftPanel';
export { RightPanel } from './RightPanel';
export { LintItemCard } from './LintItemCard';
export { ReviewItemCard } from './ReviewItemCard';
export { SourcesView } from './SourcesView';
export { SourcesTree } from './SourcesTree';
export { ActivityPanel } from './ActivityPanel';

export interface WikiBarrelAuditInput {
  exportedComponentNames: string[];
  hasWikiEditorExport: boolean;
  hasWikiGraphViewExport: boolean;
  hasWikiSearchExport: boolean;
}

export interface WikiBarrelAuditReport {
  uniqueExportCount: number;
  completeCoreWikiExports: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateWikiBarrelGovernanceAudit(
  input: WikiBarrelAuditInput,
): WikiBarrelAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.exportedComponentNames
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
  const uniqueExportCount = new Set(normalized).size;
  if (uniqueExportCount < 10) {
    issueCodes.push('WIKI_BARREL_EXPORTS_INCOMPLETE');
  }
  const completeCoreWikiExports =
    input.hasWikiEditorExport && input.hasWikiGraphViewExport && input.hasWikiSearchExport;
  if (!completeCoreWikiExports) {
    issueCodes.push('WIKI_CORE_EXPORT_MISSING');
  }
  return {
    uniqueExportCount,
    completeCoreWikiExports,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
