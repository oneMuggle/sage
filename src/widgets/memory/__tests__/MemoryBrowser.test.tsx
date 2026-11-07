/**
 * r113: MemoryBrowser UI 测试——统计卡、类型/作用域筛选、错误重试、
 * 摘要视图与会话跳转。
 *
 * memoryApi 以 vi.mock 替身注入；useNavigate 经 react-router-dom 部分_mock
 * 捕获跳转目标。组件文案为硬编码中文。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMemoriesMock = vi.fn();
const getSessionSummariesMock = vi.fn();
const searchMemoriesMock = vi.fn();
const deleteMemoryMock = vi.fn();
const promoteMemoryMock = vi.fn();
<<<<<<< HEAD
const getQualityCandidatesMock = vi.fn();
const batchDeleteMemoriesMock = vi.fn();
const submitMemoryFeedbackMock = vi.fn();
const getSessionMock = vi.fn();
=======
>>>>>>> origin/main
const navigateMock = vi.fn();
const agentsListMock = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock('../../../shared/api', () => ({
  memoryApi: {
    getMemories: (...args: unknown[]) => getMemoriesMock(...args),
    getSessionSummaries: (...args: unknown[]) => getSessionSummariesMock(...args),
    searchMemories: (...args: unknown[]) => searchMemoriesMock(...args),
    deleteMemory: (...args: unknown[]) => deleteMemoryMock(...args),
    promoteMemory: (...args: unknown[]) => promoteMemoryMock(...args),
<<<<<<< HEAD
    getQualityCandidates: (...args: unknown[]) => getQualityCandidatesMock(...args),
    batchDeleteMemories: (...args: unknown[]) => batchDeleteMemoriesMock(...args),
    submitMemoryFeedback: (...args: unknown[]) => submitMemoryFeedbackMock(...args),
  },
  sessionApi: {
    get: (...args: unknown[]) => getSessionMock(...args),
=======
>>>>>>> origin/main
  },
}));

vi.mock('../../../shared/api/agentsApi', () => ({
  agentsApi: {
    list: () => agentsListMock(),
  },
}));

vi.mock('sonner', () => ({
<<<<<<< HEAD
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import { MemoryBrowser } from '../../../widgets/memory/MemoryBrowser';
import { clearSessionInfoCache } from '../useSessionInfo';
=======
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

import { MemoryBrowser } from '../../../widgets/memory/MemoryBrowser';
>>>>>>> origin/main

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
<<<<<<< HEAD
  clearSessionInfoCache();
  getSessionMock.mockRejectedValue(new Error('session not found'));
=======
>>>>>>> origin/main
  getMemoriesMock.mockResolvedValue({
    items: [mem()],
    source_breakdown: BREAKDOWN,
    total: 1,
  });
  getSessionSummariesMock.mockResolvedValue({ items: [], source_breakdown: BREAKDOWN, total: 0 });
  searchMemoriesMock.mockResolvedValue([]);
  deleteMemoryMock.mockResolvedValue(undefined);
  promoteMemoryMock.mockResolvedValue({
    status: 'promoted',
    memory_id: 'm1',
    memory_type: 'episodic',
    previous_agent_id: 'specialist-x',
  });
  agentsListMock.mockResolvedValue([]);
<<<<<<< HEAD
  getQualityCandidatesMock.mockResolvedValue([]);
  batchDeleteMemoriesMock.mockResolvedValue({ deleted: 0, failed: [] });
  submitMemoryFeedbackMock.mockResolvedValue({
    status: 'ok',
    memory_id: 'm1',
    memory_type: 'episodic',
    feedback: 'up',
  });
=======
>>>>>>> origin/main
});

describe('MemoryBrowser 加载与列表', () => {
  it('加载中显示加载中', () => {
    getMemoriesMock.mockReturnValue(new Promise(() => {}));
    renderBrowser();
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('加载完成渲染标题、来源徽章与统计卡', async () => {
    renderBrowser();
    await waitFor(() => expect(screen.getByTestId('memory-episodic-item')).toBeInTheDocument(), {
      timeout: 10000,
    });
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

  // M3-Task 6: 专家归属筛选走后端 agent_id 精确过滤。
  it('专家归属下拉渲染共享层与专家项，切换后按 agentId 重新拉取', async () => {
    agentsListMock.mockResolvedValue([{ id: 'specialist-x', name: '文献专家' }]);
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });
    // 专家列表异步到达后下拉出现（下拉是 button，徽标是 span，用 role 区分）
    const sharedBtn = await screen.findByRole('button', { name: '共享层' }, { timeout: 5000 });
    expect(sharedBtn).toBeInTheDocument();
    const specialistBtn = screen.getByRole('button', { name: '文献专家' });
    expect(specialistBtn).toBeInTheDocument();

    fireEvent.click(specialistBtn);
    await waitFor(() => {
      expect(getMemoriesMock).toHaveBeenLastCalledWith(
        undefined,
        1,
        100,
        expect.objectContaining({ agentId: 'specialist-x' }),
      );
    });
  }, 20000);

  it('共享层筛选透传 agentId=shared', async () => {
    agentsListMock.mockResolvedValue([{ id: 'specialist-x', name: '文献专家' }]);
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });
    const sharedBtn = await screen.findByRole('button', { name: '共享层' }, { timeout: 5000 });

    fireEvent.click(sharedBtn);
    await waitFor(() => {
      expect(getMemoriesMock).toHaveBeenLastCalledWith(
        undefined,
        1,
        100,
        expect.objectContaining({ agentId: 'shared' }),
      );
    });
  }, 20000);

  it('专家归属徽标区分共享层/主助手/专家私有', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [
        mem({ id: 'm1', content: '共享记忆', agent_id: undefined }),
        mem({ id: 'm2', content: '主助手记忆', agent_id: 'primary' }),
        mem({ id: 'm3', content: '专家记忆', agent_id: 'specialist-x' }),
      ],
      source_breakdown: BREAKDOWN,
      total: 3,
    });
    renderBrowser();
    await screen.findAllByText('共享记忆', {}, { timeout: 5000 });
    expect(screen.getAllByText('共享').length).toBeGreaterThan(0);
    expect(screen.getAllByText('主助手').length).toBeGreaterThan(0);
    expect(screen.getAllByText('specialist-x').length).toBeGreaterThan(0);
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
<<<<<<< HEAD

  it('Task 4.2: 显示会话标题与相对日期', async () => {
    const sessionId = '4a4f6f2e-1111-4222-8333-944455556666';
    getSessionMock.mockResolvedValue({
      id: sessionId,
      title: '用户配置偏好',
      created_at: Math.floor((Date.now() - 3 * 24 * 60 * 60 * 1000) / 1000),
    });
    getMemoriesMock.mockResolvedValue({
      items: [mem({ session_id: sessionId })],
      source_breakdown: BREAKDOWN,
      total: 1,
    });
    renderBrowser();

    const jump = await screen.findByTitle(`跳转到会话 ${sessionId}`);
    expect(jump.textContent).toContain('↳ 「用户配置偏好」');
    expect(jump.textContent).toContain('3 天前');
  }, 20000);

  it('Task 4.2: 会话不存在时降级显示截断 ID', async () => {
    renderBrowser();
    const jump = await screen.findByTitle('跳转到会话 sess-9');
    await waitFor(() => expect(jump.textContent).toContain('↳ 会话 sess-9'), { timeout: 5000 });
    expect(jump.textContent).not.toContain('天前');
  }, 20000);
=======
>>>>>>> origin/main
});

describe('MemoryBrowser 摘要视图', () => {
  it('空 session_id 刷新给出错误提示', async () => {
    renderBrowser();
    fireEvent.click(screen.getByText('按会话查看摘要'));
    fireEvent.click(screen.getByText('刷新'));
    expect(
      await screen.findByText('请输入会话 ID 以查看摘要', {}, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(getSessionSummariesMock).not.toHaveBeenCalled();
  }, 20000);

  it('输入 session_id 后刷新拉取摘要', async () => {
    getSessionSummariesMock.mockResolvedValue({
      items: [
        mem({ id: 's1', source: 'session_summary', content: '会话摘要内容', status: 'ready' }),
      ],
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

/**
 * P0-1（2026-10-01）：接上此前零调用的 searchMemories / deleteMemory。
 * PHILOSOPHY.md 把「不可删除：用户无法清除记忆」列为反模式 —— 在此之前
 * 用户有一条错误记忆时无路可走。
 */
describe('MemoryBrowser 搜索（P0-1）', () => {
  it('输入关键词后防抖并走语义检索', async () => {
    searchMemoriesMock.mockResolvedValue([mem({ id: 'h1', content: '命中的记忆' })]);
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });

    fireEvent.change(screen.getByTestId('memory-search-input'), { target: { value: '命中' } });

    await waitFor(() => expect(searchMemoriesMock).toHaveBeenCalledWith('命中', undefined), {
      timeout: 5000,
    });
    expect(await screen.findAllByText('命中的记忆', {}, { timeout: 5000 })).not.toHaveLength(0);
  }, 20000);

  it('搜索态下类型筛选不收窄为后端不支持的维度', async () => {
    searchMemoriesMock.mockResolvedValue([mem({ id: 'h1', content: '命中的记忆' })]);
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });

    fireEvent.click(screen.getByText('工作记忆'));
    fireEvent.change(screen.getByTestId('memory-search-input'), { target: { value: '命中' } });

    // working 不在 searchMemories 契约内 → 传 undefined 交后端全量匹配，
    // 不能静默收窄成空结果。
    await waitFor(() => expect(searchMemoriesMock).toHaveBeenCalledWith('命中', undefined), {
      timeout: 5000,
    });
  }, 20000);

  it('清空搜索后回到分页列表', async () => {
    searchMemoriesMock.mockResolvedValue([mem({ id: 'h1', content: '命中的记忆' })]);
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });
    const input = screen.getByTestId('memory-search-input');

    fireEvent.change(input, { target: { value: '命中' } });
    await waitFor(() => expect(searchMemoriesMock).toHaveBeenCalled(), { timeout: 5000 });

    fireEvent.change(input, { target: { value: '' } });
    await waitFor(() => expect(getMemoriesMock).toHaveBeenCalledTimes(2), { timeout: 5000 });
  }, 20000);
});

describe('MemoryBrowser 删除（P0-1）', () => {
  it('两步确认后才调用 deleteMemory 并移除该条', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [mem({ id: 'm1', content: '要删的记忆' }), mem({ id: 'm2', content: '保留的记忆' })],
      source_breakdown: BREAKDOWN,
      total: 2,
    });
    renderBrowser();
    await screen.findAllByText('要删的记忆', {}, { timeout: 5000 });

    // 第一步：仅进入确认态，不发请求
    fireEvent.click(screen.getByTestId('memory-delete-m1'));
    expect(deleteMemoryMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('memory-delete-confirm-m1')).toBeInTheDocument();

    // 第二步：确认后才真正删除
    fireEvent.click(screen.getByTestId('memory-delete-confirm-m1'));
    await waitFor(() => expect(deleteMemoryMock).toHaveBeenCalledWith('m1'), { timeout: 5000 });
    await waitFor(() => expect(screen.queryByText('要删的记忆')).not.toBeInTheDocument(), {
      timeout: 5000,
    });
    expect(screen.getAllByText('保留的记忆').length).toBeGreaterThan(0);
    expect(toast.success).toHaveBeenCalled();
  }, 20000);

  it('取消确认不发删除请求', async () => {
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });
    fireEvent.click(screen.getByTestId('memory-delete-m1'));
    fireEvent.click(screen.getByTestId('memory-delete-cancel-m1'));
    expect(deleteMemoryMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('memory-delete-m1')).toBeInTheDocument();
  }, 20000);

  it('删除失败时保留该条并明确提示，不静默移除', async () => {
    deleteMemoryMock.mockRejectedValue(new Error('db locked'));
    renderBrowser();
    await screen.findAllByText('记忆内容A', {}, { timeout: 5000 });

    fireEvent.click(screen.getByTestId('memory-delete-m1'));
    fireEvent.click(screen.getByTestId('memory-delete-confirm-m1'));

    await waitFor(() => expect(toast.error).toHaveBeenCalled(), { timeout: 5000 });
    // 关键：失败的行不得从列表消失（PHILOSOPHY「静默失败」反模式）
    expect(screen.getAllByText('记忆内容A').length).toBeGreaterThan(0);
  }, 20000);
});

/** M3-Task 7（2026-11-04）：私有记忆提升为共享层。 */
describe('MemoryBrowser 提升为共享（M3-Task 7）', () => {
  it('仅私有记忆渲染提升按钮，共享层记忆不渲染', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [
        mem({ id: 'shared-1', content: '共享记忆', agent_id: undefined }),
        mem({ id: 'priv-1', content: '专家私有记忆', agent_id: 'specialist-x' }),
      ],
      source_breakdown: BREAKDOWN,
      total: 2,
    });
    renderBrowser();
    await screen.findAllByText('专家私有记忆', {}, { timeout: 5000 });

    expect(screen.getByTestId('memory-promote-priv-1')).toBeInTheDocument();
    expect(screen.queryByTestId('memory-promote-shared-1')).not.toBeInTheDocument();
  }, 20000);

  it('两步确认后才调用 promoteMemory 并把归属翻转为共享', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [mem({ id: 'priv-1', content: '专家私有记忆', agent_id: 'specialist-x' })],
      source_breakdown: BREAKDOWN,
      total: 1,
    });
    renderBrowser();
    await screen.findAllByText('专家私有记忆', {}, { timeout: 5000 });
    expect(screen.getAllByText('specialist-x').length).toBeGreaterThan(0);

    // 第一步：进入确认态，不发请求
    fireEvent.click(screen.getByTestId('memory-promote-priv-1'));
    expect(promoteMemoryMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('memory-promote-priv-1').getAttribute('data-state')).toBe('armed');

    // 第二步：确认后调用，并把该行 agent_id 置空（徽标翻转为共享）
    fireEvent.click(screen.getByTestId('memory-promote-priv-1'));
    await waitFor(() => expect(promoteMemoryMock).toHaveBeenCalledWith('priv-1'), {
      timeout: 5000,
    });
    await waitFor(() => expect(screen.queryByText('specialist-x')).not.toBeInTheDocument(), {
      timeout: 5000,
    });
    expect(screen.getAllByText('共享').length).toBeGreaterThan(0);
    // 提升后不再是私有行 → 按钮消失
    expect(screen.queryByTestId('memory-promote-priv-1')).not.toBeInTheDocument();
    expect(toast.success).toHaveBeenCalled();
  }, 20000);

  it('已在共享层的幂等结果给出明确提示', async () => {
    promoteMemoryMock.mockResolvedValue({
      status: 'already_shared',
      memory_id: 'priv-1',
      memory_type: 'episodic',
      previous_agent_id: null,
    });
    getMemoriesMock.mockResolvedValue({
      items: [mem({ id: 'priv-1', content: '专家私有记忆', agent_id: 'specialist-x' })],
      source_breakdown: BREAKDOWN,
      total: 1,
    });
    renderBrowser();
    await screen.findAllByText('专家私有记忆', {}, { timeout: 5000 });

    fireEvent.click(screen.getByTestId('memory-promote-priv-1'));
    fireEvent.click(screen.getByTestId('memory-promote-priv-1'));
    await waitFor(() => expect(toast.success).toHaveBeenCalled(), { timeout: 5000 });
    // 归属翻转后徽标变「共享」、提升按钮随之消失（覆盖 Promise 微任务里的 setState）
    await waitFor(() => expect(screen.getAllByText('共享').length).toBeGreaterThan(0), {
      timeout: 5000,
    });
    expect(screen.queryByTestId('memory-promote-priv-1')).not.toBeInTheDocument();
  }, 20000);

  it('提升失败时保留专家归属并明确提示，不静默翻转', async () => {
    promoteMemoryMock.mockRejectedValue(new Error('db down'));
    getMemoriesMock.mockResolvedValue({
      items: [mem({ id: 'priv-1', content: '专家私有记忆', agent_id: 'specialist-x' })],
      source_breakdown: BREAKDOWN,
      total: 1,
    });
    renderBrowser();
    await screen.findAllByText('专家私有记忆', {}, { timeout: 5000 });

    fireEvent.click(screen.getByTestId('memory-promote-priv-1'));
    fireEvent.click(screen.getByTestId('memory-promote-priv-1'));

    await waitFor(() => expect(toast.error).toHaveBeenCalled(), { timeout: 5000 });
    // pending 态落回 idle（覆盖 Promise 微任务里的 setState）后再断言归属未变
    await waitFor(() =>
      expect(screen.getByTestId('memory-promote-priv-1').textContent).toContain('提升为共享'),
    );
    // 归属不变：专家徽标仍在，提升按钮仍可用
    expect(screen.getAllByText('specialist-x').length).toBeGreaterThan(0);
    expect(screen.getByTestId('memory-promote-priv-1')).toBeInTheDocument();
  }, 20000);
});

/** P0-6：从聊天气泡记忆引用深链 /memory?focus=<id> 的定位高亮。 */
describe('MemoryBrowser 深链定位（P0-6）', () => {
  beforeEach(() => {
    getMemoriesMock.mockResolvedValue({
      items: [mem({ id: 'm1', content: '第一条' }), mem({ id: 'm2', content: '被引用的那条' })],
      source_breakdown: BREAKDOWN,
      total: 2,
    });
  });

  it('命中 focus 的条目带高亮标记', async () => {
    renderBrowser({ focusMemoryId: 'm2' });
    await screen.findAllByText('被引用的那条', {}, { timeout: 5000 });

    const cards = screen.getAllByTestId('memory-episodic-item');
    const focused = cards.filter((c) => c.getAttribute('data-focused') === 'true');
    expect(focused).toHaveLength(1);
    expect(focused[0].textContent).toContain('被引用的那条');
  }, 20000);

  it('无 focus 参数时不高亮任何条目', async () => {
    renderBrowser();
    await screen.findAllByText('被引用的那条', {}, { timeout: 5000 });
    const cards = screen.getAllByTestId('memory-episodic-item');
    expect(cards.filter((c) => c.getAttribute('data-focused') === 'true')).toHaveLength(0);
  }, 20000);

  it('focus 指向不存在的 id 时不高亮、不报错', async () => {
    renderBrowser({ focusMemoryId: 'nope' });
    await screen.findAllByText('被引用的那条', {}, { timeout: 5000 });
    const cards = screen.getAllByTestId('memory-episodic-item');
    expect(cards.filter((c) => c.getAttribute('data-focused') === 'true')).toHaveLength(0);
  }, 20000);
});
<<<<<<< HEAD

/** Task 4.3：选择模式 + 批量清理低质量记忆。 */
describe('MemoryBrowser 批量清理（Task 4.3）', () => {
  beforeEach(() => {
    getMemoriesMock.mockResolvedValue({
      items: [
        mem({ id: 'm1', content: '低质量A', quality_score: 0.2 }),
        mem({ id: 'm2', content: '低质量B', quality_score: 0.25 }),
      ],
      source_breakdown: BREAKDOWN,
      total: 2,
    });
  });

  it('选择模式显示复选框，选中后两步确认批量删除', async () => {
    batchDeleteMemoriesMock.mockResolvedValue({ deleted: 2, failed: [] });
    renderBrowser();
    await screen.findAllByText('低质量A', {}, { timeout: 5000 });

    // 未进入选择模式时没有复选框
    expect(screen.queryByTestId('memory-select-m1')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('memory-select-mode-toggle'));
    fireEvent.click(screen.getByTestId('memory-select-m1'));
    fireEvent.click(screen.getByTestId('memory-select-m2'));
    expect(screen.getByText('已选 2 条')).toBeInTheDocument();

    // 第一步：仅进入确认态，不发请求
    fireEvent.click(screen.getByTestId('memory-batch-delete'));
    expect(batchDeleteMemoriesMock).not.toHaveBeenCalled();
    expect(screen.getByText('即将删除 2 条记忆（不可撤销）')).toBeInTheDocument();

    // 第二步：确认后按所选类型批量提交
    fireEvent.click(screen.getByTestId('memory-batch-confirm'));
    await waitFor(() => expect(batchDeleteMemoriesMock).toHaveBeenCalledTimes(1), {
      timeout: 5000,
    });
    expect(batchDeleteMemoriesMock).toHaveBeenCalledWith([
      { id: 'm1', memory_type: 'episodic' },
      { id: 'm2', memory_type: 'episodic' },
    ]);
    await waitFor(() => expect(screen.queryAllByText('低质量A').length).toBe(0), {
      timeout: 5000,
    });
    expect(screen.queryAllByText('低质量B').length).toBe(0);
    expect(toast.success).toHaveBeenCalled();
  }, 20000);

  it('取消批量确认不发请求', async () => {
    renderBrowser();
    await screen.findAllByText('低质量A', {}, { timeout: 5000 });
    fireEvent.click(screen.getByTestId('memory-select-mode-toggle'));
    fireEvent.click(screen.getByTestId('memory-select-m1'));
    fireEvent.click(screen.getByTestId('memory-batch-delete'));
    fireEvent.click(screen.getByTestId('memory-batch-cancel'));

    expect(batchDeleteMemoriesMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('memory-batch-delete')).toBeInTheDocument();
    expect(screen.getAllByText('低质量A').length).toBeGreaterThan(0);
  }, 20000);

  it('部分失败时保留失败条目并汇总提示', async () => {
    batchDeleteMemoriesMock.mockResolvedValue({
      deleted: 1,
      failed: [{ id: 'm2', reason: 'store returned False (not found)' }],
    });
    renderBrowser();
    await screen.findAllByText('低质量A', {}, { timeout: 5000 });
    fireEvent.click(screen.getByTestId('memory-select-mode-toggle'));
    fireEvent.click(screen.getByTestId('memory-select-m1'));
    fireEvent.click(screen.getByTestId('memory-select-m2'));
    fireEvent.click(screen.getByTestId('memory-batch-delete'));
    fireEvent.click(screen.getByTestId('memory-batch-confirm'));

    await waitFor(() => expect(toast.warning).toHaveBeenCalled(), { timeout: 5000 });
    expect(screen.queryAllByText('低质量A').length).toBe(0);
    expect(screen.getAllByText('低质量B').length).toBeGreaterThan(0);
  }, 20000);

  it('低质量候选按钮调用 getQualityCandidates 并渲染候选', async () => {
    getQualityCandidatesMock.mockResolvedValue([
      {
        id: 'q1',
        content: '候选内容',
        memory_type: 'episodic',
        importance: 1,
        quality_score: 0.1,
        created_at_ms: 1700000000000,
        access_count: 0,
      },
    ]);
    renderBrowser();
    await screen.findAllByText('低质量A', {}, { timeout: 5000 });

    fireEvent.click(screen.getByTestId('memory-quality-candidates-toggle'));
    await waitFor(() => expect(getQualityCandidatesMock).toHaveBeenCalled(), { timeout: 5000 });
    expect(getQualityCandidatesMock).toHaveBeenCalledWith(50, 0.3);
    expect(await screen.findByText(/低质量候选 · 1 条/)).toBeInTheDocument();
    expect(screen.getAllByText('候选内容').length).toBeGreaterThan(0);
    expect(screen.queryAllByText('低质量A').length).toBe(0);
  }, 20000);
});

describe('MemoryBrowser 记忆级反馈（Task 4.5）', () => {
  it('episodic 行渲染 👍/👎，工作记忆行不渲染', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [mem({ id: 'e1' }), mem({ id: 'w1', source: 'working', memory_type: 'working' })],
      source_breakdown: BREAKDOWN,
      total: 2,
    });
    renderBrowser();
    await waitFor(() => expect(screen.getByTestId('memory-feedback-e1')).toBeInTheDocument(), {
      timeout: 5000,
    });
    expect(screen.getAllByTestId('memory-feedback-e1').length).toBeGreaterThan(0);
    expect(screen.queryByTestId('memory-feedback-w1')).not.toBeInTheDocument();
  }, 20000);

  it('点击 👍 调用 submitMemoryFeedback("up")', async () => {
    renderBrowser();
    const upBtn = await screen.findByTestId('memory-feedback-up-m1', {}, { timeout: 5000 });
    fireEvent.click(upBtn);
    await waitFor(() => expect(submitMemoryFeedbackMock).toHaveBeenCalled(), { timeout: 5000 });
    expect(submitMemoryFeedbackMock).toHaveBeenCalledWith('m1', 'up', {
      memoryType: 'episodic',
      reason: undefined,
    });
    await waitFor(() => expect(upBtn.getAttribute('aria-pressed')).toBe('true'));
  }, 20000);

  it('再次点击同一 👍 撤销为 neutral', async () => {
    renderBrowser();
    const upBtn = await screen.findByTestId('memory-feedback-up-m1', {}, { timeout: 5000 });
    fireEvent.click(upBtn);
    await waitFor(() => expect(upBtn.getAttribute('aria-pressed')).toBe('true'), { timeout: 5000 });
    fireEvent.click(upBtn);
    await waitFor(() => expect(submitMemoryFeedbackMock).toHaveBeenCalledTimes(2), {
      timeout: 5000,
    });
    expect(submitMemoryFeedbackMock).toHaveBeenLastCalledWith('m1', 'neutral', {
      memoryType: 'episodic',
      reason: undefined,
    });
    await waitFor(() => expect(upBtn.getAttribute('aria-pressed')).toBe('false'));
  }, 20000);

  it('点击 👎 后展开原因输入，回车带上 reason 提交', async () => {
    renderBrowser();
    const downBtn = await screen.findByTestId('memory-feedback-down-m1', {}, { timeout: 5000 });
    fireEvent.click(downBtn);
    await waitFor(() => expect(submitMemoryFeedbackMock).toHaveBeenCalledTimes(1), {
      timeout: 5000,
    });
    expect(submitMemoryFeedbackMock).toHaveBeenLastCalledWith('m1', 'down', {
      memoryType: 'episodic',
      reason: undefined,
    });

    const input = await screen.findByLabelText('反馈原因（可选）', {}, { timeout: 5000 });
    fireEvent.change(input, { target: { value: '内容过时' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(submitMemoryFeedbackMock).toHaveBeenCalledTimes(2), {
      timeout: 5000,
    });
    expect(submitMemoryFeedbackMock).toHaveBeenLastCalledWith('m1', 'down', {
      memoryType: 'episodic',
      reason: '内容过时',
    });
  }, 20000);

  it('列表带 user_feedback 时按钮呈现已反馈态', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [mem({ id: 'm1', user_feedback: 'down' })],
      source_breakdown: BREAKDOWN,
      total: 1,
    });
    renderBrowser();
    const downBtn = await screen.findByTestId('memory-feedback-down-m1', {}, { timeout: 5000 });
    expect(downBtn.getAttribute('aria-pressed')).toBe('true');
    const upBtn = screen.getByTestId('memory-feedback-up-m1');
    expect(upBtn.getAttribute('aria-pressed')).toBe('false');
  }, 20000);

  it('提交失败时回退状态并提示', async () => {
    submitMemoryFeedbackMock.mockRejectedValue(new Error('network'));
    renderBrowser();
    const upBtn = await screen.findByTestId('memory-feedback-up-m1', {}, { timeout: 5000 });
    fireEvent.click(upBtn);
    await waitFor(() => expect(toast.error).toHaveBeenCalled(), { timeout: 5000 });
    await waitFor(() => expect(upBtn.getAttribute('aria-pressed')).toBe('false'));
  }, 20000);
});
=======
>>>>>>> origin/main
