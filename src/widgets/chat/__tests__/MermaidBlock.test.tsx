/**
 * U7' (对标增强第五轮批次 A): MermaidBlock 渲染测试
 *
 * mermaid 模块整体 mock（不测库本身）:
 * - render 成功 → 注入 SVG（白底容器）
 * - render 失败（语法错误）→ 回退 ShikiCodeBlock 源码展示 + 提示
 * - 加载中 → 占位
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const renderMock = vi.fn();
const initializeMock = vi.fn();

vi.mock('mermaid', () => ({
  default: {
    initialize: (...args: unknown[]) => initializeMock(...args),
    render: (...args: unknown[]) => renderMock(...args),
  },
}));

import { I18nProvider } from '../../../shared/lib/i18n';
import {
  MermaidBlock,
  formatMermaidBlockAuditJson,
  formatMermaidBlockAuditSnapshot,
} from '../MermaidBlock';

const FLOWCHART = 'graph TD\n  A[开始] --> B[结束]';

const renderBlock = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('MermaidBlock (U7\')', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.documentElement.classList.remove('dark');
  });

  it('成功渲染：注入 SVG 并按主题初始化', async () => {
    renderMock.mockResolvedValue({ svg: '<svg><text>ok</text></svg>' });
    renderBlock(<MermaidBlock code={FLOWCHART} />);

    // 加载占位先出现
    expect(screen.getByTestId('mermaid-loading')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('mermaid-figure')).toBeInTheDocument();
    });
    expect(renderMock).toHaveBeenCalledWith(expect.any(String), FLOWCHART);
    // light 主题 → 'default'
    expect(initializeMock).toHaveBeenCalledWith(expect.objectContaining({ theme: 'default' }));
    expect(screen.queryByTestId('mermaid-fallback')).not.toBeInTheDocument();
  });

  it('dark 模式下用 dark 主题初始化', async () => {
    document.documentElement.classList.add('dark');
    renderMock.mockResolvedValue({ svg: '<svg></svg>' });
    renderBlock(<MermaidBlock code={FLOWCHART} />);

    await waitFor(() => {
      expect(screen.getByTestId('mermaid-figure')).toBeInTheDocument();
    });
    expect(initializeMock).toHaveBeenCalledWith(expect.objectContaining({ theme: 'dark' }));
  });

  it('渲染失败：回退源码展示（ShikiCodeBlock）+ 提示', async () => {
    renderMock.mockRejectedValue(new Error('Parse error'));
    renderBlock(<MermaidBlock code={FLOWCHART} />);

    await waitFor(() => {
      expect(screen.getByTestId('mermaid-fallback')).toBeInTheDocument();
    });
    // 源码原样可见（Shiki 异步高亮前也渲染原始文本）
    expect(screen.getByText(/graph TD/)).toBeInTheDocument();
    expect(screen.getByText(/渲染失败/)).toBeInTheDocument();
    expect(screen.queryByTestId('mermaid-figure')).not.toBeInTheDocument();
  });

  it('formats MermaidBlock audit snapshot/JSON and supports copy controls (P103)', async () => {
    expect(
      formatMermaidBlockAuditSnapshot({
        state: 'ready',
        theme: 'default',
        zoomPct: 100,
        fullscreen: false,
        codeLength: 25,
      }),
    ).toBe('state=ready|theme=default|zoom=100|fs=0|len=25');
    expect(
      JSON.parse(
        formatMermaidBlockAuditJson({
          state: 'failed',
          theme: 'dark',
          zoomPct: 125,
          fullscreen: true,
          codeLength: 10,
        }),
      ),
    ).toEqual({
      state: 'failed',
      theme: 'dark',
      zoomPct: 125,
      fullscreen: true,
      codeLength: 10,
    });

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderMock.mockResolvedValue({ svg: '<svg><text>ok</text></svg>' });
    renderBlock(<MermaidBlock code={FLOWCHART} />);
    await waitFor(() => {
      expect(screen.getByTestId('mermaid-figure')).toHaveAttribute(
        'data-mermaid-block-audit',
        `state=ready|theme=default|zoom=100|fs=0|len=${FLOWCHART.length}`,
      );
    });
    fireEvent.click(screen.getByTestId('mermaid-block-audit-copy'));
    expect(writeText).toHaveBeenCalledWith(
      `state=ready|theme=default|zoom=100|fs=0|len=${FLOWCHART.length}`,
    );
    fireEvent.click(screen.getByTestId('mermaid-block-audit-copy-json'));
    expect(writeText).toHaveBeenCalledTimes(2);
  });
});
