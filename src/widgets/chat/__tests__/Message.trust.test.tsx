/**
 * R17 批次 —— Message 气泡信任感交互测试
 *
 * - A: 复制按钮恒显（不再被 onFeedback 门控劫持）
 * - B: 删除按钮两步确认（TwoStepDelete）+ 流式中不显示
 * - E: memory_used 记忆召回明细可展开
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

const makeMsg = (patch: Partial<MessageType> = {}): MessageType => ({
  id: 'm1',
  session_id: 's1',
  role: 'assistant',
  content: '这是回答内容',
  created_at: 0,
  ...patch,
});

describe('Message — R17 信任感交互', () => {
  it('A: 无 onFeedback 时复制按钮仍然显示（旧实现被 onFeedback 劫持为死区）', () => {
    renderWithI18n(<Message message={makeMsg()} />);
    expect(screen.getByTestId('copy-message')).toBeInTheDocument();
  });

  it('A: 点击复制写入剪贴板并进入已复制态', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderWithI18n(<Message message={makeMsg()} />);
    fireEvent.click(screen.getByTestId('copy-message'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('这是回答内容'));
  });

  it('A: 流式中的消息不显示复制按钮（内容未定型）', () => {
    renderWithI18n(<Message message={makeMsg()} isStreaming />);
    expect(screen.queryByTestId('copy-message')).not.toBeInTheDocument();
  });

  it('B: 删除需两步确认 —— 第一次点击 armed，第二次才回调', () => {
    const onDelete = vi.fn();
    renderWithI18n(<Message message={makeMsg()} onDelete={onDelete} />);
    const btn = screen.getByTestId('delete-message');
    fireEvent.click(btn);
    expect(onDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('delete-message'));
    expect(onDelete).toHaveBeenCalledWith('m1');
  });

  it('B: 未传 onDelete 时不渲染删除按钮', () => {
    renderWithI18n(<Message message={makeMsg()} />);
    expect(screen.queryByTestId('delete-message')).not.toBeInTheDocument();
  });

  it('E: memory_applied > 0 显示可展开的记忆召回开关', () => {
    const msg = makeMsg({
      memory_applied: 2,
      memory_refs: [
        { id: 'a', memory_type: 'semantic', preview: '用户偏好深色主题' },
        { id: 'b', memory_type: 'working', preview: '正在做记忆功能' },
      ],
    });
    renderWithI18n(<Message message={msg} />);
    expect(screen.getByTestId('memory-used-toggle')).toHaveTextContent('2');
    // 默认收起；点击展开后逐条可见
    expect(screen.queryByTestId('memory-used-list')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('memory-used-toggle'));
    const list = screen.getByTestId('memory-used-list');
    expect(list).toHaveTextContent('用户偏好深色主题');
    expect(list).toHaveTextContent('正在做记忆功能');
  });

  it('E: 无 memory_applied 时不显示记忆开关', () => {
    renderWithI18n(<Message message={makeMsg()} />);
    expect(screen.queryByTestId('memory-used-toggle')).not.toBeInTheDocument();
  });
});
