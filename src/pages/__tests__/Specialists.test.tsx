/**
 * P1 专家页面信息架构：筛选 Tab / 搜索 / 空态回归测试。
 *
 * 覆盖：列表渲染、来源筛选（全部/内置/我的/导入）、搜索过滤与清除、
 * 无匹配空态、无专家引导态。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AgentProfile } from '../../shared/api';
import { Specialists } from '../Specialists';

const mockList = vi.fn();

vi.mock('../../shared/api', () => ({
  agentsApi: {
    list: () => mockList(),
  },
  sessionApi: {
    setSpecialist: vi.fn(),
  },
  specialistApi: {
    isAvailable: () => false,
  },
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
vi.mock('../../widgets/specialists/TemplateGalleryDialog', () => ({
  TemplateGalleryDialog: () => null,
}));
vi.mock('../../widgets/specialists/VersionHistoryDialog', () => ({
  VersionHistoryDialog: () => null,
}));
vi.mock('../../widgets/specialists/SpecialistEvalDialog', () => ({
  SpecialistEvalDialog: () => null,
}));

function agent(partial: Partial<AgentProfile>): AgentProfile {
  return {
    id: 'a1',
    name: '专家',
    role: 'specialist',
    enabled: true,
    source: 'builtin',
    ...partial,
  } as unknown as AgentProfile;
}

const AGENTS: AgentProfile[] = [
  agent({ id: 'a1', name: '写作专家', source: 'builtin', persona_ui: { tagline: '专业写作' } }),
  agent({ id: 'a2', name: '研究专家', source: 'user', persona_ui: { tagline: '文献研究' } }),
  agent({ id: 'a3', name: '导入专家', source: 'imported', persona_ui: {} }),
];

function renderPage() {
  return render(
    <MemoryRouter>
      <Specialists />
    </MemoryRouter>,
  );
}

describe('Specialists 页面（P1）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue(AGENTS);
  });

  it('渲染全部专家卡片', async () => {
    renderPage();
    expect(await screen.findByText('写作专家')).toBeInTheDocument();
    expect(screen.getByText('研究专家')).toBeInTheDocument();
    expect(screen.getByText('导入专家')).toBeInTheDocument();
  });

  it('按来源筛选：导入 Tab 只显示 imported 专家', async () => {
    renderPage();
    await screen.findByText('写作专家');

    fireEvent.click(screen.getByRole('tab', { name: '导入' }));
    expect(screen.getByText('导入专家')).toBeInTheDocument();
    expect(screen.queryByText('写作专家')).not.toBeInTheDocument();
    expect(screen.queryByText('研究专家')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: '我的' }));
    expect(screen.getByText('研究专家')).toBeInTheDocument();
    expect(screen.queryByText('导入专家')).not.toBeInTheDocument();
  });

  it('搜索过滤名称/标语，无匹配时显示空态并可清除', async () => {
    renderPage();
    await screen.findByText('写作专家');

    const search = screen.getByTestId('specialists-search');
    fireEvent.change(search, { target: { value: '写作' } });
    expect(screen.getByText('写作专家')).toBeInTheDocument();
    expect(screen.queryByText('研究专家')).not.toBeInTheDocument();

    // 标语也能命中
    fireEvent.change(search, { target: { value: '文献' } });
    expect(screen.getByText('研究专家')).toBeInTheDocument();
    expect(screen.queryByText('写作专家')).not.toBeInTheDocument();

    // 无匹配 → 空态 + 清除筛选
    fireEvent.change(search, { target: { value: '不存在' } });
    expect(screen.getByText('没有匹配的专家')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }));
    expect(screen.getByText('写作专家')).toBeInTheDocument();
    expect(screen.getByText('导入专家')).toBeInTheDocument();
  });

  it('没有任何专家时显示引导与创建 CTA', async () => {
    mockList.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText('还没有专家')).toBeInTheDocument();
    // PageHeader 与空态各有一个 CTA，均存在即符合预期
    expect(screen.getAllByRole('button', { name: /从模板创建/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: /新建专家/ }).length).toBeGreaterThan(0);
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
  });
});
