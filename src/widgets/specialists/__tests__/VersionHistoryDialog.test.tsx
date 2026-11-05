/**
 * M4-T3 (2026-11-05): 版本历史对话框测试。
 *
 * 覆盖：打开时加载版本列表并展示标签/当前标记；「对比」调用 diff 并渲染
 * 中文字段名与前后值；两段式回滚（确认/取消）；回滚成功后 toast + 回调 +
 * 重新加载；加载失败与空态。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  SpecialistVersionDiff,
  SpecialistVersionMeta,
} from '../../../shared/api/specialistApi';
import type { AgentProfile } from '../../../shared/api/types/domainEntityTypes';
import { VersionHistoryDialog } from '../VersionHistoryDialog';

const mockListVersions = vi.fn<(agentId: string) => Promise<SpecialistVersionMeta[]>>();
const mockDiffVersions = vi.fn<
  (agentId: string, from: number, to: number) => Promise<SpecialistVersionDiff[]>
>();
const mockRollback = vi.fn<(agentId: string, version: number) => Promise<AgentProfile>>();

vi.mock('../../../shared/api/specialistApi', () => ({
  specialistApi: {
    listVersions: (agentId: string) => mockListVersions(agentId),
    diffVersions: (agentId: string, from: number, to: number) =>
      mockDiffVersions(agentId, from, to),
    rollbackAgent: (agentId: string, version: number) =>
      mockRollback(agentId, version),
  },
}));

const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

const agent: AgentProfile = {
  id: 'spec-a',
  name: '写作专家',
  role: 'specialist',
  description: '',
  system_prompt: '当前提示词',
  tools: [],
  memory_access: [],
  model_config: { model: '', temperature: 0.7, max_tokens: 0 },
  max_iterations: 20,
  enabled: true,
  version: 2,
};

const versions: SpecialistVersionMeta[] = [
  { version: 2, reason: 'update', created_at: 1730800000000 },
  { version: 1, reason: 'create', created_at: 1730700000000 },
];

const rolledProfile: AgentProfile = { ...agent, version: 3 };

describe('VersionHistoryDialog (M4-T3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListVersions.mockResolvedValue(versions);
    mockDiffVersions.mockResolvedValue([
      { field: 'system_prompt', before: '旧提示词', after: '新提示词' },
    ]);
    mockRollback.mockResolvedValue(rolledProfile);
  });

  it('loads versions on open and renders labels', async () => {
    render(
      <VersionHistoryDialog open onOpenChange={vi.fn()} agent={agent} />,
    );

    await waitFor(() => expect(mockListVersions).toHaveBeenCalledWith('spec-a'));
    expect(await screen.findByText('v2')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByText('更新')).toBeInTheDocument();
    expect(screen.getByText('创建')).toBeInTheDocument();
    expect(screen.getByText('当前')).toBeInTheDocument();
  });

  it('shows loading state initially', () => {
    mockListVersions.mockReturnValue(new Promise(() => {}));
    render(
      <VersionHistoryDialog open onOpenChange={vi.fn()} agent={agent} />,
    );
    expect(screen.getByText('加载版本…')).toBeInTheDocument();
  });

  it('shows empty state when no versions', async () => {
    mockListVersions.mockResolvedValue([]);
    render(
      <VersionHistoryDialog open onOpenChange={vi.fn()} agent={agent} />,
    );
    expect(await screen.findByText(/暂无版本快照/)).toBeInTheDocument();
  });

  it('shows error state on load failure', async () => {
    mockListVersions.mockRejectedValue(new Error('backend down'));
    render(
      <VersionHistoryDialog open onOpenChange={vi.fn()} agent={agent} />,
    );
    expect(await screen.findByText(/加载版本失败/)).toBeInTheDocument();
    expect(screen.getByText(/backend down/)).toBeInTheDocument();
  });

  it('diffs a historical version against the latest', async () => {
    render(
      <VersionHistoryDialog open onOpenChange={vi.fn()} agent={agent} />,
    );

    // DESC 列表：第 0 个是当前版本（对比禁用），第 1 个是 v1
    const diffButtons = await screen.findAllByRole('button', { name: '对比' });
    expect(diffButtons).toHaveLength(2);
    expect(diffButtons[0]).toBeDisabled();
    fireEvent.click(diffButtons[1]);

    await waitFor(() =>
      expect(mockDiffVersions).toHaveBeenCalledWith('spec-a', 1, 2),
    );
    expect(await screen.findByText('人设提示词')).toBeInTheDocument();
    expect(screen.getByText('旧提示词')).toBeInTheDocument();
    expect(screen.getByText('新提示词')).toBeInTheDocument();
    // 再次点击收起
    fireEvent.click(screen.getByRole('button', { name: '收起对比' }));
    await waitFor(() =>
      expect(screen.queryByText('人设提示词')).not.toBeInTheDocument(),
    );
  });

  it('rolls back in two steps with confirm', async () => {
    const onRolledBack = vi.fn();
    render(
      <VersionHistoryDialog
        open
        onOpenChange={vi.fn()}
        agent={agent}
        onRolledBack={onRolledBack}
      />,
    );

    const rollbackButtons = await screen.findAllByRole('button', { name: '回滚' });
    expect(rollbackButtons).toHaveLength(1); // 仅 v1（当前版本无回滚）
    fireEvent.click(rollbackButtons[0]);

    // 第一步不调用后端
    expect(mockRollback).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认回滚' }));

    await waitFor(() =>
      expect(mockRollback).toHaveBeenCalledWith('spec-a', 1),
    );
    await waitFor(() => expect(onRolledBack).toHaveBeenCalledWith(rolledProfile));
    expect(mockToastSuccess).toHaveBeenCalled();
    // 回滚后重新加载列表（初始 1 次 + 回滚后 1 次）
    await waitFor(() => expect(mockListVersions).toHaveBeenCalledTimes(2));
  });

  it('cancels pending rollback without calling backend', async () => {
    render(
      <VersionHistoryDialog open onOpenChange={vi.fn()} agent={agent} />,
    );

    fireEvent.click((await screen.findAllByRole('button', { name: '回滚' }))[0]);
    fireEvent.click(screen.getByRole('button', { name: '取消' }));

    expect(mockRollback).not.toHaveBeenCalled();
    expect(
      screen.queryByRole('button', { name: '确认回滚' }),
    ).not.toBeInTheDocument();
  });

  it('shows toast on rollback failure', async () => {
    mockRollback.mockRejectedValue(new Error('version not found'));
    render(
      <VersionHistoryDialog open onOpenChange={vi.fn()} agent={agent} />,
    );

    fireEvent.click((await screen.findAllByRole('button', { name: '回滚' }))[0]);
    fireEvent.click(screen.getByRole('button', { name: '确认回滚' }));

    await waitFor(() => expect(mockToastError).toHaveBeenCalled());
    expect(mockToastError.mock.calls[0][0]).toMatch(/version not found/);
  });
});
