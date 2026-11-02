// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { PlaybookSpec } from '../../../shared/api/playbookApi';
import { PlaybookSpecEditor } from '../PlaybookSpecEditor';

const SPEC = {
  id: 'cn-research-grant',
  name: '科研课题规程',
  description: '开题—实施—结题',
  stages: [
    {
      id: 'proposal',
      label: '开题',
      order: 1,
      objective: '明确研究问题',
      artifacts: [
        {
          id: 'proposal_report',
          label: '开题报告',
          required: true,
          target_dir: '01_开题',
          match: { globs: ['**/开题报告*.md'], min_bytes: 0, min_count: 1 },
          content_checks: [],
        },
      ],
      exit_criteria: [
        {
          id: 'proposal_finalized',
          label: '开题报告已定稿',
          type: 'artifact',
          artifact_id: 'proposal_report',
        },
      ],
      rules: [
        {
          template_key: 'citation_strict',
          content: '引用必须可核验',
          category: 'academic',
          trigger_pattern: 'always',
          priority: 8,
        },
      ],
      recommended_milestones: [{ title: '完成初稿', description: '两周内' }],
    },
  ],
  directory_layout: [],
  global_rules: [],
  todos: [],
  ai_guidance: {},
  meta: {},
  applies_to: { project_types: [], sub_types: [] },
  schema_version: '1.0',
} as unknown as PlaybookSpec;

function renderEditor() {
  render(
    <PlaybookSpecEditor
      spec={SPEC}
      saving={false}
      error={null}
      onSave={vi.fn()}
      onCancel={vi.fn()}
    />,
  );
}

describe('PlaybookSpecEditor a11y', () => {
  it('阶段分组有可访问名称', () => {
    renderEditor();
    expect(screen.getByRole('group', { name: '阶段 1' })).toBeInTheDocument();
  });

  it('表单控件均有可访问名称', () => {
    renderEditor();

    expect(screen.getByRole('textbox', { name: '阶段 1 名称' })).toHaveValue('开题');
    expect(screen.getByRole('textbox', { name: '阶段 1 目标' })).toHaveValue('明确研究问题');
    expect(screen.getByRole('textbox', { name: '阶段 1 产物 1 名称' })).toHaveValue('开题报告');
    expect(screen.getByRole('textbox', { name: '阶段 1 产物 1 目标目录' })).toHaveValue('01_开题');
    expect(screen.getByRole('textbox', { name: '阶段 1 产物 1 匹配 glob' })).toHaveValue(
      '**/开题报告*.md',
    );
    expect(screen.getByRole('checkbox', { name: '阶段 1 产物 1 必需' })).toBeChecked();

    expect(screen.getByRole('textbox', { name: '阶段 1 规则 1 模板 key' })).toHaveValue(
      'citation_strict',
    );
    expect(screen.getByRole('textbox', { name: '阶段 1 规则 1 类别' })).toHaveValue('academic');
    expect(screen.getByRole('spinbutton', { name: '阶段 1 规则 1 优先级' })).toHaveValue(8);
    expect(screen.getByRole('textbox', { name: '阶段 1 规则 1 正文' })).toHaveValue(
      '引用必须可核验',
    );
    expect(screen.getByRole('textbox', { name: '阶段 1 规则 1 触发 glob' })).toHaveValue('always');

    expect(screen.getByRole('textbox', { name: '阶段 1 里程碑 1 标题' })).toHaveValue('完成初稿');
    expect(screen.getByRole('textbox', { name: '阶段 1 里程碑 1 描述' })).toHaveValue('两周内');

    expect(screen.getByRole('textbox', { name: '阶段 1 退出条件 1 id' })).toHaveValue(
      'proposal_finalized',
    );
    expect(screen.getByRole('textbox', { name: '阶段 1 退出条件 1 名称' })).toHaveValue(
      '开题报告已定稿',
    );
    expect(screen.getByRole('combobox', { name: '阶段 1 退出条件 1 类型' })).toHaveValue(
      'artifact',
    );
    expect(screen.getByRole('textbox', { name: '阶段 1 退出条件 1 关联产物 id' })).toHaveValue(
      'proposal_report',
    );

    expect(screen.getByRole('button', { name: '删除阶段 1 规则 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '删除阶段 1 里程碑 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '删除阶段 1 退出条件 1' })).toBeInTheDocument();
  });
});
