/**
 * P1 (UI 优化方案 2026-09-13): MermaidBlock 图表工具栏 — 全屏开关行为。
 * mermaid 模块 mock 方式与 MermaidBlock.test.tsx 一致。
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
import { MermaidBlock } from '../MermaidBlock';

const FLOWCHART = 'graph TD\n  A[开始] --> B[结束]';

describe('MermaidBlock toolbar (P1)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.documentElement.classList.remove('dark');
  });

  it('toolbar 渲染在图表容器上，含全屏/下载/复制入口', async () => {
    renderMock.mockResolvedValue({ svg: '<svg></svg>' });
    render(
      <I18nProvider defaultLocale="zh">
        <MermaidBlock code={FLOWCHART} />
      </I18nProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('mermaid-figure')).toBeInTheDocument());
    expect(screen.getByTestId('mermaid-toolbar')).toBeInTheDocument();
    expect(screen.getByLabelText('全屏')).toBeInTheDocument();
    expect(screen.getByLabelText('下载 PNG')).toBeInTheDocument();
    expect(screen.getByLabelText('复制源码')).toBeInTheDocument();
  });

  it('点击全屏打开 portal 覆盖层，ESC 关闭', async () => {
    renderMock.mockResolvedValue({ svg: '<svg></svg>' });
    render(
      <I18nProvider defaultLocale="zh">
        <MermaidBlock code={FLOWCHART} />
      </I18nProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('mermaid-figure')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('mermaid-fullscreen-open'));
    expect(screen.getByTestId('mermaid-fullscreen')).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('mermaid-fullscreen')).not.toBeInTheDocument();
  });
});
