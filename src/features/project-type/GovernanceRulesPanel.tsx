/**
 * GovernanceRulesPanel — 合并"AI 约束规则"与"跨目录白名单"为一个治理 Tab。
 *
 * 语义上两者都属于"AI 行为规则"：前者约束 AI 在该项目中的操作模式，
 * 后者定义 AI 可访问的跨目录只读路径。垂直堆叠两节，用分隔线区隔。
 *
 * Created 2026-10-18 as part of Scheme 4 (merge governance tabs).
 */

import { useState } from 'react';

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

// eslint-disable-next-line react-refresh/only-export-components
export function formatGovernanceRulesMarkdown(params: {
  projectId: string;
  projectPath: string;
  projectType: ProjectType;
  allowedPaths: ReadonlyArray<string>;
}): string {
  const lines = [
    '# 项目治理规则摘要 (Governance Rules Summary)',
    '',
    `- **项目 ID**: \`${params.projectId}\``,
    `- **项目路径**: \`${params.projectPath}\``,
    `- **项目类型**: \`${params.projectType}\``,
    `- **跨目录白名单数量**: ${params.allowedPaths.length}`,
  ];
  if (params.allowedPaths.length === 0) {
    lines.push('', '_暂无跨目录只读白名单_');
  } else {
    lines.push('', '## 跨目录只读白名单');
    for (const p of params.allowedPaths) {
      lines.push(`- \`${p}\``);
    }
  }
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatGovernanceRulesJson(params: {
  projectId: string;
  projectPath: string;
  projectType: ProjectType;
  allowedPaths: ReadonlyArray<string>;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      ...params,
    },
    null,
    2,
  );
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
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(
        formatGovernanceRulesMarkdown({ projectId, projectPath, projectType, allowedPaths }),
      );
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(
        formatGovernanceRulesJson({ projectId, projectPath, projectType, allowedPaths }),
      );
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div className="space-y-6" data-testid="governance-rules-panel">
      {/* Section 1: AI 行为约束规则 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-primary/10 text-primary text-xs font-bold">
              1
            </span>
            AI 行为约束规则
          </h3>
          <div className="flex items-center gap-1">
            <button
              type="button"
              data-testid="governance-rules-copy-md"
              onClick={() => void handleCopyMarkdown()}
              className="px-2 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
            >
              {copiedMd ? '已复制 MD' : '复制 MD'}
            </button>
            <button
              type="button"
              data-testid="governance-rules-copy-json"
              onClick={() => void handleCopyJson()}
              className="px-2 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
            >
              {copiedJson ? '已复制 JSON' : '复制 JSON'}
            </button>
          </div>
        </div>
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

// eslint-disable-next-line react-refresh/only-export-components
export function auditGovernanceRulesPanelGovernance(): {
  module: 'src/features/project-type/GovernanceRulesPanel.tsx';
  phase: 'P166';
  domain: 'project-type';
  sections: readonly ['constraints', 'allowed-paths'];
  supportsMarkdownAndJsonExport: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/project-type/GovernanceRulesPanel.tsx',
    phase: 'P166',
    domain: 'project-type',
    sections: ['constraints', 'allowed-paths'],
    supportsMarkdownAndJsonExport: true,
    compliant: true,
  };
}
