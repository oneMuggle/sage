// src/widgets/chat/__tests__/ConversationOutline.test.tsx
//
// P2-3.10: 验证对话目录组件的渲染逻辑。
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { OutlineItem } from '../../../features/chat/useConversationOutline';
import { ConversationOutline } from '../ConversationOutline';

describe('ConversationOutline', () => {
  it('shows loading state', () => {
    render(<ConversationOutline items={[]} isLoading={true} />);
    expect(screen.getByText('加载中…')).toBeInTheDocument();
  });

  it('shows empty state when no items', () => {
    render(<ConversationOutline items={[]} isLoading={false} />);
    expect(screen.getByText('暂无目录')).toBeInTheDocument();
    expect(screen.getByText(/h2\/h3 标题会自动生成目录/)).toBeInTheDocument();
  });

  it('renders h2 items with font-medium', () => {
    const items: OutlineItem[] = [{ text: '简介', messageId: 'm1', level: 2 }];
    render(<ConversationOutline items={items} isLoading={false} />);
    const button = screen.getByText('简介');
    expect(button).toBeInTheDocument();
    expect(button.className).toContain('font-medium');
    expect(button.className).not.toContain('pl-7');
  });

  it('renders h3 items with indent and font-normal', () => {
    const items: OutlineItem[] = [{ text: '背景', messageId: 'm1', level: 3 }];
    render(<ConversationOutline items={items} isLoading={false} />);
    const button = screen.getByText('背景');
    expect(button).toBeInTheDocument();
    expect(button.className).toContain('font-normal');
    expect(button.className).toContain('pl-7');
  });

  it('renders multiple items with correct testids', () => {
    const items: OutlineItem[] = [
      { text: '第一项', messageId: 'm1', level: 2 },
      { text: '子项', messageId: 'm1', level: 3 },
      { text: '第二项', messageId: 'm2', level: 2 },
    ];
    render(<ConversationOutline items={items} isLoading={false} />);
    expect(screen.getByTestId('conversation-outline')).toBeInTheDocument();
    expect(screen.getByTestId('outline-item-0')).toHaveTextContent('第一项');
    expect(screen.getByTestId('outline-item-1')).toHaveTextContent('子项');
    expect(screen.getByTestId('outline-item-2')).toHaveTextContent('第二项');
  });

  it('handles long titles with truncate', () => {
    const items: OutlineItem[] = [
      {
        text: '这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的标题',
        messageId: 'm1',
        level: 2,
      },
    ];
    render(<ConversationOutline items={items} isLoading={false} />);
    const button = screen.getByText(/这是一个非常/);
    expect(button.className).toContain('truncate');
  });

  it('A2: clicking an item reports it with its heading index inside the message', () => {
    const items: OutlineItem[] = [
      { text: '第一项', messageId: 'm1', level: 2 },
      { text: '第二项', messageId: 'm2', level: 2 },
      { text: '子项', messageId: 'm1', level: 3 },
    ];
    const onSelect = vi.fn();
    render(<ConversationOutline items={items} isLoading={false} onSelect={onSelect} />);

    fireEvent.click(screen.getByTestId('outline-item-2'));
    expect(onSelect).toHaveBeenLastCalledWith(items[2], 1);
    fireEvent.click(screen.getByTestId('outline-item-1'));
    expect(onSelect).toHaveBeenLastCalledWith(items[1], 0);
  });

  it('A2: items stay inert without onSelect', () => {
    const items: OutlineItem[] = [{ text: '简介', messageId: 'm1', level: 2 }];
    render(<ConversationOutline items={items} isLoading={false} />);
    expect(() => fireEvent.click(screen.getByTestId('outline-item-0'))).not.toThrow();
  });

  it('copies conversation outline as Markdown and JSON to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const items: OutlineItem[] = [
      { text: '简介', messageId: 'm1', level: 2 },
      { text: '细节', messageId: 'm1', level: 3 },
    ];
    render(<ConversationOutline items={items} isLoading={false} />);

    fireEvent.click(screen.getByTestId('conversation-outline-copy-md-btn'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining('# 对话大纲目录'));
    });

    fireEvent.click(screen.getByTestId('conversation-outline-copy-json-btn'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining('"简介"'));
    });
  });
});
