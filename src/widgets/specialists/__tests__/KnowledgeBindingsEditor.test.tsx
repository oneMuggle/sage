/**
 * M2-Task 2 (2026-11-04): 专家知识绑定编辑器测试。
 *
 * 覆盖：打开时加载列表、新增（specialist_private 默认源标识 = 专家 ID）、
 * 解绑、加载失败显示错误并可重试。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AgentProfile, KnowledgeBinding } from '../../../shared/api';
import { KnowledgeBindingsEditor } from '../KnowledgeBindingsEditor';

const mockList = vi.fn<(agentId: string) => Promise<KnowledgeBinding[]>>();
const mockCreate =
  vi.fn<(agentId: string, payload: Record<string, unknown>) => Promise<KnowledgeBinding>>();
const mockRemove = vi.fn<(agentId: string, bindingId: string) => Promise<void>>();

vi.mock('../../../shared/api/specialistKnowledgeApi', () => ({
  specialistKnowledgeApi: {
    list: (agentId: string) => mockList(agentId),
    create: (agentId: string, payload: Record<string, unknown>) => mockCreate(agentId, payload),
    remove: (agentId: string, bindingId: string) => mockRemove(agentId, bindingId),
  },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const agent: AgentProfile = {
  id: 'specialist-abc',
  name: '写作专家',
  role: 'specialist',
  description: '',
  system_prompt: '',
  tools: [],
  memory_access: [],
  model_config: { model: 'test', temperature: 0.7, max_tokens: 1024 },
  max_iterations: 20,
  enabled: true,
};

const binding: KnowledgeBinding = {
  id: 'a1b2c3d4e5f6',
  agent_id: 'specialist-abc',
  source_type: 'wiki_project',
  source_id: 'proj_1',
  name: '团队论文库',
  filters: {},
  created_at: 1762262400,
};

function renderEditor(onOpenChange = vi.fn()) {
  return render(<KnowledgeBindingsEditor open onOpenChange={onOpenChange} agent={agent} />);
}

describe('KnowledgeBindingsEditor (M2-Task 2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('打开时加载并展示已有绑定', async () => {
    mockList.mockResolvedValue([binding]);

    renderEditor();

    expect(await screen.findByText('团队论文库')).toBeInTheDocument();
    const list = within(screen.getByRole('list', { name: '知识绑定列表' }));
    expect(list.getByText('项目 Wiki')).toBeInTheDocument();
    expect(list.getByText('proj_1')).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledWith('specialist-abc');
  });

  it('新增 specialist_private 绑定时源标识默认为专家 ID', async () => {
    mockList.mockResolvedValue([]);
    mockCreate.mockResolvedValue({
      ...binding,
      id: 'new-binding',
      source_type: 'specialist_private',
      source_id: 'specialist-abc',
      name: '私有资料',
      created_at: 1762262500,
    });

    renderEditor();
    await screen.findByText('尚未绑定任何知识源。');

    fireEvent.change(screen.getByLabelText('展示名称'), {
      target: { value: '私有资料' },
    });
    fireEvent.click(screen.getByRole('button', { name: '绑定' }));

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith('specialist-abc', {
        source_type: 'specialist_private',
        source_id: 'specialist-abc',
        name: '私有资料',
      });
    });
    expect(await screen.findByText('私有资料')).toBeInTheDocument();
  });

  it('解绑后从列表移除', async () => {
    mockList.mockResolvedValue([binding]);
    mockRemove.mockResolvedValue(undefined);

    renderEditor();

    fireEvent.click(await screen.findByRole('button', { name: '解绑 团队论文库' }));

    await waitFor(() => {
      expect(mockRemove).toHaveBeenCalledWith('specialist-abc', 'a1b2c3d4e5f6');
    });
    await waitFor(() => {
      expect(screen.queryByText('团队论文库')).not.toBeInTheDocument();
    });
  });

  it('加载失败显示错误并可重试', async () => {
    mockList.mockRejectedValueOnce(new Error('后端连接失败')).mockResolvedValueOnce([]);

    renderEditor();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('后端连接失败');

    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    expect(await screen.findByText('尚未绑定任何知识源。')).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledTimes(2);
  });
});
