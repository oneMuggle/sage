/**
 * r113: MemoryBrowser UI 测试——统计卡、类型/作用域筛选、错误重试、
 * 摘要视图与会话跳转。
 *
 * memoryApi 以 vi.mock 替身注入；useNavigate 经 react-router-dom 部分_mock
 * 捕获跳转目标。组件文案为硬编码中文。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMemoriesMock = vi.fn();
const getSessionSummariesMock = vi.fn();
const navigateMock = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock('../../../shared/api', () => ({
  memoryApi: {
    getMemories: (...args: unknown[]) => getMemoriesMock(...args),
    getSessionSummaries: (...args: unknown[]) => getSessionSummariesMock(...args),
  },
}));

import { MemoryBrowser } from '../../../widgets/memory/MemoryBrowser';

function mem(overrides: Record<string, unknown> = {}) {
  return {
    id: 'm1',
    content: '记忆内容A',
    source: 'episodic',
    scope: 'user',
    session_id: 'sess-9',
    created_at_ms: 1700000000000,
    importance: 8,
    access_count: 2,
    ...overrides,
  };
}

const BREAKDOWN = { episodic: 1, semantic: 1, working: 1, session_summary: 0 };

function renderBrowser(props: Record<string, unknown> = {}) {
  return render(
    <>
      <MemoryBrowser {...props} />
    </>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getMemoriesMock.mockResolvedValue({
    items: [mem()],
    source_breakdown: BREAKDOWN,
    total: 1,
  });
  getSessionSummariesMock.mockResolvedValue({ items: [], source_breakdown: BREAKDOWN, total: 0 });
});

describe('MemoryBrowser 加载与列表', () => {
  it('加载中显示加载中', () => {
    getMemoriesMock.mockReturnValue(new Promise(() => {}));
    renderBrowser();
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('加载完成渲染标题、来源徽章与统计卡', async () => {
    renderBrowser();
    await waitFor(() => expect(screen.getByTestId('memory-episodic-item')).toBeInTheDocument(), { timeout: 10000 });
    expect(screen.getByTestId('memory-episodic-item').textContent).toContain('用户');
    expect(screen.getAllByText('情景').length).toBeGreaterThan(0); // source 徽章
    expect(screen.getByText('本周新增')).toBeInTheDocument(); // 统计卡
  }, 20000);

  it('接口报错显示错误信息与重试按钮', async () => {
    getMemoriesMock.mockRejectedValue(new Error('db down'));
    renderBrowser();
    expect(await screen.findByText('db down', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('重试')).toBeInTheDocument();
  }, 20000);

  it('空列表显示暂无记忆', async () => {
    getMemoriesMock.mockResolvedValue({ items: [], source_breakdown: BREAKDOWN, total: 0 });
    renderBrowser();
    expect(await screen.findByText('暂无记忆', {}, { timeout: 5000 })).toBeInTheDocument();
  }, 20000);
});

describe('MemoryBrowser 筛选', () => {
  it('类型筛选按钮切换后按新类型重新拉取', async () => {
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });
    fireEvent.click(screen.getByText('工作记忆'));
    await waitFor(() => {
      expect(getMemoriesMock).toHaveBeenLastCalledWith(
        'working',
        1,
        100,
        expect.objectContaining({ signal: expect.anything() }),
      );
    });
  }, 20000);

  it('作用域筛选为前端过滤：项目作用域只显示项目记忆', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [
        mem({ id: 'm1', content: '用户记忆', scope: 'user' }),
        mem({ id: 'm2', content: '项目记忆', scope: 'project', project_key: 'pk-1' }),
      ],
      source_breakdown: BREAKDOWN,
      total: 2,
    });
    renderBrowser();
    await screen.findAllByText('用户记忆', {}, { timeout: 5000 });
    // '项目' 文本同时出现在筛选按钮与记忆徽章上——筛选按钮在 DOM 前部
    const projectFilter = screen.getAllByText('项目')[0];
    fireEvent.click(projectFilter);
    await waitFor(() => expect(screen.queryByText('用户记忆')).not.toBeInTheDocument());
    expect(screen.getAllByText('项目记忆').length).toBeGreaterThan(0);
  }, 20000);
});

describe('MemoryBrowser 会话跳转', () => {
  it('携带 session_id 的记忆显示跳转按钮并导航', async () => {
    renderBrowser();
    const jump = await screen.findByTitle('跳转到会话 sess-9');
    fireEvent.click(jump);
    expect(navigateMock).toHaveBeenCalledWith('/chat?session=sess-9');
  }, 20000);

  it('未携带 session_id 的记忆不显示跳转按钮', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [mem({ session_id: undefined })],
      source_breakdown: BREAKDOWN,
      total: 1,
    });
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });
    expect(screen.queryByTitle(/跳转到会话/)).not.toBeInTheDocument();
  }, 20000);
});

describe('MemoryBrowser 摘要视图', () => {
  it('空 session_id 刷新给出错误提示', async () => {
    renderBrowser();
    fireEvent.click(screen.getByText('按会话查看摘要'));
    fireEvent.click(screen.getByText('刷新'));
    expect(await screen.findByText('请输入会话 ID 以查看摘要', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(getSessionSummariesMock).not.toHaveBeenCalled();
  }, 20000);

  it('输入 session_id 后刷新拉取摘要', async () => {
    getSessionSummariesMock.mockResolvedValue({
      items: [mem({ id: 's1', source: 'session_summary', content: '会话摘要内容', status: 'ready' })],
      source_breakdown: BREAKDOWN,
      total: 1,
    });
    renderBrowser();
    fireEvent.click(screen.getByText('按会话查看摘要'));
    const input = screen.getByPlaceholderText('session_id');
    fireEvent.change(input, { target: { value: 'sess-42' } });
    fireEvent.click(screen.getByText('刷新'));
    await waitFor(() => expect(getSessionSummariesMock).toHaveBeenCalled());
    await screen.findAllByText('会话摘要内容'); // 标题与正文各渲染一次
    expect(screen.getByText('已就绪')).toBeInTheDocument();
  }, 20000);
});
