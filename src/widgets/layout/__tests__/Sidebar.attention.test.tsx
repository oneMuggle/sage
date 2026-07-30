import { act, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { useQuestionState } from '../../../entities/question/questionState';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../Sidebar';

/**
 * U9 集成测试:Sidebar 中 Live-Dot（存活,无数字）与 Attention-Badge
 * （待处理,带数字）的语义分离。
 */

// 用 vi.hoisted 让静态 mock 工厂能读到每个用例可切换的设置
// （常量必须一并提升到 hoisted 块内,否则工厂执行时模块 const 尚未初始化）。
const hoisted = vi.hoisted(() => {
  const settingsConfigured = {
    endpoints: [
      {
        id: 'e1',
        name: '测试端点',
        baseUrl: 'http://127.0.0.1:8765',
        apiKey: 'test-key',
        discoveredModels: [],
        lastDiscoveredAt: null,
      },
    ],
    modelSelections: {
      chatModel: { endpointId: 'e1' as string | null, modelId: 'm1' as string | null },
      visionModel: { endpointId: null as string | null, modelId: null as string | null },
      embeddingModel: { endpointId: null as string | null, modelId: null as string | null },
    },
    maxContext: 4096,
    temperature: 0.7,
  };
  return {
    settingsConfigured,
    settingsBare: {
      ...settingsConfigured,
      endpoints: [],
      modelSelections: {
        chatModel: { endpointId: null, modelId: null },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
    },
    settingsRef: { current: settingsConfigured },
    testEndpointConnection: vi.fn(),
  };
});

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({ settings: hoisted.settingsRef.current }),
}));

vi.mock('../../../features/manage-endpoints/api', () => ({
  testEndpointConnection: (...args: unknown[]) => hoisted.testEndpointConnection(...args),
}));

const PENDING_PERMISSION = {
  request_id: 'req-1',
  tool_name: 'terminal',
  args_summary: '{"cmd":"rm -rf /tmp/x"}',
  risk: 'suspicious' as const,
  message: '需要执行终端命令',
  created_at: 0,
};

const PENDING_QUESTION = {
  request_id: 'req-2',
  question: '选择输出格式',
  header: '输出格式',
  options: [{ label: 'Markdown' }, { label: 'HTML' }],
  multi_select: false,
  created_at: 0,
};

function renderSidebar() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    </I18nProvider>,
  );
}

beforeEach(() => {
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
  // 三个 store 的清理统一放在 beforeEach,保证每个用例从干净状态开始。
  usePermissionState.setState({ currentRequest: null });
  useQuestionState.setState({ currentQuestion: null });
  hoisted.settingsRef.current = hoisted.settingsConfigured;
  hoisted.testEndpointConnection.mockReset();
});

describe('Sidebar — U9 Live-Dot vs Attention-Badge 分离', () => {
  it('无任何挂起卡点时不渲染 AttnBadge', async () => {
    hoisted.testEndpointConnection.mockResolvedValue({ success: true, latency: 10 });
    renderSidebar();
    await waitFor(() => expect(screen.getByLabelText(/^已连接/)).toBeInTheDocument());
    expect(screen.queryByRole('status', { name: /项待处理/ })).not.toBeInTheDocument();
  });

  it('挂起审批时,对话入口出现带数字的 AttnBadge', () => {
    hoisted.testEndpointConnection.mockResolvedValue({ success: true });
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    renderSidebar();
    const chatLink = screen.getByRole('link', { name: /对话/ });
    const badge = within(chatLink).getByRole('status');
    expect(badge).toHaveTextContent('1');
    expect(badge).toHaveAttribute('title', '1 项待处理');
  });

  it('挂起解除后 AttnBadge 即时消失(zustand 订阅重渲染路径)', () => {
    hoisted.testEndpointConnection.mockResolvedValue({ success: true });
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    renderSidebar();
    const chatLink = screen.getByRole('link', { name: /对话/ });
    expect(within(chatLink).getByRole('status')).toHaveTextContent('1');
    act(() => {
      usePermissionState.getState().resolve();
    });
    expect(within(chatLink).queryByRole('status')).not.toBeInTheDocument();
  });

  it('审批与提问同时挂起时计数累加', () => {
    hoisted.testEndpointConnection.mockResolvedValue({ success: true });
    usePermissionState.setState({ currentRequest: PENDING_PERMISSION });
    useQuestionState.setState({ currentQuestion: PENDING_QUESTION });
    renderSidebar();
    const chatLink = screen.getByRole('link', { name: /对话/ });
    expect(within(chatLink).getByRole('status')).toHaveTextContent('2');
  });

  it('后端已连接 → 页脚显示 working LiveDot(accent 脉冲,无数字)', async () => {
    hoisted.testEndpointConnection.mockResolvedValue({ success: true, latency: 42 });
    renderSidebar();
    const dot = await screen.findByLabelText('已连接 · 延迟 42ms');
    expect(dot).toHaveClass('bg-accent');
    expect(dot).toHaveClass('animate-pulse');
    // 存活指示器不带数字
    expect(dot).toHaveTextContent('');
  });

  it('未配置端点 → 页脚显示 sleeping LiveDot(静态点)', () => {
    hoisted.settingsRef.current = hoisted.settingsBare;
    renderSidebar();
    const dot = screen.getByLabelText('未配置端点');
    expect(dot).not.toHaveClass('animate-pulse');
    expect(screen.getByText('未配置')).toBeInTheDocument();
  });

  it('连接失败 → LiveDot 熄灭,改由 AttnBadge 承载告警', async () => {
    hoisted.testEndpointConnection.mockResolvedValue({ success: false });
    renderSidebar();
    await waitFor(() => expect(screen.getByText('连接失败')).toBeInTheDocument());
    // 存活指示器不渲染(idle)
    expect(screen.queryByLabelText(/^已连接/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('未配置端点')).not.toBeInTheDocument();
    // 注意力徽标承载错误
    expect(screen.getByRole('status', { name: '连接失败,请检查端点配置' })).toBeInTheDocument();
  });
});
