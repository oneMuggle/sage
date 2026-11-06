/**
 * M3-Task 7 资产中心：SpecialistAssetsDialog 测试。
 *
 * 覆盖：打开时并行加载私有记忆 + 知识绑定并展示统计；手动添加记忆透传
 * agentId；删除 / 提升为共享后从列表移除；空态；加载失败可重试。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AgentProfile } from '../../../shared/api';
import { SpecialistAssetsDialog } from '../SpecialistAssetsDialog';

const mockGetMemories = vi.fn();
const mockSaveMemory = vi.fn();
const mockDeleteMemory = vi.fn();
const mockPromoteMemory = vi.fn();
const mockListBindings = vi.fn();

vi.mock('../../../shared/api', () => ({
  memoryApi: {
    getMemories: (...args: unknown[]) => mockGetMemories(...args),
    saveMemory: (...args: unknown[]) => mockSaveMemory(...args),
    deleteMemory: (...args: unknown[]) => mockDeleteMemory(...args),
    promoteMemory: (...args: unknown[]) => mockPromoteMemory(...args),
  },
}));

vi.mock('../../../shared/api/specialistKnowledgeApi', () => ({
  specialistKnowledgeApi: {
    list: (...args: unknown[]) => mockListBindings(...args),
  },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const agent = {
  id: 'specialist-writer',
  name: '写作专家',
  role: 'specialist',
  skills: ['zz-write', 'zz-polish'],
} as unknown as AgentProfile;

function memory(id: string, content: string) {
  return {
    id,
    content,
    memory_type: 'episodic',
    importance: 5,
    tags: [],
    created_at: 1_700_000_000,
    created_at_ms: 1_700_000_000_000,
    access_count: 0,
  };
}

function listResponse(items: unknown[], total = items.length) {
  return {
    items,
    total,
    page: 1,
    page_size: 20,
    layer: 'all',
    source_breakdown: { episodic: total, semantic: 0, working: 0, session_summary: 0 },
  };
}

function renderDialog() {
  return render(
    <SpecialistAssetsDialog
      open
      onOpenChange={vi.fn()}
      agent={agent}
      onManageKnowledge={vi.fn()}
    />,
  );
}

describe('SpecialistAssetsDialog（资产中心）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMemories.mockResolvedValue(
      listResponse([memory('m1', '偏好中文'), memory('m2', '代号必须拼成 SAGE')], 2),
    );
    mockSaveMemory.mockResolvedValue({ id: 'm3', status: 'ok' });
    mockDeleteMemory.mockResolvedValue(undefined);
    mockPromoteMemory.mockResolvedValue({
      status: 'promoted',
      memory_id: 'm1',
      memory_type: 'episodic',
      previous_agent_id: 'specialist-writer',
    });
    mockListBindings.mockResolvedValue([
      {
        id: 'b1',
        agent_id: 'specialist-writer',
        source_type: 'project_material',
        source_id: 'proj-1',
        name: '产品需求资料',
        filters: {},
        created_at: 1_700_000_000,
      },
    ]);
  });

  it('加载私有记忆、知识绑定与统计', async () => {
    renderDialog();

    expect(await screen.findByText('偏好中文')).toBeInTheDocument();
    expect(screen.getByText('代号必须拼成 SAGE')).toBeInTheDocument();
    expect(mockGetMemories).toHaveBeenCalledWith('all', 1, 20, { agentId: 'specialist-writer' });
    // 统计行
    expect(screen.getByText(/私有记忆 2 条/)).toBeInTheDocument();
    expect(screen.getByText(/知识绑定 1 项/)).toBeInTheDocument();
    expect(screen.getByText('产品需求资料')).toBeInTheDocument();
    expect(screen.getByText('zz-write')).toBeInTheDocument();
  });

  it('手动添加记忆时透传 agentId 并刷新列表', async () => {
    renderDialog();
    await screen.findByText('偏好中文');

    fireEvent.change(screen.getByTestId('specialist-asset-memory-input'), {
      target: { value: '新的专家私有偏好' },
    });
    fireEvent.change(screen.getByTestId('specialist-asset-memory-type'), {
      target: { value: 'semantic' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加记忆' }));

    await waitFor(() =>
      expect(mockSaveMemory).toHaveBeenCalledWith(
        '新的专家私有偏好',
        'semantic',
        5,
        ['manual'],
        undefined,
        'specialist-writer',
      ),
    );
    // 添加后重新加载
    await waitFor(() => expect(mockGetMemories).toHaveBeenCalledTimes(2));
  });

  it('提升为共享后从私有列表移除', async () => {
    renderDialog();
    await screen.findByText('偏好中文');

    fireEvent.click(screen.getAllByRole('button', { name: '提升为共享' })[0]);

    await waitFor(() => expect(mockPromoteMemory).toHaveBeenCalledWith('m1'));
    await waitFor(() => expect(screen.queryByText('偏好中文')).not.toBeInTheDocument());
    expect(screen.getByText('代号必须拼成 SAGE')).toBeInTheDocument();
  });

  it('删除记忆后从列表移除', async () => {
    renderDialog();
    await screen.findByText('代号必须拼成 SAGE');

    const row = screen.getByTestId('specialist-asset-memory-m2');
    const buttons = row.querySelectorAll('button');
    fireEvent.click(buttons[buttons.length - 1] as HTMLButtonElement);

    await waitFor(() => expect(mockDeleteMemory).toHaveBeenCalledWith('m2'));
    await waitFor(() => expect(screen.queryByText('代号必须拼成 SAGE')).not.toBeInTheDocument());
  });

  it('无私有记忆时显示空态', async () => {
    mockGetMemories.mockResolvedValue(listResponse([], 0));
    mockListBindings.mockResolvedValue([]);
    renderDialog();

    expect(await screen.findByText(/暂无私有记忆/)).toBeInTheDocument();
    expect(screen.getByText(/尚未绑定知识源/)).toBeInTheDocument();
  });

  it('加载失败显示错误并可重试', async () => {
    mockGetMemories.mockRejectedValueOnce(new Error('后端不可用'));
    renderDialog();

    expect(await screen.findByText(/加载失败：后端不可用/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('偏好中文')).toBeInTheDocument();
  });
});
