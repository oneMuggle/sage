// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { PlaybookImportPreview } from '../../../shared/api/playbookApi';
import { PlaybookImportPreviewCard } from '../PlaybookImportPreviewCard';

const STAGE_DIFF = {
  label: '开题',
  changed_fields: [],
  artifacts_added: [{ id: 'dmp', label: '数据管理计划' }],
  artifacts_removed: [{ id: 'old_doc', label: '旧材料' }],
  artifacts_changed: [{ id: 'proposal_report', label: '开题报告', fields: ['match', 'required'] }],
  rules_added: ['导入规则：引用必须可核验'],
  rules_removed: ['旧规则'],
  milestones_added: ['完成伦理审批'],
  milestones_removed: [],
  criteria_added: [{ id: 'dmp_ready', label: '数据管理计划完成' }],
  criteria_removed: [],
  criteria_changed: [],
  has_changes: true,
};

function preview(
  stageDetails: Record<string, typeof STAGE_DIFF>,
  directoriesAdded: string[] = [],
): PlaybookImportPreview {
  return {
    playbook: { name: '科研课题规程', stages: [{}, {}, {}] } as never,
    scaffold: { include: true, directories: ['01_开题'], documents: [] },
    diff: {
      stages_added: [],
      stages_removed: [],
      stages_changed: Object.keys(stageDetails),
      directories_added: directoriesAdded,
      directories_removed: [],
      directories_changed: [],
      name_changed: false,
      description_changed: false,
      global_rules_added: [],
      global_rules_removed: [],
      stage_details: stageDetails,
    },
  };
}

function renderCard(value: PlaybookImportPreview) {
  render(
    <PlaybookImportPreviewCard
      preview={value}
      conflict="save_as_new"
      onConflictChange={vi.fn()}
      saveToLibrary={false}
      onSaveToLibraryChange={vi.fn()}
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
      importing={false}
    />,
  );
}

describe('PlaybookImportPreviewCard', () => {
  it('展示汇总计数与逐项阶段 diff', () => {
    renderCard(preview({ proposal: STAGE_DIFF }, ['05_附录']));
    expect(screen.getByText(/新增目录 1/)).toBeInTheDocument();
    expect(screen.getByTestId('playbook-diff-details')).toBeInTheDocument();
    expect(screen.getByTestId('playbook-diff-stage-proposal')).toBeInTheDocument();
    expect(screen.getByText('+ 产物：数据管理计划')).toBeInTheDocument();
    expect(screen.getByText('− 产物：旧材料')).toBeInTheDocument();
    expect(screen.getByText(/~ 产物：开题报告（match、required）/)).toBeInTheDocument();
    expect(screen.getByText('+ 规则：导入规则：引用必须可核验')).toBeInTheDocument();
    expect(screen.getByText('+ 里程碑：完成伦理审批')).toBeInTheDocument();
    expect(screen.getByText('+ 退出条件：数据管理计划完成')).toBeInTheDocument();
  });

  it('无变更时显示无结构变更且不渲染明细', () => {
    renderCard(preview({}));
    expect(screen.getByText('变更：无结构变更')).toBeInTheDocument();
    expect(screen.queryByTestId('playbook-diff-details')).not.toBeInTheDocument();
  });
});
