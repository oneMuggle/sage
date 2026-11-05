/**
 * M4-T4 (2026-11-05): 黄金任务集评测对话框测试。
 *
 * 覆盖：打开时加载任务目录；非模板实例化专家禁用运行并显示提示；
 * 运行评测后渲染通过率 / 按模板聚合 / 逐任务结果与未通过检查项；
 * 评测失败展示错误；目录加载失败展示错误。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  SpecialistEvalRunResult,
  SpecialistGoldenTasksResult,
} from '../../../shared/api/specialistApi';
import type { AgentProfile } from '../../../shared/api/types/domainEntityTypes';
import { SpecialistEvalDialog } from '../SpecialistEvalDialog';

const mockListGoldenTasks = vi.fn<() => Promise<SpecialistGoldenTasksResult>>();
const mockRunEval = vi.fn<(agentId: string) => Promise<SpecialistEvalRunResult>>();

vi.mock('../../../shared/api/specialistApi', () => ({
  specialistApi: {
    listGoldenTasks: () => mockListGoldenTasks(),
    runEval: (agentId: string) => mockRunEval(agentId),
  },
}));

const agent: AgentProfile = {
  id: 'specialist-writing-abcdef',
  name: '写作专家',
  role: 'specialist',
  description: '',
  system_prompt: '提示词',
  tools: [],
  memory_access: [],
  model_config: { model: '', temperature: 0.7, max_tokens: 0 },
  max_iterations: 20,
  enabled: true,
  version: 1,
};

const nonTemplateAgent: AgentProfile = { ...agent, id: 'writer', name: '自定义专家' };

const catalog: SpecialistGoldenTasksResult = {
  tasks: [
    {
      id: 'writing-polish-ai-education',
      template_id: 'writing',
      topic: '短文润色',
      prompt: '润色以下短文',
      checks: [{ kind: 'keywords_all', value: ['教育'] }],
    },
    {
      id: 'research-quantum-crypto',
      template_id: 'research',
      topic: '量子密码',
      prompt: '概述量子威胁',
      checks: [{ kind: 'refusal' }],
    },
  ],
  template_ids: ['writing', 'research'],
};

const runResult: SpecialistEvalRunResult = {
  run_id: 'f'.repeat(32),
  report: {
    total_tasks: 2,
    passed: 1,
    failed: 1,
    errored: 0,
    pass_rate: 0.5,
    total_tokens: 84,
    by_template: {
      writing: { total: 1, passed: 1, tokens: 42, pass_rate: 1 },
      research: { total: 1, passed: 0, tokens: 42, pass_rate: 0 },
    },
    task_results: [
      {
        task_id: 'writing-polish-ai-education',
        template_id: 'writing',
        topic: '短文润色',
        passed: true,
        checks: [{ check: 'keywords_all', passed: true }],
        tokens: 42,
        tool_calls: [],
        output_length: 200,
      },
      {
        task_id: 'research-quantum-crypto',
        template_id: 'research',
        topic: '量子密码',
        passed: false,
        checks: [{ check: 'max_chars', passed: false }],
        tokens: 42,
        tool_calls: [],
        output_length: 900,
      },
    ],
    started_at: 1730831400000,
    finished_at: 1730831460000,
  },
};

describe('SpecialistEvalDialog (M4-T4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListGoldenTasks.mockResolvedValue(catalog);
    mockRunEval.mockResolvedValue(runResult);
  });

  it('loads task catalog on open and shows coverage', async () => {
    render(<SpecialistEvalDialog open onOpenChange={vi.fn()} agent={agent} />);

    await waitFor(() => expect(mockListGoldenTasks).toHaveBeenCalledTimes(1));
    const coverage = await screen.findByText(/共 2 个任务，覆盖/);
    expect(coverage).toHaveTextContent('写作 / 研究');
  });

  it('shows loading state while catalog is loading', () => {
    mockListGoldenTasks.mockReturnValue(new Promise(() => {}));
    render(<SpecialistEvalDialog open onOpenChange={vi.fn()} agent={agent} />);
    expect(screen.getByText('加载任务目录…')).toBeInTheDocument();
  });

  it('shows catalog error', async () => {
    mockListGoldenTasks.mockRejectedValue(new Error('golden down'));
    render(<SpecialistEvalDialog open onOpenChange={vi.fn()} agent={agent} />);
    expect(await screen.findByText(/加载任务目录失败/)).toBeInTheDocument();
    expect(screen.getByText(/golden down/)).toBeInTheDocument();
  });

  it('disables run for non-template agents with a hint', async () => {
    render(
      <SpecialistEvalDialog open onOpenChange={vi.fn()} agent={nonTemplateAgent} />,
    );

    expect(
      await screen.findByText(/仅通过内置模板创建的专家支持评测/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '运行评测' })).toBeDisabled();
  });

  it('runs eval and renders pass rate and per-task checks', async () => {
    render(<SpecialistEvalDialog open onOpenChange={vi.fn()} agent={agent} />);
    await waitFor(() => expect(mockListGoldenTasks).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: '运行评测' }));

    await waitFor(() =>
      expect(mockRunEval).toHaveBeenCalledWith('specialist-writing-abcdef'),
    );
    expect(await screen.findByText(/通过 1\/2（50%）/)).toBeInTheDocument();
    expect(screen.getByText('短文润色')).toBeInTheDocument();
    expect(screen.getByText('量子密码')).toBeInTheDocument();
    // 未通过任务展示未通过的检查项中文标签
    expect(screen.getByText(/未通过：/)).toHaveTextContent('字数上限');
  });

  it('shows run error without crashing', async () => {
    mockRunEval.mockRejectedValue(new Error('agent not found'));
    render(<SpecialistEvalDialog open onOpenChange={vi.fn()} agent={agent} />);
    await waitFor(() => expect(mockListGoldenTasks).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: '运行评测' }));

    expect(await screen.findByText(/评测失败：/)).toBeInTheDocument();
    expect(screen.getByText(/agent not found/)).toBeInTheDocument();
  });
});
