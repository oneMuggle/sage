// src/widgets/chat/__tests__/MermaidDiagram.test.tsx
//
// 2026-11-04 (rich-preview-rendering Task 3): MermaidDiagram 交互单测 ——
// 覆盖工具条、源码视图切换、解析错误详情、拖拽平移、Ctrl+滚轮缩放、
// 双击复位、适应屏幕/实际大小、SVG 下载、复制源码与全屏开关。
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const renderMock = vi.fn();
const parseMock = vi.fn();
const initializeMock = vi.fn();

vi.mock('mermaid', () => ({
  default: {
    initialize: (...args: unknown[]) => initializeMock(...args),
    render: (...args: unknown[]) => renderMock(...args),
    parse: (...args: unknown[]) => parseMock(...args),
  },
}));

import { I18nProvider } from '../../../shared/lib/i18n';
import { MermaidDiagram } from '../MermaidDiagram';

const FLOWCHART = 'graph TD\n  A[开始] --> B[结束]';

// 错误回退分支渲染 ShikiCodeBlock，需要 I18nProvider（与 MermaidBlock.test.tsx 一致）
async function renderDiagram(code: string = FLOWCHART): Promise<void> {
  render(
    <I18nProvider defaultLocale="zh">
      <MermaidDiagram code={code} theme="default" />
    </I18nProvider>,
  );
  await waitFor(() => expect(screen.getByTestId('mermaid-figure')).toBeInTheDocument());
}

describe('MermaidDiagram', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.documentElement.classList.remove('dark');
    renderMock.mockResolvedValue({ svg: '<svg data-testid="mermaid-svg"><text>ok</text></svg>' });
    parseMock.mockResolvedValue(true);
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => 'blob:mock-url');
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('工具条包含缩放/适应屏幕/实际大小/源码切换/下载 SVG 等入口', async () => {
    await renderDiagram();
    expect(screen.getByTestId('mermaid-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-zoom-in')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-zoom-out')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-fit')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-actual-size')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-toggle-source')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-download-png')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-download-svg')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-copy-source')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-fullscreen-open')).toBeInTheDocument();
  });

  it('点击源图切换后显示源码 textarea 并带原文', async () => {
    await renderDiagram();
    expect(screen.queryByTestId('mermaid-source-textarea')).toBeNull();
    fireEvent.click(screen.getByTestId('mermaid-toggle-source'));
    const textarea = screen.getByTestId('mermaid-source-textarea');
    expect(textarea).toHaveValue(FLOWCHART);
    // 再次点击回到图表
    fireEvent.click(screen.getByTestId('mermaid-toggle-source'));
    expect(screen.queryByTestId('mermaid-source-textarea')).toBeNull();
    expect(screen.getByTestId('mermaid-figure')).toBeInTheDocument();
  });

  it('解析失败时回退源码并展示错误详情', async () => {
    parseMock.mockRejectedValue(new Error('Syntax error at line 3'));
    render(
      <I18nProvider defaultLocale="zh">
        <MermaidDiagram code="invalid" theme="default" />
      </I18nProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('mermaid-fallback')).toBeInTheDocument());
    expect(screen.getByTestId('mermaid-error-detail')).toHaveTextContent('Syntax error at line 3');
    expect(screen.queryByTestId('mermaid-figure')).toBeNull();
  });

  it('拖拽平移更新画布位移', async () => {
    await renderDiagram();
    const viewport = screen.getByTestId('mermaid-viewport');
    fireEvent.pointerDown(viewport, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(viewport, { clientX: 30, clientY: 40 });
    fireEvent.pointerUp(viewport);
    expect(screen.getByTestId('mermaid-canvas').style.transform).toContain('translate(20px, 30px)');
  });

  it('Ctrl+滚轮放大，未按 Ctrl 时不缩放', async () => {
    await renderDiagram();
    const viewport = screen.getByTestId('mermaid-viewport');
    await act(async () => {
      viewport.dispatchEvent(
        new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true, cancelable: true }),
      );
    });
    await waitFor(() => expect(screen.getByTestId('mermaid-zoom-label')).toHaveTextContent('125%'));

    await act(async () => {
      viewport.dispatchEvent(
        new WheelEvent('wheel', { deltaY: -100, ctrlKey: false, bubbles: true, cancelable: true }),
      );
    });
    expect(screen.getByTestId('mermaid-zoom-label')).toHaveTextContent('125%');
  });

  it('双击画布复位到实际大小（清空位移）', async () => {
    await renderDiagram();
    const viewport = screen.getByTestId('mermaid-viewport');
    fireEvent.pointerDown(viewport, { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(viewport, { clientX: 25, clientY: 25 });
    fireEvent.pointerUp(viewport);
    expect(screen.getByTestId('mermaid-canvas').style.transform).toContain('translate(25px, 25px)');

    fireEvent.doubleClick(viewport);
    const transform = screen.getByTestId('mermaid-canvas').style.transform;
    expect(transform).toContain('scale(1)');
    expect(transform).not.toContain('translate');
  });

  it('工具条缩放按钮与实际大小/适应屏幕复位生效', async () => {
    await renderDiagram();
    fireEvent.click(screen.getByTestId('mermaid-zoom-in'));
    expect(screen.getByTestId('mermaid-zoom-label')).toHaveTextContent('125%');
    fireEvent.click(screen.getByTestId('mermaid-zoom-out'));
    expect(screen.getByTestId('mermaid-zoom-label')).toHaveTextContent('100%');

    fireEvent.click(screen.getByTestId('mermaid-zoom-in'));
    fireEvent.click(screen.getByTestId('mermaid-actual-size'));
    expect(screen.getByTestId('mermaid-zoom-label')).toHaveTextContent('100%');

    // 适应屏幕：容器尺寸不可用时退回 100%
    fireEvent.click(screen.getByTestId('mermaid-zoom-in'));
    fireEvent.click(screen.getByTestId('mermaid-fit'));
    expect(screen.getByTestId('mermaid-zoom-label')).toHaveTextContent('100%');
  });

  it('下载 SVG 生成 image/svg+xml blob', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await renderDiagram();
    fireEvent.click(screen.getByTestId('mermaid-download-svg'));
    expect(URL.createObjectURL).toHaveBeenCalled();
    const blob = (URL.createObjectURL as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as Blob;
    expect(blob.type).toContain('image/svg+xml');
    expect(blob.size).toBeGreaterThan(0);
    clickSpy.mockRestore();
  });

  it('复制源码写入原始 mermaid 文本', async () => {
    await renderDiagram();
    fireEvent.click(screen.getByTestId('mermaid-copy-source'));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(FLOWCHART);
    // 等 setCopied 的异步状态更新落定，避免 act() 警告
    await waitFor(() => expect(screen.getByLabelText('已复制')).toBeInTheDocument());
  });

  it('全屏开关：打开 portal 覆盖层，ESC 关闭', async () => {
    await renderDiagram();
    fireEvent.click(screen.getByTestId('mermaid-fullscreen-open'));
    expect(screen.getByTestId('mermaid-fullscreen')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('mermaid-fullscreen')).not.toBeInTheDocument();
    expect(screen.getByTestId('mermaid-figure')).toBeInTheDocument();
  });
});
