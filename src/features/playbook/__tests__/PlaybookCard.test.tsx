// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlaybookCurrent } from '../../../shared/api/playbookApi';
import { PlaybookCard } from '../PlaybookCard';

const getCurrentMock = vi.fn();
const listBuiltinMock = vi.fn();
const bindMock = vi.fn();
const auditMock = vi.fn();
const auditAiMock = vi.fn();
const authorPreviewMock = vi.fn();
const applyActionsMock = vi.fn();
const confirmStageMock = vi.fn();
const exportMock = vi.fn();
const wikiExportMock = vi.fn();
const updateStateMock = vi.fn();
const unbindMock = vi.fn();
const versionsMock = vi.fn();
const cleanupRulesMock = vi.fn();
const importPreviewMock = vi.fn();
const importMock = vi.fn();

vi.mock('../../../shared/api/playbookApi', () => ({
  playbookApi: {
    getCurrent: (...args: unknown[]) => getCurrentMock(...args),
    listBuiltin: (...args: unknown[]) => listBuiltinMock(...args),
    bind: (...args: unknown[]) => bindMock(...args),
    audit: (...args: unknown[]) => auditMock(...args),
    auditAi: (...args: unknown[]) => auditAiMock(...args),
    authorPreview: (...args: unknown[]) => authorPreviewMock(...args),
    applyActions: (...args: unknown[]) => applyActionsMock(...args),
    confirmStage: (...args: unknown[]) => confirmStageMock(...args),
    exportPlaybook: (...args: unknown[]) => exportMock(...args),
    exportToWiki: (...args: unknown[]) => wikiExportMock(...args),
    updateState: (...args: unknown[]) => updateStateMock(...args),
    unbind: (...args: unknown[]) => unbindMock(...args),
    listVersions: (...args: unknown[]) => versionsMock(...args),
    cleanupRules: (...args: unknown[]) => cleanupRulesMock(...args),
    importPreview: (...args: unknown[]) => importPreviewMock(...args),
    importPlaybook: (...args: unknown[]) => importMock(...args),
  },
}));

const audit = {
  playbook: { id: 'cn-research-grant', name: '科研课题' },
  current_stage: 'proposal',
  detected_stage: { id: 'execution', confidence: 0.75, evidence: ['stage:proposal progress=100%'] },
  stages: [
    {
      id: 'proposal',
      label: '开题',
      order: 1,
      objective: '明确研究问题',
      progress: 100,
      required_total: 1,
      required_done: 1,
      remaining: [],
      artifacts: [],
      exit_criteria: [
        {
          id: 'literature_matrix_ready',
          label: '文献对比矩阵已建立',
          type: 'manual',
          status: 'pending',
        },
      ],
    },
    {
      id: 'execution',
      label: '实施',
      order: 2,
      objective: '完成研究',
      progress: 0,
      required_total: 1,
      required_done: 0,
      remaining: [
        {
          id: 'raw_data',
          label: '原始数据',
          missing_action: { type: 'create_folder', payload: { path: '02_实施/数据' } },
        },
      ],
      artifacts: [],
      exit_criteria: [],
    },
  ],
  overall: { required_total: 2, required_done: 1, progress: 50 },
  classification_suggestions: [
    {
      from: '开题报告.md',
      to: '01_开题/开题报告.md',
      artifact_id: 'proposal_report',
      label: '开题报告',
      stage_id: 'proposal',
      reason: '开题报告应位于 01_开题/',
    },
  ],
  scanned_at: 1,
};

const unbound: PlaybookCurrent = {
  bound: false,
  state: {},
  suggested: {
    id: 'cn-research-grant',
    name: '科研课题（开题 · 实施 · 结题）',
    description: '科研全周期管理',
    project_types: ['research'],
    sub_types: [],
    stage_count: 3,
    directories: ['01_开题'],
  },
};

const bound: PlaybookCurrent = {
  bound: true,
  playbook: {
    id: 'cn-research-grant',
    name: '科研课题（开题 · 实施 · 结题）',
    description: '科研全周期管理',
    stages: [
      {
        id: 'proposal',
        label: '开题',
        artifacts: [],
        recommended_milestones: [{ title: '完成开题报告初稿', stage: 'proposal' }],
      },
      { id: 'execution', label: '实施', artifacts: [], recommended_milestones: [] },
    ],
  } as never,
  source: 'builtin:cn-research-grant',
  version: 1,
  state: { current_stage: 'proposal' },
  audit: audit as never,
};

const boundExecution: PlaybookCurrent = {
  ...bound,
  state: { current_stage: 'execution' },
  audit: {
    ...audit,
    current_stage: 'execution',
    detected_stage: { id: 'execution', confidence: 0.9, evidence: [] },
  } as never,
};

beforeEach(() => {
  vi.clearAllMocks();
  listBuiltinMock.mockResolvedValue([
    {
      id: 'cn-research-grant',
      name: '科研课题',
      description: '科研全周期管理',
      project_types: ['research'],
      sub_types: [],
      stage_count: 3,
      directories: [],
    },
  ]);
});

describe('PlaybookCard', () => {
  it('未绑定时显示推荐规程并可绑定', async () => {
    getCurrentMock.mockResolvedValue(unbound);
    bindMock.mockResolvedValue({ ...bound, version: 2 });
    render(<PlaybookCard projectId="p1" />);

    await screen.findByTestId('playbook-card');
    expect(screen.getByText(/推荐/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('playbook-bind-btn'));
    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith('p1', { playbookId: 'cn-research-grant' }),
    );
  });

  it('已绑定显示阶段条、完成度与缺失项动作', async () => {
    getCurrentMock.mockResolvedValue(boundExecution);
    applyActionsMock.mockResolvedValue({
      applied: ['create_folder'],
      skipped: [],
      errors: [],
      checkpoint_created: true,
      audit,
    });
    render(<PlaybookCard projectId="p1" />);

    await screen.findByTestId('playbook-card');
    expect(screen.getByText(/整体完成度 50%/)).toBeInTheDocument();
    expect(screen.getByTestId('playbook-stage-proposal')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('playbook-missing-action-raw_data'));
    await waitFor(() =>
      expect(applyActionsMock).toHaveBeenCalledWith('p1', [
        { type: 'create_folder', payload: { path: '02_实施/数据' } },
      ]),
    );
  });

  it('AI 定制规程后可直接绑定生成的草案', async () => {
    getCurrentMock.mockResolvedValue(unbound);
    authorPreviewMock.mockResolvedValue({
      playbook: { ...bound.playbook, id: 'custom-1', name: 'AI 生成的规程' },
      rationale: '根据学校要求生成',
      llm_available: true,
      source: 'llm',
    });
    bindMock.mockResolvedValue({ ...bound, version: 2 });
    render(<PlaybookCard projectId="p1" />);

    await screen.findByTestId('playbook-card');
    fireEvent.click(screen.getByTestId('playbook-author-btn'));
    await waitFor(() => expect(authorPreviewMock).toHaveBeenCalledWith('p1', { notes: '' }));
    expect(screen.getByText('AI 生成的规程')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('playbook-bind-authored'));
    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith('p1', {
        spec: expect.objectContaining({ id: 'custom-1' }),
        source: 'ai-authored',
      }),
    );
  });

  it('检测到阶段推进时需用户确认', async () => {
    getCurrentMock.mockResolvedValue(bound);
    confirmStageMock.mockResolvedValue({
      ...bound,
      state: { current_stage: 'execution' },
    });
    render(<PlaybookCard projectId="p1" />);

    await screen.findByTestId('playbook-detected-stage');
    fireEvent.click(screen.getByTestId('playbook-confirm-stage'));
    await waitFor(() => expect(confirmStageMock).toHaveBeenCalledWith('p1', 'execution'));
  });

  it('“保持当前”会隐藏检测提示', async () => {
    getCurrentMock.mockResolvedValue(bound);
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-detected-stage');
    fireEvent.click(screen.getByTestId('playbook-keep-stage'));
    await waitFor(() =>
      expect(screen.queryByTestId('playbook-detected-stage')).not.toBeInTheDocument(),
    );
  });

  it('检查完整性重新拉取审计', async () => {
    getCurrentMock.mockResolvedValue(bound);
    auditMock.mockResolvedValue(audit);
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-card');
    fireEvent.click(screen.getByTestId('playbook-refresh-audit'));
    await waitFor(() => expect(auditMock).toHaveBeenCalledWith('p1'));
  });

  it('写入 Wiki 调用 exportToWiki', async () => {
    getCurrentMock.mockResolvedValue(bound);
    wikiExportMock.mockResolvedValue({
      path: 'wiki/guides/playbook-handbook.md',
      created: true,
      updated: false,
    });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-wiki-export');
    fireEvent.click(screen.getByTestId('playbook-wiki-export'));
    await waitFor(() => expect(wikiExportMock).toHaveBeenCalledWith('p1'));
  });

  it('AI 检查内容调用 auditAi', async () => {
    getCurrentMock.mockResolvedValue(bound);
    auditAiMock.mockResolvedValue({ ...audit, llm_available: true });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-card');
    fireEvent.click(screen.getByTestId('playbook-ai-audit'));
    await waitFor(() => expect(auditAiMock).toHaveBeenCalledWith('p1'));
  });

  it('待补项可一键转待办', async () => {
    getCurrentMock.mockResolvedValue(boundExecution);
    applyActionsMock.mockResolvedValue({
      applied: ['add_todo'],
      skipped: [],
      errors: [],
      checkpoint_created: true,
      audit,
    });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-add-todo-raw_data');
    fireEvent.click(screen.getByTestId('playbook-add-todo-raw_data'));
    await waitFor(() =>
      expect(applyActionsMock).toHaveBeenCalledWith('p1', [
        {
          type: 'add_todo',
          payload: {
            title: '补齐：原始数据',
            description: '项目规程 科研课题（开题 · 实施 · 结题） · 阶段 实施',
          },
        },
      ]),
    );
  });

  it('归类建议可逐项确认移动', async () => {
    getCurrentMock.mockResolvedValue(bound);
    applyActionsMock.mockResolvedValue({
      applied: ['move_file'],
      skipped: [],
      errors: [],
      checkpoint_created: true,
      audit,
    });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-classification');
    fireEvent.click(screen.getByTestId('playbook-move-proposal_report'));
    await waitFor(() =>
      expect(applyActionsMock).toHaveBeenCalledWith('p1', [
        {
          type: 'move_file',
          payload: { from: '开题报告.md', to: '01_开题/开题报告.md' },
        },
      ]),
    );
  });

  it('可编辑规程 JSON 并保存为新版本', async () => {
    getCurrentMock.mockResolvedValue(bound);
    bindMock.mockResolvedValue({ ...bound, version: 2 });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-edit-btn');
    fireEvent.click(screen.getByTestId('playbook-edit-btn'));
    await screen.findByTestId('playbook-editor-form');
    fireEvent.click(screen.getByTestId('playbook-editor-mode-json'));
    const editor = (await screen.findByTestId('playbook-spec-editor')) as HTMLTextAreaElement;
    const draft = JSON.parse(editor.value);
    draft.name = '自定义规程';
    fireEvent.change(editor, { target: { value: JSON.stringify(draft, null, 2) } });
    fireEvent.click(screen.getByTestId('playbook-save-spec'));
    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith('p1', {
        spec: expect.objectContaining({ name: '自定义规程' }),
        source: 'custom',
      }),
    );
  });

  it('表单模式可改名并保存', async () => {
    getCurrentMock.mockResolvedValue(bound);
    bindMock.mockResolvedValue({ ...bound, version: 2 });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-edit-btn');
    fireEvent.click(screen.getByTestId('playbook-edit-btn'));
    const nameInput = await screen.findByTestId('playbook-editor-name');
    fireEvent.change(nameInput, { target: { value: '表单改名规程' } });
    fireEvent.click(screen.getByTestId('playbook-save-spec'));
    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith('p1', {
        spec: expect.objectContaining({ name: '表单改名规程' }),
        source: 'custom',
      }),
    );
  });

  it('表单模式可编辑阶段规则与退出条件', async () => {
    getCurrentMock.mockResolvedValue(bound);
    bindMock.mockResolvedValue({ ...bound, version: 2 });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-edit-btn');
    fireEvent.click(screen.getByTestId('playbook-edit-btn'));

    const rules = await screen.findByTestId('playbook-editor-rules-proposal');
    fireEvent.click(within(rules).getByText('添加规则'));
    fireEvent.change(within(rules).getByPlaceholderText('规则正文（无模板 key 时必填）'), {
      target: { value: '禁止编造引用' },
    });

    const criteria = screen.getByTestId('playbook-editor-criteria-proposal');
    fireEvent.click(within(criteria).getByText('添加退出条件'));
    fireEvent.change(within(criteria).getByPlaceholderText('条件名称'), {
      target: { value: '文献矩阵已完成' },
    });

    fireEvent.click(screen.getByTestId('playbook-save-spec'));
    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith('p1', {
        spec: expect.objectContaining({
          stages: expect.arrayContaining([
            expect.objectContaining({
              rules: expect.arrayContaining([
                expect.objectContaining({ content: '禁止编造引用' }),
              ]),
              exit_criteria: expect.arrayContaining([
                expect.objectContaining({ label: '文献矩阵已完成', type: 'manual' }),
              ]),
            }),
          ]),
        }),
        source: 'custom',
      }),
    );
  });

  it('待补项可豁免', async () => {
    getCurrentMock.mockResolvedValue(boundExecution);
    updateStateMock.mockResolvedValue({
      ...boundExecution,
      state: { ...boundExecution.state, waivers: ['execution.raw_data'] },
    });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-waive-raw_data');
    fireEvent.click(screen.getByTestId('playbook-waive-raw_data'));
    await waitFor(() =>
      expect(updateStateMock).toHaveBeenCalledWith('p1', {
        waivers: ['execution.raw_data'],
      }),
    );
  });

  it('手动退出条件可标记完成', async () => {
    getCurrentMock.mockResolvedValue(bound);
    updateStateMock.mockResolvedValue({
      ...bound,
      state: { ...bound.state, manual_done: ['proposal.literature_matrix_ready'] },
    });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-manual-literature_matrix_ready');
    fireEvent.click(screen.getByTestId('playbook-manual-literature_matrix_ready'));
    await waitFor(() =>
      expect(updateStateMock).toHaveBeenCalledWith('p1', {
        manual_done: ['proposal.literature_matrix_ready'],
      }),
    );
  });

  it('版本历史可展开', async () => {
    getCurrentMock.mockResolvedValue(bound);
    versionsMock.mockResolvedValue([
      { version: 1, source: 'builtin:cn-research-grant', spec_hash: 'a', created_at: 1, active: true },
    ]);
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-versions-btn');
    fireEvent.click(screen.getByTestId('playbook-versions-btn'));
    await waitFor(() => expect(versionsMock).toHaveBeenCalledWith('p1'));
    expect(await screen.findByTestId('playbook-versions')).toBeInTheDocument();
  });

  it('解绑前需要确认', async () => {
    getCurrentMock.mockResolvedValue(bound);
    unbindMock.mockResolvedValue({ bound: false, state: {} });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-unbind');
    fireEvent.click(screen.getByTestId('playbook-unbind'));
    await waitFor(() => expect(unbindMock).toHaveBeenCalledWith('p1'));
    confirm.mockRestore();
  });

  it('可播种推荐里程碑', async () => {
    getCurrentMock.mockResolvedValue(bound);
    applyActionsMock.mockResolvedValue({
      applied: ['seed_milestones'],
      skipped: [],
      errors: [],
      checkpoint_created: true,
      audit,
    });
    render(<PlaybookCard projectId="p1" />);
    await screen.findByTestId('playbook-seed-milestones');
    fireEvent.click(screen.getByTestId('playbook-seed-milestones'));
    await waitFor(() =>
      expect(applyActionsMock).toHaveBeenCalledWith('p1', [
        {
          type: 'seed_milestones',
          payload: {
            milestones: [
              {
                title: '完成开题报告初稿',
                description: '',
                stage: 'proposal',
              },
            ],
          },
        },
      ]),
    );
  });
});
