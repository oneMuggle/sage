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

  // R38: 技能激活与上下文压缩透明度测试
  it('R38: activated_skills 存在时显示可展开的技能激活开关', () => {
    const msg = makeMsg({
      role: 'user',
      activated_skills: [
        { name: 'code-reviewer', triggers_matched: ['审查代码'] },
        { name: 'tdd-guide', triggers_matched: ['测试'] },
      ],
    });
    renderWithI18n(<Message message={msg} />);
    expect(screen.getByTestId('skill-activated-toggle')).toHaveTextContent('2');
    // 默认收起；点击展开后逐条可见
    expect(screen.queryByTestId('skill-activated-list')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('skill-activated-toggle'));
    const list = screen.getByTestId('skill-activated-list');
    expect(list).toHaveTextContent('code-reviewer');
    expect(list).toHaveTextContent('tdd-guide');
  });

  it('R38: 无 activated_skills 时不显示技能激活开关', () => {
    renderWithI18n(<Message message={makeMsg({ role: 'user' })} />);
    expect(screen.queryByTestId('skill-activated-toggle')).not.toBeInTheDocument();
  });

  it('R38: role=system 且含 compact_info 时渲染居中的压缩系统提示', () => {
    const msg = makeMsg({
      role: 'system',
      // LOW-1: 统一口径
      content: '📦 上下文已压缩：20 → 8 条（12 条历史已合并为摘要）',
      compact_info: { before: 20, after: 8, removed: 12 },
    });
    renderWithI18n(<Message message={msg} />);
    expect(screen.getByText(/上下文已压缩：20 → 8 条/)).toBeInTheDocument();
    // 系统提示不应渲染用户/助手头像
    expect(screen.queryByText('U')).not.toBeInTheDocument();
    expect(screen.queryByText('S')).not.toBeInTheDocument();
  });

  it('R38: assistant 续接行 —— 横幅在气泡上方, 摘要正文与操作按钮仍保留', () => {
    const msg = makeMsg({
      role: 'assistant',
      content: '这是 LLM 写的摘要正文',
      compact_info: { before: 20, after: 8, removed: 12 },
    });
    renderWithI18n(<Message message={msg} />);
    // 横幅出现
    expect(screen.getByTestId('compact-banner')).toBeInTheDocument();
    // 摘要正文（assistant 气泡）仍在
    expect(screen.getByText('这是 LLM 写的摘要正文')).toBeInTheDocument();
    // affordance 未丢失
    expect(screen.getByTestId('copy-message')).toBeInTheDocument();
  });

  it('R38: 无 compact_info 时不渲染横幅', () => {
    renderWithI18n(<Message message={makeMsg()} />);
    expect(screen.queryByTestId('compact-banner')).not.toBeInTheDocument();
  });
});
