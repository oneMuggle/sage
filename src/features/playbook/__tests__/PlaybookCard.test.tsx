// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlaybookCurrent } from '../../../shared/api/playbookApi';
import { PlaybookCard } from '../PlaybookCard';

const getCurrentMock = vi.fn();
const listBuiltinMock = vi.fn();
const bindMock = vi.fn();
const auditMock = vi.fn();
const applyActionsMock = vi.fn();
const confirmStageMock = vi.fn();
const exportMock = vi.fn();
const importPreviewMock = vi.fn();
const importMock = vi.fn();

vi.mock('../../../shared/api/playbookApi', () => ({
  playbookApi: {
    getCurrent: (...args: unknown[]) => getCurrentMock(...args),
    listBuiltin: (...args: unknown[]) => listBuiltinMock(...args),
    bind: (...args: unknown[]) => bindMock(...args),
    audit: (...args: unknown[]) => auditMock(...args),
    applyActions: (...args: unknown[]) => applyActionsMock(...args),
    confirmStage: (...args: unknown[]) => confirmStageMock(...args),
    exportPlaybook: (...args: unknown[]) => exportMock(...args),
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
      exit_criteria: [],
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
    stages: [{ id: 'proposal' }, { id: 'execution' }],
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

  it('检测到阶段推进时需用户确认', async () => {
    getCurrentMock.mockResolvedValue(bound);
    confirmStageMock.mockResolvedValue({
      ...bound,
      state: { current_stage: 'execution' },
    });
    render(<PlaybookCard projectId="p1" />);

    await screen.findByTestId('playbook-detected-stage');
    fireEvent.click(screen.getByTestId('playbook-confirm-stage'));
    await waitFor(() =>
      expect(confirmStageMock).toHaveBeenCalledWith('p1', 'execution'),
    );
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
});
