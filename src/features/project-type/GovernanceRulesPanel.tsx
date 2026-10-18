/**
 * GovernanceRulesPanel — 合并"AI 约束规则"与"跨目录白名单"为一个治理 Tab。
 *
 * 语义上两者都属于"AI 行为规则"：前者约束 AI 在该项目中的操作模式，
 * 后者定义 AI 可访问的跨目录只读路径。垂直堆叠两节，用分隔线区隔。
 *
 * Created 2026-10-18 as part of Scheme 4 (merge governance tabs).
 */

import type { ProjectType } from '../../shared/api';

import { ConstraintManager } from './ConstraintManager';
import { StudioAllowedPathsTabPanel } from './StudioMaterialsAndProfilePanels';

export interface GovernanceRulesPanelProps {
  projectId: string;
  projectPath: string;
  projectType: ProjectType;
  allowedPaths: string[];
  newAllowedPath: string;
  onNewAllowedPathChange: (value: string) => void;
  savingPaths: boolean;
  onAddAllowedPath: () => void;
  onQuickAddPresetPath: (pattern: string) => void;
  onRemoveAllowedPath: (path: string) => void;
}

export function GovernanceRulesPanel({
  projectId,
  projectPath,
  projectType,
  allowedPaths,
  newAllowedPath,
  onNewAllowedPathChange,
  savingPaths,
  onAddAllowedPath,
  onQuickAddPresetPath,
  onRemoveAllowedPath,
}: GovernanceRulesPanelProps) {
  return (
    <div className="space-y-6" data-testid="governance-rules-panel">
      {/* Section 1: AI 行为约束规则 */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-primary/10 text-primary text-xs font-bold">
            1
          </span>
          AI 行为约束规则
        </h3>
        <ConstraintManager projectId={projectId} projectType={projectType} />
      </div>

      {/* 分隔线 */}
      <div className="border-t border-border" />

      {/* Section 2: 跨目录只读白名单 */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-primary/10 text-primary text-xs font-bold">
            2
          </span>
          跨目录只读白名单
        </h3>
        <StudioAllowedPathsTabPanel
          projectPath={projectPath}
          projectType={projectType}
          allowedPaths={allowedPaths}
          newAllowedPath={newAllowedPath}
          onNewAllowedPathChange={onNewAllowedPathChange}
          savingPaths={savingPaths}
          onAddAllowedPath={onAddAllowedPath}
          onQuickAddPresetPath={onQuickAddPresetPath}
          onRemoveAllowedPath={onRemoveAllowedPath}
        />
      </div>
    </div>
  );
}
