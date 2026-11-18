/**
 * MemoryItemCard 测试（2026-11-17 记忆详情化）。
 *
 * 覆盖：标题优先级 / 折叠-展开全文 / 选择模式互斥 / 内联编辑保存。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Memory } from '../../../shared/api';
import { MemoryItemCard } from '../MemoryItemCard';

vi.mock('../../../shared/api', () => ({
  memoryApi: {
    submitMemoryFeedback: vi.fn().mockResolvedValue(undefined),
  },
  sessionApi: {
    get: vi.fn().mockRejectedValue(new Error('not found')),
  },
}));

vi.mock('sonner', () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const LONG_CONTENT = `用户偏好函数式编程\n${'这是很长的记忆正文。'.repeat(20)}`;

function mem(overrides: Partial<Memory> = {}): Memory {
  return {
    id: 'm1',
    content: LONG_CONTENT,
    source: 'episodic',
    scope: 'user',
    created_at_ms: 1700000000000,
    importance: 8,
    access_count: 2,
    tags: [],
    ...overrides,
  } as Memory;
}

function renderCard(props: Partial<Parameters<typeof MemoryItemCard>[0]> = {}) {
  return render(
    <MemoryItemCard
      memory={mem()}
      onJumpToSession={() => undefined}
      onDelete={() => undefined}
      {...props}
    />,
  );
}

describe('MemoryItemCard 标题与折叠态', () => {
  it('标题取首个非空行，长内容显示详情入口', () => {
    renderCard();
    expect(screen.getByTestId('memory-title-m1').textContent).toBe('用户偏好函数式编程');
    expect(screen.getByTestId('memory-toggle-m1')).toBeInTheDocument();
    // 折叠态不渲染全文容器
    expect(screen.queryByTestId('memory-full-content-m1')).not.toBeInTheDocument();
  });

  it('优先使用后端下发的 title 字段', () => {
    renderCard({ memory: mem({ title: '后端生成的短标题' }) });
    expect(screen.getByTestId('memory-title-m1').textContent).toBe('后端生成的短标题');
  });

  it('内容很短时预览即全文，详情按钮禁用', () => {
    renderCard({ memory: mem({ content: '短短一条' }) });
    // 标题与预览各渲染一次
    expect(screen.getAllByText('短短一条').length).toBeGreaterThan(0);
    expect(screen.getByTestId('memory-toggle-m1')).toBeDisabled();
  });
});

describe('MemoryItemCard 展开/收起', () => {
  it('点击卡片展开全文，再次点击收起（保留换行）', () => {
    renderCard();
    const card = screen.getByTestId('memory-episodic-item');
    fireEvent.click(card);
    const full = screen.getByTestId('memory-full-content-m1');
    expect(full.textContent).toBe(LONG_CONTENT);
    expect(full.className).toContain('whitespace-pre-wrap');

    fireEvent.click(card);
    expect(screen.queryByTestId('memory-full-content-m1')).not.toBeInTheDocument();
  });

  it('编辑态输入框的空格/回车不会被卡片切换逻辑吞掉', () => {
    renderCard({ onUpdate: vi.fn().mockResolvedValue(undefined) });
    fireEvent.click(screen.getByTestId('memory-edit-m1'));
    const contentArea = screen.getByTestId('memory-edit-content-m1');
    // 卡片外层不再拦截键盘事件：编辑框保持焦点、卡片保持展开
    fireEvent.keyDown(contentArea, { key: ' ' });
    fireEvent.keyDown(contentArea, { key: 'Enter' });
    expect(screen.getByTestId('memory-edit-content-m1')).toBeInTheDocument();
  });

  it('详情按钮通过 aria-expanded 暴露展开状态', () => {
    renderCard();
    const toggle = screen.getByTestId('memory-toggle-m1');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
  });

  it('选择模式下点击卡片只触发勾选，不展开', () => {
    const onToggleSelect = vi.fn();
    renderCard({ selectable: true, onToggleSelect });
    fireEvent.click(screen.getByTestId('memory-episodic-item'));
    expect(onToggleSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('memory-full-content-m1')).not.toBeInTheDocument();
  });

  it('折叠态显示正文真实字数', () => {
    renderCard();
    expect(screen.getByText(new RegExp(`${LONG_CONTENT.length} 字`))).toBeInTheDocument();
  });
});

describe('MemoryItemCard 内联编辑', () => {
  it('编辑并保存时调用 onUpdate（content + title）', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderCard({ onUpdate });

    fireEvent.click(screen.getByTestId('memory-edit-m1'));
    const titleInput = screen.getByTestId('memory-edit-title-m1') as HTMLInputElement;
    const contentArea = screen.getByTestId('memory-edit-content-m1') as HTMLTextAreaElement;
    expect(contentArea.value).toBe(LONG_CONTENT);

    fireEvent.change(titleInput, { target: { value: '新标题' } });
    fireEvent.change(contentArea, { target: { value: '修正后的记忆内容' } });
    fireEvent.click(screen.getByTestId('memory-edit-save-m1'));

    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }), {
        content: '修正后的记忆内容',
        title: '新标题',
      }),
    );
  });

  it('只改内容不改标题时，补丁不含 title（由后端按新内容重推）', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderCard({ onUpdate });

    fireEvent.click(screen.getByTestId('memory-edit-m1'));
    fireEvent.change(screen.getByTestId('memory-edit-content-m1'), {
      target: { value: '只改内容' },
    });
    fireEvent.click(screen.getByTestId('memory-edit-save-m1'));

    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }), {
        content: '只改内容',
      }),
    );
  });

  it('保存失败时停留在编辑态并提示', async () => {
    const onUpdate = vi.fn().mockRejectedValue(new Error('db down'));
    renderCard({ onUpdate });

    fireEvent.click(screen.getByTestId('memory-edit-m1'));
    fireEvent.change(screen.getByTestId('memory-edit-content-m1'), {
      target: { value: '新内容' },
    });
    fireEvent.click(screen.getByTestId('memory-edit-save-m1'));

    await waitFor(() => expect(onUpdate).toHaveBeenCalled());
    const { toast } = await import('sonner');
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByTestId('memory-edit-content-m1')).toBeInTheDocument();
  });

  it('未传 onUpdate 时不渲染编辑按钮（向后兼容）', () => {
    renderCard();
    expect(screen.queryByTestId('memory-edit-m1')).not.toBeInTheDocument();
  });

  it('working 记忆不渲染编辑按钮（与反馈同口径）', () => {
    const onUpdate = vi.fn();
    renderCard({ memory: mem({ source: 'working' }), onUpdate });
    expect(screen.queryByTestId('memory-edit-m1')).not.toBeInTheDocument();
  });
});
