// @vitest-environment jsdom
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { displayModeStore } from '../../../features/chat/displayMode/displayModeStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const renderWithI18n = (ui: React.ReactElement) =>
  render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">{ui}</I18nProvider>
    </MemoryRouter>,
  );

/** 构造一条 assistant 消息（默认字段可被 overrides 覆盖）。 */
function assistantMessage(overrides: Partial<MessageType>): MessageType {
  return {
    id: 'm1',
    session_id: 's1',
    role: 'assistant',
    content: '最终结果。',
    created_at: 0,
    ...overrides,
  };
}

afterEach(() => {
  displayModeStore.clearAll();
});

describe('Message display modes — result summary bar', () => {
  it('collapses reasoning and tool calls into a single summary bar in result mode', () => {
    displayModeStore.setSession('s1', 'result');
    renderWithI18n(
      <Message
        message={assistantMessage({
          id: 'm-result-basic',
          reasoning_content: '先读文件再总结',
          tool_calls: [
            { name: 'read_file', args: { path: 'a.ts' }, result: 'alpha' },
            { name: 'web_search', args: { query: 'gamma' }, result: 'delta' },
          ],
        })}
      />,
    );

    const summary = screen.getByTestId('display-mode-result-summary');
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(summary).toHaveTextContent('已隐藏思考过程与 2 步工具调用');

    // 思考正文与工具卡片默认都不可见（内容没有丢，只是收进汇总条）
    expect(screen.queryByTestId('thinking-preview')).toBeNull();
    expect(screen.queryByText('先读文件再总结')).not.toBeInTheDocument();
    expect(screen.queryByText('a.ts')).not.toBeInTheDocument();
  });

  it('reveals the full detail in place with one click', () => {
    displayModeStore.setSession('s1', 'result');
    renderWithI18n(
      <Message
        message={assistantMessage({
          id: 'm-result-expand',
          reasoning_content: '展开后应看到这段思考正文',
          tool_calls: [
            { name: 'read_file', args: { path: 'expand-a.ts' }, result: 'alpha' },
            { name: 'web_search', args: { query: 'gamma' }, result: 'delta' },
          ],
        })}
      />,
    );

    const summary = screen.getByTestId('display-mode-result-summary');
    fireEvent.click(summary);

    expect(summary).toHaveAttribute('aria-expanded', 'true');
    expect(summary).toHaveTextContent('已展开明细');
    // 一次点击即可回看：思考面板默认展开（不是折叠态的 preview）
    expect(screen.queryByTestId('thinking-preview')).toBeNull();
    expect(screen.getByText('展开后应看到这段思考正文')).toBeInTheDocument();
    // 工具卡片全部就地出现
    expect(screen.getByText('expand-a.ts')).toBeInTheDocument();
  });

  it('never hides special (blocked) tool calls behind the summary bar', () => {
    displayModeStore.setSession('s1', 'result');
    renderWithI18n(
      <Message
        message={assistantMessage({
          id: 'm-result-blocked',
          reasoning_content: '尝试抓取页面',
          tool_calls: [
            {
              name: 'web_fetch',
              args: { url: 'https://example.test/page' },
              result: 'blocked',
              metadata: {
                blockReason: 'antibot_cf',
                blockedUrl: 'https://example.test/page',
              },
            },
          ],
        })}
      />,
    );

    // 不可分组的特殊调用：汇总条只覆盖思考过程
    const summary = screen.getByTestId('display-mode-result-summary');
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(summary).toHaveTextContent('已隐藏思考过程');
    expect(summary).not.toHaveTextContent('步工具调用');

    // 拦截卡片无需展开即可见（spec §3.4）
    expect(screen.getByTestId('blocked-card')).toBeInTheDocument();
  });

  it('leaves detail/trace modes untouched (group toggle still drives tool cards)', () => {
    renderWithI18n(
      <Message
        message={assistantMessage({
          id: 'm-trace',
          tool_calls: [
            { name: 'read_file', args: { path: 'trace-a.ts' }, result: 'alpha' },
            { name: 'read_file', args: { path: 'trace-b.ts' }, result: 'beta' },
            { name: 'web_search', args: { query: 'gamma' }, result: 'delta' },
          ],
        })}
      />,
    );

    // 默认档位是 trace，工具组默认展开，且不出现 result 汇总条
    const toggle = screen.getByTestId('tool-calls-group-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByTestId('display-mode-result-summary')).toBeNull();
    expect(screen.getByText('trace-a.ts')).toBeInTheDocument();
  });

  it('collapses already-expanded tool cards when the session switches to result', () => {
    renderWithI18n(
      <Message
        message={assistantMessage({
          id: 'm-switch-to-result',
          reasoning_content: '切换前已展开',
          tool_calls: [
            { name: 'read_file', args: { path: 'switch-a.ts' }, result: 'alpha' },
            { name: 'read_file', args: { path: 'switch-b.ts' }, result: 'beta' },
            { name: 'web_search', args: { query: 'gamma' }, result: 'delta' },
          ],
        })}
      />,
    );

    // trace 档工具组默认展开 —— 卡片可见
    expect(screen.getByText('switch-a.ts')).toBeInTheDocument();

    // 切到 result 档后，已挂载的历史消息也必须立即生效（验收标准 #1）：
    // 卡片收起，汇总条如实报告被隐藏的内容
    act(() => {
      displayModeStore.setSession('s1', 'result');
    });

    expect(screen.getByTestId('display-mode-result-summary')).toHaveTextContent(
      '已隐藏思考过程与 3 步工具调用',
    );
    expect(screen.queryByText('switch-a.ts')).not.toBeInTheDocument();
  });

  it('renders no summary bar when there is nothing to hide', () => {
    displayModeStore.setSession('s1', 'result');
    renderWithI18n(
      <Message message={assistantMessage({ id: 'm-result-empty', content: '只有一个结果。' })} />,
    );

    expect(screen.queryByTestId('display-mode-result-summary')).toBeNull();
  });
});
