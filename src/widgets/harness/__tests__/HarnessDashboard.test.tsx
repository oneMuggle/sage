import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { HarnessComponent } from '../../../entities/harness/types';
import { harnessApi } from '../../../shared/api/harnessApi';
import { HarnessDashboard } from '../HarnessDashboard';

vi.mock('../../../shared/api/harnessApi', () => ({
  harnessApi: {
    listComponents: vi.fn(),
    listNeedingImprovement: vi.fn(),
    recordUsage: vi.fn(),
  },
}));

const mockedApi = vi.mocked(harnessApi);

function component(overrides: Partial<HarnessComponent> = {}): HarnessComponent {
  return {
    id: 'tool:bash',
    type: 'tool_guidance',
    name: 'bash 工具引导',
    version: '1.0.0',
    config: {},
    effectiveness: {
      usage_count: 42,
      success_rate: 0.92,
      avg_latency_ms: 320,
      user_satisfaction: 0.8,
      last_used_at: '2026-10-21T10:00:00Z',
    },
    needs_improvement: false,
    created_at: '2026-10-20T08:00:00Z',
    updated_at: '2026-10-21T10:00:00Z',
    ...overrides,
  };
}

describe('HarnessDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('加载期间显示加载态', async () => {
    mockedApi.listComponents.mockReturnValue(new Promise(() => {}));
    render(<HarnessDashboard />);
    expect(screen.getByText('加载中…')).toBeTruthy();
  });

  it('渲染组件卡片及其效果指标', async () => {
    mockedApi.listComponents.mockResolvedValue({
      items: [component()],
      total: 1,
      component_types: ['tool_guidance'],
    });
    render(<HarnessDashboard />);
    await waitFor(() => expect(screen.getByText('bash 工具引导')).toBeTruthy());
    expect(screen.getByText('工具引导')).toBeTruthy();
    expect(screen.getByText('42 次调用')).toBeTruthy();
    expect(screen.getByText('成功率 92%')).toBeTruthy();
    expect(screen.getByText('平均延迟 320ms')).toBeTruthy();
    expect(screen.getByText('满意度 80%')).toBeTruthy();
  });

  it('标记需要改进的组件', async () => {
    mockedApi.listComponents.mockResolvedValue({
      items: [
        component({
          id: 'skill:academic-search',
          type: 'skills',
          name: 'academic-search',
          needs_improvement: true,
          effectiveness: {
            usage_count: 5,
            success_rate: 0.6,
            avg_latency_ms: 1800,
            user_satisfaction: 0.4,
            last_used_at: null,
          },
        }),
      ],
      total: 1,
      component_types: ['skills'],
    });
    render(<HarnessDashboard />);
    await waitFor(() => expect(screen.getByTestId('harness-needs-improvement')).toBeTruthy());
    expect(screen.getByText('待改进')).toBeTruthy();
  });

  it('健康组件不带待改进标记', async () => {
    mockedApi.listComponents.mockResolvedValue({
      items: [component()],
      total: 1,
      component_types: ['tool_guidance'],
    });
    render(<HarnessDashboard />);
    await waitFor(() => expect(screen.getByText('bash 工具引导')).toBeTruthy());
    expect(screen.queryByTestId('harness-needs-improvement')).toBeNull();
  });

  it('延迟超过一秒时按秒展示，满意度按百分比展示', async () => {
    mockedApi.listComponents.mockResolvedValue({
      items: [
        component({
          effectiveness: {
            usage_count: 3,
            success_rate: 0.5,
            avg_latency_ms: 1800,
            user_satisfaction: 0.4,
            last_used_at: null,
          },
        }),
      ],
      total: 1,
      component_types: ['tool_guidance'],
    });
    render(<HarnessDashboard />);
    await waitFor(() => expect(screen.getByText('平均延迟 1.8s')).toBeTruthy());
    expect(screen.getByText('满意度 40%')).toBeTruthy();
  });

  it('无组件时展示空态提示', async () => {
    mockedApi.listComponents.mockResolvedValue({ items: [], total: 0, component_types: [] });
    render(<HarnessDashboard />);
    await waitFor(() => expect(screen.getByText(/暂无 harness 组件/)).toBeTruthy());
  });

  it('加载失败时展示错误与重试按钮', async () => {
    mockedApi.listComponents.mockRejectedValueOnce(new Error('后端不可达'));
    render(<HarnessDashboard />);
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.getByText('后端不可达')).toBeTruthy();

    mockedApi.listComponents.mockResolvedValue({ items: [], total: 0, component_types: [] });
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('按类型筛选组件', async () => {
    mockedApi.listComponents.mockResolvedValue({
      items: [
        component(),
        component({ id: 'skill:academic-search', type: 'skills', name: 'academic-search' }),
      ],
      total: 2,
      component_types: ['tool_guidance', 'skills'],
    });
    render(<HarnessDashboard />);
    await waitFor(() => expect(screen.getByText('全部 (2)')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: '技能 (1)' }));
    await waitFor(() => expect(screen.queryByText('bash 工具引导')).toBeNull());
    expect(screen.getByText('academic-search')).toBeTruthy();
  });
});
