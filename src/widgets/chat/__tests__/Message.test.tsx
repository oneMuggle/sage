import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

// M4: Message 内部使用 useI18n（fork 按钮 title），测试必须挂 provider
const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('Message', () => {
  it('renders plain text content', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '你好！',
      created_at: 0,
    };
    renderWithI18n(<Message message={msg} />);
    expect(screen.getByText('你好！')).toBeInTheDocument();
  });

  it('renders tool_call indicator', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '观察中...',
      created_at: 0,
      tool_calls: [
        {
          name: 'read_file',
          args: { path: '/tmp/foo2' },
          result: 'content with 2',
        },
      ],
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    expect(container.textContent).toContain('Read');
    expect(container.textContent).toContain('2');
  });

  it('renders humanized tool call title instead of raw args dump (U8)', () => {
    // Arrange
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '正在写文件...',
      created_at: 0,
      tool_calls: [{ name: 'write_file', args: { path: 'src/App.tsx', content: 'export {}' } }],
    };

    // Act
    const { container } = renderWithI18n(<Message message={msg} />);

    // Assert — 人性化标题 + 文件名（专用渲染器不显示原始工具名）
    expect(container.textContent).toContain('Write');
    expect(container.textContent).toContain('src/App.tsx');
    // 原始 args JSON dump 不再渲染（write_file 的 content 会撑爆卡片）
    expect(container.textContent).not.toContain('export {}');
    expect(container.textContent).not.toContain('{"path"');
  });

  it('shows search tool card for web tools (ZCode-inspired)', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '搜索中...',
      created_at: 0,
      tool_calls: [{ name: 'web_search', args: { query: 'tauri v2' } }],
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    expect(container.textContent).toContain('Search');
    expect(container.textContent).toContain('tauri v2');
  });

  it('applies error style when content starts with [错误', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '[错误:auth_failed] API Key 无效',
      created_at: 0,
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    const errorEl = container.querySelector('[data-error="true"]');
    expect(errorEl).toBeInTheDocument();
  });

  it('message row does not constrain to max-w-[720px] (full-width layout)', () => {
    // Regression for "对话区域没有占满": previously Message.tsx had
    // `max-w-[720px]` on the row, leaving a big empty right side.
    // Width should now come from the MessageList container.
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: 'hi',
      created_at: 0,
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    const row = container.firstChild as HTMLElement;
    expect(row.className).not.toMatch(/max-w-\[720px\]/);
    expect(row.className).toMatch(/\bw-full\b/);
  });

  it('message bubble caps width with max-w-2xl (so text stays readable)', () => {
    // PR-7b: width constraint moved from MessageList wrapper to the bubble
    // itself, so the panel uses full width but text doesn't get too wide.
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: 'hi',
      created_at: 0,
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    // 找 data-error 属性所在的 div(就是气泡)
    const bubble = container.querySelector('div[class*="max-w-2xl"]');
    expect(bubble).toBeTruthy();
  });
});

describe('ThinkingPanel', () => {
  it('renders reasoning_content when present', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '答案是 42',
      created_at: 0,
      reasoning_content: '让我思考一下：6 * 7 = 42',
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    // 应该渲染思考过程按钮
    expect(container.textContent).toContain('思考过程');
    expect(container.textContent).toContain('17'); // 字符数
  });

  it('does not render thinking panel when reasoning_content is absent', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '你好！',
      created_at: 0,
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    // 不应该渲染思考过程按钮
    expect(container.textContent).not.toContain('思考过程');
  });

  it('does not render thinking panel for user messages', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'user',
      content: '你好',
      created_at: 0,
      reasoning_content: '这不是用户的思考过程',
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    // 用户消息不应该渲染思考过程面板
    expect(container.textContent).not.toContain('思考过程');
  });

  it('shows a folded preview and keeps expanded state across remount (id replacement)', () => {
    const reasoning = '第一行思考摘要\n第二行更详细的推理内容';
    const msg: MessageType = {
      id: 'temp-id',
      session_id: 's',
      role: 'assistant',
      content: '答案',
      created_at: 0,
      reasoning_content: reasoning,
    };
    const { container, unmount } = renderWithI18n(<Message message={msg} />);

    // 默认折叠：头部有首行预览，正文不展示
    expect(screen.getByTestId('thinking-preview').textContent).toContain('第一行思考摘要');
    expect(container.textContent).not.toContain('第二行更详细的推理内容');

    fireEvent.click(screen.getByRole('button', { name: /思考过程/ }));
    expect(screen.getByRole('button', { name: /思考过程/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(container.textContent).toContain('第二行更详细的推理内容');

    // 模拟流结束后的服务端 id 替换：组件重挂载，展开态应保留
    unmount();
    const { container: remounted } = renderWithI18n(
      <Message message={{ ...msg, id: 'server-id' }} />,
    );
    expect(remounted.textContent).toContain('第二行更详细的推理内容');
  });

  it('expands thinking panel on click', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '答案',
      created_at: 0,
      reasoning_content: '这是思考内容\n这是隐藏细节',
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    // 点击展开
    const button = container.querySelector('button');
    expect(button).toBeInTheDocument();
    // 初始状态：折叠；头部只显示首行预览，正文细节不可见
    expect(container.textContent).toContain('这是思考内容');
    expect(container.textContent).not.toContain('这是隐藏细节');
    // 点击按钮
    fireEvent.click(button!);
    // 展开后：完整思考内容可见
    expect(container.textContent).toContain('这是隐藏细节');
  });
});

describe('ToolCallResultDefensiveRender', () => {
  // 回归测试 (2026-09-17 win7 安装包): 后端历史 bug 让 tc.result 在运行时
  // 是 dict 而非字符串,前端直接渲染 dict 会触发 React error #31
  // "Objects are not valid as a React child (found: object with keys {...})".
  // ToolCallResult 组件现在用 typeof 守卫把 unknown → JSON 字符串。

  it('renders dict-shaped tool result as JSON string without throwing', () => {
    const msg = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '工具调用失败',
      created_at: 0,
      tool_calls: [
        {
          name: 'execute_code',
          args: { code: 'x = 1' },
          // 故意传 dict 而非 str: 模拟后端历史 bug（dict 穿透到 React 渲染）
          result: { error: '子进程异常退出', exit_code: 137, stderr: 'FATAL' },
        },
      ],
    } as unknown as MessageType;
    expect(() => renderWithI18n(<Message message={msg} />)).not.toThrow();
    const { container } = renderWithI18n(<Message message={msg} />);
    // result 必须被 JSON 序列化展示,不能直接渲染对象
    expect(container.textContent).toContain('子进程异常退出');
    expect(container.textContent).toContain('137');
  });

  it('renders string tool result unchanged', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '工具返回',
      created_at: 0,
      tool_calls: [{ name: 'read_file', args: {}, result: '42' }],
    };
    const { container } = renderWithI18n(<Message message={msg} />);
    expect(container.textContent).toContain('42');
  });

  it('renders null tool result as empty (no crash)', () => {
    const msg = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '工具返回',
      created_at: 0,
      tool_calls: [{ name: 'read_file', args: {}, result: null }],
    } as unknown as MessageType;
    expect(() => renderWithI18n(<Message message={msg} />)).not.toThrow();
  });

  it('formats Message audit summary and JSON (Phase P119)', async () => {
<<<<<<< HEAD
    const { formatMessageAuditSummary, formatMessageAuditJson } = await import('../Message');
=======
    const { formatMessageAuditSummary, formatMessageAuditJson } = await import('../messageAudit');
>>>>>>> origin/main
    const msg: MessageType = {
      id: 'm1',
      session_id: 's1',
      role: 'assistant',
      content: 'hello world',
      created_at: 0,
      tool_calls: [{ name: 'read_file', args: {}, result: 'ok' }],
    };
    expect(formatMessageAuditSummary(msg, false)).toBe(
      'm1 · role=assistant · streaming=false · tools=1 · chars=11',
    );
    expect(JSON.parse(formatMessageAuditJson(msg, false))).toEqual({
      id: 'm1',
      role: 'assistant',
      isStreaming: false,
      toolCallCount: 1,
      contentLength: 11,
    });
  });
});
