/**
 * 项目类型分类系统组件导出 (2026-09-25；多形态项目工作台扩展 2026-10-10)
 */

export {
  ARCHETYPE_BLUEPRINTS,
  ARCHETYPE_ORDER,
  getArchetypeBlueprint,
} from './archetypeBlueprints';
export type {
  ArchetypeBlueprintMeta,
  ArchetypeStageMeta,
  ArchetypeTemplateMeta,
} from './archetypeBlueprints';

export { ProjectTypeBadge } from './ProjectTypeBadge';
export type { ProjectTypeBadgeProps } from './ProjectTypeBadge';

export { ProjectTypeSelector } from './ProjectTypeSelector';
export type { ProjectTypeSelectorProps } from './ProjectTypeSelector';

export { TypeDetectionPreview } from './TypeDetectionPreview';
export type { TypeDetectionPreviewProps } from './TypeDetectionPreview';

export { ProjectCreationWizard } from './ProjectCreationWizard';
export type { ProjectCreationWizardProps } from './ProjectCreationWizard';

export { GitStatusWidget } from './GitStatusWidget';
export type { GitStatusWidgetProps } from './GitStatusWidget';

export { ConstraintSummaryWidget } from './ConstraintSummaryWidget';
export type { ConstraintSummaryWidgetProps } from './ConstraintSummaryWidget';

export { MilestoneProgressWidget } from './MilestoneProgressWidget';
export type { MilestoneProgressWidgetProps } from './MilestoneProgressWidget';

export { ProjectOverviewWidgets } from './ProjectOverviewWidgets';
export type { ProjectOverviewWidgetsProps } from './ProjectOverviewWidgets';

export { ConstraintManager } from './ConstraintManager';
export type { ConstraintManagerProps } from './ConstraintManager';

export { ConstraintEditor } from './ConstraintEditor';
export type { ConstraintEditorProps } from './ConstraintEditor';

export { MilestoneManager } from './MilestoneManager';
export type { MilestoneManagerProps } from './MilestoneManager';

export { MilestoneEditor } from './MilestoneEditor';
export type { MilestoneEditorProps } from './MilestoneEditor';

export { TaskDecomposeDialog } from './TaskDecomposeDialog';
export type { TaskDecomposeDialogProps } from './TaskDecomposeDialog';

export { KnowledgeExtractionPanel } from './KnowledgeExtractionPanel';
export type { KnowledgeExtractionPanelProps } from './KnowledgeExtractionPanel';

export { ProjectAdvisorCard } from './ProjectAdvisorCard';
export type { ProjectAdvisorCardProps } from './ProjectAdvisorCard';

export { WikiGenerationPanel } from './WikiGenerationPanel';
export type { WikiGenerationPanelProps } from './WikiGenerationPanel';

export { SemanticSearchPanel } from './SemanticSearchPanel';
export type { SemanticSearchPanelProps } from './SemanticSearchPanel';

export { ProjectArchetypeStudio } from './ProjectArchetypeStudio';
export type { ProjectArchetypeStudioProps } from './ProjectArchetypeStudio';

export { PolymorphicArchetypeCards } from './PolymorphicArchetypeCards';
export type { PolymorphicArchetypeCardsProps } from './PolymorphicArchetypeCards';
