/**
 * P0 交互欠账的前端覆盖：行内三态循环 + 行内详情面板编辑 + 状态筛选。
 *
 * 三条链路分别打：
 * - 三态循环：pending → in_progress → completed → pending，走 PUT 的
 *   ``status`` 字段（后端在 completed 时分派到 complete_todo）；
 * - 详情面板：失焦提交描述/截止/项目/标签，优先级/提醒/负责人点一下即提交，
 *   清空必须发 ``null``（IPC 的 JSON 序列化会丢掉 undefined）；
 * - 状态筛选：与智能视图互斥（后端 view 优先于 status）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Todo, TodoListParams } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TodoDetailPanel } from '../TodoDetailPanel';
import { TodoRowEditor } from '../TodoRowEditor';
import { TodoToolbar } from '../TodoToolbar';

const mocks = vi.hoisted(() => ({
  confirmDialog: vi.fn(),
  listTags: vi.fn(),
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirmDialog,
}));

// 工具栏启动时会拉标签清单（失败静默降级）——这里直接给空清单。
vi.mock('../../../shared/api/todoClient', () => ({
  todoClient: { listTags: mocks.listTags },
}));

const todo = (overrides: Partial<Todo> = {}): Todo => ({
  id: 7,
  title: '买牛奶',
  status: 'pending',
  priority: 'medium',
  is_recurring: false,
  created_at: '2026-09-21T00:00:00',
  updated_at: '2026-09-21T00:00:00',
  ...overrides,
});

function renderRow(overrides: Partial<Parameters<typeof TodoRowEditor>[0]> = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ul>
        <TodoRowEditor
          todo={todo()}
          selected={false}
          onSelect={vi.fn()}
          onUpdate={vi.fn().mockResolvedValue(undefined)}
          onComplete={vi.fn().mockResolvedValue(undefined)}
          onCancel={vi.fn().mockResolvedValue(undefined)}
          onDelete={vi.fn().mockResolvedValue(undefined)}
          {...overrides}
        />
      </ul>
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listTags.mockResolvedValue([]);
});

describe('TodoRowEditor — 三态循环', () => {
  it('未开始 → 进行中', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ onUpdate });

    fireEvent.click(screen.getByTestId('todo-status-7'));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(7, { status: 'in_progress' }));
  });

  it('进行中 → 已完成', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ todo: todo({ status: 'in_progress' }), onUpdate });

    fireEvent.click(screen.getByTestId('todo-status-7'));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(7, { status: 'completed' }));
  });

  it('已完成 → 未开始（重新打开）', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ todo: todo({ status: 'completed' }), onUpdate });

    fireEvent.click(screen.getByTestId('todo-status-7'));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(7, { status: 'pending' }));
  });

  it('已取消不在循环内 —— 不发任何更新', () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ todo: todo({ status: 'cancelled' }), onUpdate });

    fireEvent.click(screen.getByTestId('todo-status-7'));

    expect(onUpdate).not.toHaveBeenCalled();
  });

  it('进行中的行有左侧主色竖条', () => {
    const { rerender } = renderRow({ todo: todo({ status: 'in_progress' }) });
    expect(screen.getByTestId('todo-in-progress-bar-7')).toBeInTheDocument();

    rerender(
      <I18nProvider defaultLocale="zh">
        <ul>
          <TodoRowEditor
            todo={todo({ status: 'pending' })}
            selected={false}
            onSelect={vi.fn()}
            onUpdate={vi.fn().mockResolvedValue(undefined)}
            onComplete={vi.fn().mockResolvedValue(undefined)}
            onCancel={vi.fn().mockResolvedValue(undefined)}
            onDelete={vi.fn().mockResolvedValue(undefined)}
          />
        </ul>
      </I18nProvider>,
    );
    expect(screen.queryByTestId('todo-in-progress-bar-7')).toBeNull();
  });
});

describe('TodoRowEditor — 行内详情面板', () => {
  it('点详情开关展开面板，再点收起', async () => {
    renderRow();

    expect(screen.queryByTestId('todo-detail-panel-7')).toBeNull();
    fireEvent.click(screen.getByTestId('todo-detail-toggle-7'));
    expect(await screen.findByTestId('todo-detail-panel-7')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('todo-detail-close-7'));
    await waitFor(() => expect(screen.queryByTestId('todo-detail-panel-7')).toBeNull());
  });

  it('描述失焦才落库', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ todo: todo({ description: '旧的' }), onUpdate });

    fireEvent.click(screen.getByTestId('todo-detail-toggle-7'));
    const textarea = await screen.findByTestId('detail-todo-description');

    fireEvent.change(textarea, { target: { value: '新的描述' } });
    expect(onUpdate).not.toHaveBeenCalled();

    fireEvent.blur(textarea);
    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(7, { description: '新的描述' }),
    );
  });

  it('清空描述必须发 null（发 undefined 等于「不动」）', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ todo: todo({ description: '旧的' }), onUpdate });

    fireEvent.click(screen.getByTestId('todo-detail-toggle-7'));
    const textarea = await screen.findByTestId('detail-todo-description');

    fireEvent.change(textarea, { target: { value: '' } });
    fireEvent.blur(textarea);

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(7, { description: null }));
  });

  it('优先级点一下立即落库', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ onUpdate });

    fireEvent.click(screen.getByTestId('todo-detail-toggle-7'));
    fireEvent.click(await screen.findByTestId('detail-todo-priority-high'));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(7, { priority: 'high' }));
  });

  it('标签按逗号/空白切开并落库', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ onUpdate });

    fireEvent.click(screen.getByTestId('todo-detail-toggle-7'));
    const input = await screen.findByTestId('detail-todo-tags');

    fireEvent.change(input, { target: { value: '工作, 论文' } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(7, { tags: ['工作', '论文'] }),
    );
  });

  it('收起面板时兜底提交还没失焦的字段', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ onUpdate });

    fireEvent.click(screen.getByTestId('todo-detail-toggle-7'));
    const textarea = await screen.findByTestId('detail-todo-description');
    fireEvent.change(textarea, { target: { value: '没失焦就收起' } });

    fireEvent.click(screen.getByTestId('todo-detail-close-7'));

    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(7, { description: '没失焦就收起' }),
    );
  });

  it('已落库的字段不会因为收起面板被重复写', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderRow({ todo: todo({ description: '旧的' }), onUpdate });

    fireEvent.click(screen.getByTestId('todo-detail-toggle-7'));
    const textarea = await screen.findByTestId('detail-todo-description');
    fireEvent.change(textarea, { target: { value: '新的描述' } });
    fireEvent.blur(textarea);
    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('todo-detail-close-7'));

    await waitFor(() => expect(screen.queryByTestId('todo-detail-panel-7')).toBeNull());
    expect(onUpdate).toHaveBeenCalledTimes(1);
  });

  it('写库失败时回滚该字段并显示错误', async () => {
    const onUpdate = vi.fn().mockRejectedValue(new Error('后端炸了'));
    renderRow({ todo: todo({ description: '旧的' }), onUpdate });

    fireEvent.click(screen.getByTestId('todo-detail-toggle-7'));
    const textarea = await screen.findByTestId('detail-todo-description');
    fireEvent.change(textarea, { target: { value: '新的描述' } });
    fireEvent.blur(textarea);

    expect(await screen.findByTestId('todo-detail-error-7')).toHaveTextContent('后端炸了');
    await waitFor(() => expect((textarea as HTMLTextAreaElement).value).toBe('旧的'));
  });
});

describe('TodoDetailPanel — 截止日期清空', () => {
  it('清空截止日期发 null', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(
      <I18nProvider defaultLocale="zh">
        <TodoDetailPanel
          todo={todo({ due_at: '2026-12-01T09:00:00' })}
          onUpdate={onUpdate}
          onClose={vi.fn()}
        />
      </I18nProvider>,
    );

    const input = await screen.findByTestId('detail-todo-due-at');
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.blur(input);

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(7, { due_at: null }));
  });
});

describe('TodoToolbar — 状态筛选', () => {
  function renderToolbar(params: TodoListParams = {}) {
    const onParamsChange = vi.fn();
    render(
      <TodoToolbar
        params={params}
        searchQuery=""
        onParamsChange={onParamsChange}
        onSearchChange={vi.fn()}
      />,
    );
    return onParamsChange;
  }

  it('选中状态时带上 status 参数', () => {
    const onParamsChange = renderToolbar();

    fireEvent.change(screen.getByTestId('todo-status-filter'), {
      target: { value: 'in_progress' },
    });

    expect(onParamsChange).toHaveBeenCalledWith({ status: 'in_progress' });
  });

  it('与智能视图互斥：切状态会清掉 view', () => {
    const onParamsChange = renderToolbar({ view: 'today' });

    fireEvent.change(screen.getByTestId('todo-status-filter'), {
      target: { value: 'pending' },
    });

    const next = onParamsChange.mock.calls[0][0] as TodoListParams;
    expect(next.status).toBe('pending');
    expect(next.view).toBeUndefined();
    expect(next.include_completed).toBeUndefined();
  });

  it('反向互斥：切视图会清掉 status', () => {
    const onParamsChange = renderToolbar({ status: 'pending' });

    fireEvent.click(screen.getByRole('button', { name: '今天' }));

    const next = onParamsChange.mock.calls[0][0] as TodoListParams;
    expect(next.view).toBe('today');
    expect(next.status).toBeUndefined();
  });

  it('状态筛选生效时智能视图按钮全部呈现未选中', () => {
    renderToolbar({ status: 'pending' });

    for (const label of ['全部', '今天', '近7天', '已完成']) {
      expect(screen.getByRole('button', { name: label })).toHaveAttribute(
        'aria-pressed',
        'false',
      );
    }
  });

  it('选回「不限状态」时删掉 status 参数', () => {
    const onParamsChange = renderToolbar({ status: 'pending' });

    fireEvent.change(screen.getByTestId('todo-status-filter'), {
      target: { value: '' },
    });

    const next = onParamsChange.mock.calls[0][0] as TodoListParams;
    expect(next.status).toBeUndefined();
  });

  it('状态筛选存在时「清除」按钮出现', () => {
    renderToolbar({ status: 'pending' });
    expect(screen.getByRole('button', { name: '清除所有过滤条件' })).toBeInTheDocument();
  });
});
