/**
 * 详情页「能力」tab：技能 chips + 工具能力（能力包覆盖 / 未归类 / 纯对话空态）。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { findToolCapabilityPack } from '../../entities/specialist/toolCapabilities';
import type { AgentProfile } from '../../shared/api';
import { SpecialistDetail } from '../SpecialistDetail';

const mockList = vi.fn();

vi.mock('../../shared/api', () => ({
  agentsApi: {
    list: () => mockList(),
  },
  sessionApi: {
    setSpecialist: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('../../widgets/specialists/SpecialistWizard', () => ({
  SpecialistWizard: () => null,
}));
vi.mock('../../widgets/specialists/KnowledgeBindingsEditor', () => ({
  KnowledgeBindingsEditor: () => null,
}));
vi.mock('../../widgets/specialists/SpecialistAssetsDialog', () => ({
  SpecialistAssetsDialog: () => null,
}));
vi.mock('../../widgets/specialists/VersionHistoryDialog', () => ({
  VersionHistoryDialog: () => null,
}));
vi.mock('../../widgets/specialists/SpecialistEvalDialog', () => ({
  SpecialistEvalDialog: () => null,
}));

function makeAgent(partial: Partial<AgentProfile>): AgentProfile {
  return {
    id: 'a1',
    name: '写作专家',
    role: 'specialist',
    enabled: true,
    source: 'user',
    version: 1,
    system_prompt: '## 身份\n写作助手',
    skills: ['academic-search'],
    tools: [],
    ...partial,
  } as unknown as AgentProfile;
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/specialists/a1']}>
      <Routes>
        <Route path="/specialists/:id" element={<SpecialistDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SpecialistDetail 能力 tab', () => {
  it('按能力包展示已覆盖的工具并列出未归类条目', async () => {
    const readPack = findToolCapabilityPack('file-read')!;
    mockList.mockResolvedValue([makeAgent({ tools: [...readPack.tools, 'office_delete'] })]);
    renderDetail();

    fireEvent.click(await screen.findByRole('tab', { name: '能力' }));

    expect(screen.getByText('academic-search')).toBeInTheDocument();
    const toolsCard = await screen.findByTestId('specialist-detail-tools');
    expect(toolsCard).toHaveTextContent(`共 ${readPack.tools.length + 1} 项工具`);
    expect(toolsCard).toHaveTextContent(readPack.label);
    expect(toolsCard).toHaveTextContent('未归类：office_delete');
  });

  it('工具为空时展示纯对话警告', async () => {
    mockList.mockResolvedValue([makeAgent({ tools: [] })]);
    renderDetail();

    fireEvent.click(await screen.findByRole('tab', { name: '能力' }));

    const toolsCard = await screen.findByTestId('specialist-detail-tools');
    expect(toolsCard).toHaveTextContent('纯对话专家');
    expect(screen.getByText(/纯对话（无工具）/)).toBeInTheDocument();
  });

  it('部分覆盖的能力包标注（部分）', async () => {
    mockList.mockResolvedValue([makeAgent({ tools: ['read_file'] })]);
    renderDetail();

    fireEvent.click(await screen.findByRole('tab', { name: '能力' }));

    const toolsCard = await screen.findByTestId('specialist-detail-tools');
    expect(toolsCard).toHaveTextContent('文件读取与检索（部分）');
  });
});
